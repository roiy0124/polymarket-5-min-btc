"""VOL CIRCUIT-BREAKER — does the maker's quote go STALE during vol spikes, and is that tradable?

Research finding (warproxxx/poly-maker, the real public MM): the bot uses a volatility CIRCUIT-BREAKER +
HYSTERESIS-CANCEL — when realized vol spikes it stops/freezes quoting (re-quotes only on a >0.5c move),
so its quote goes STALE and one-sided for ~10s, exactly when spot is moving fast. Hypothesis: right after
a sharp spot move, the favored side (direction of the move) is UNDER-priced by the laggy quote -> a
fair-value taker edge that should be CONCENTRATED in high-realized-vol windows.

Two questions, both causal (use only data up to the decision instant):
  MECHANISM  : does the quote lag spot MORE in high-vol regimes? (quote under-reacts; then catches up)
  TRADABILITY: buy the favored side (up if recent spot return>0 else down) at its ask, hold to 0/1; is
               net-EV (taker fee + spread) positive, and bigger in the high-vol / big-move buckets?

Decision grid: tl in {240,180,120,90,60} (skip first/last 60s). Recent move = 5s spot return; realized
vol = trailing 60s. HONEST PRIOR: the faster-feed work already showed the ~1s quote lag is real but the
SPREAD caps it at ~breakeven; the circuit-breaker refinement is whether the staleness is fat enough in
spike windows to clear fee+spread. Likely still walled, but it's a SPECIFIC mechanism, not a vague edge.

VERDICT (2026-06-27, second-mind validated agent a12112dc): the TAKER leg is FEE-WALLED both directions
(momentum cell -0.060, contrarian cell -0.087, same resid -0.014, both deflated p=1.0) -> the negative is the
0.07*(1-p) taker fee at near-0.5 prices, NOT a verdict on the maker mechanism. The freeze is NOT observable at
1/s (sub-second; the 1/s quote looks fully responsive). BUT the 1/s up_book/down_book ladders DO show the
footprint: in the high-vol/big-move cell the favored side's depth ~HALVES and the ask/bid depth ratio drops
0.98->0.90 (asymmetric thinning), though the book stays two-sided (true one-sidedness is L2-only). CORRECT
STATUS: taker leg CLOSED (known taker wall); the fee-free MAKER leg (rest the abandoned-side quote in the
spike, earn rebate, no taker fee) is UNTESTED and needs the L2 build (maker-fill sim vs book_events + depth
one-sidedness). This SHAPES the L2 capture: log depth one-sidedness (overall_ratio) + abandoned-side detection.

    python experiment_vol_circuit_breaker.py
"""
import sqlite3
import bisect

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from analysis import stats as S
from net_ev import net_ev_per_dollar, wilson_lb, breakeven_winrate

GRID = [240, 180, 120, 90, 60]
MOVE_S = 5      # recent-move lookback (s)
VOL_S = 60      # realized-vol window (s)
NEXT_S = 5      # quote catch-up window (s) for the mechanism test


def load(coin):
    out = []
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute(
                "SELECT window_start, resolved_outcome FROM windows WHERE resolved_outcome IN ('Up','Down')").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, outcome in wins:
            snaps = con.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND down_ask IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY time_left DESC", (ws,)).fetchall()
            if len(snaps) < 60:
                continue
            tl = np.array([s[0] for s in snaps], float)
            um = np.array([s[1] for s in snaps]); ua = np.array([s[2] for s in snaps])
            da = np.array([s[3] for s in snaps]); px = np.array([s[4] for s in snaps])
            order = np.argsort(-tl)               # already desc, but be safe
            tl, um, ua, da, px = tl[order], um[order], ua[order], da[order], px[order]
            def at(target):
                i = int(np.argmin(np.abs(tl - target)))
                return i if abs(tl[i] - target) <= 3 else None
            for g in GRID:
                i = at(g)
                if i is None:
                    continue
                ip = at(g + MOVE_S)               # MOVE_S earlier (more time_left)
                iv = at(g + VOL_S)
                inx = at(g - NEXT_S)              # NEXT_S later (catch-up)
                if ip is None or iv is None or px[ip] <= 0:
                    continue
                r5 = np.log(px[i] / px[ip])
                # trailing realized vol over [g, g+VOL_S]
                seg = px[min(i, iv):max(i, iv) + 1]
                if len(seg) < 8:
                    continue
                lr = np.diff(np.log(seg))
                rvol = np.sqrt(np.mean(lr ** 2)) if len(lr) else 0.0
                if rvol <= 0 or not np.isfinite(r5):
                    continue
                fav_up = r5 > 0
                ask = ua[i] if fav_up else da[i]
                if not (0.05 < ask < 0.98):
                    continue
                won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
                dmid_now = um[i] - um[ip]                                  # quote move during the spot move
                dmid_next = (um[inx] - um[i]) if inx is not None else np.nan  # catch-up after
                out.append((ws, g, r5, rvol, ask, won, dmid_now, dmid_next, fav_up))
        con.close()
    return out


def main():
    rows = []
    for c in coins.ENABLED:
        rows += [(c,) + r for r in load(c)]
    co = np.array([r[0] for r in rows]); ws = np.array([r[1] for r in rows])
    r5 = np.array([r[3] for r in rows]); rvol = np.array([r[4] for r in rows])
    ask = np.array([r[5] for r in rows]); won = np.array([r[6] for r in rows], float)
    dnow = np.array([r[7] for r in rows]); dnext = np.array([r[8] for r in rows]); favup = np.array([r[9] for r in rows])
    n = len(rows)
    print(f"VOL CIRCUIT-BREAKER  n={n}  (fair-value taker: buy the side of the last 5s spot move, hold 0/1)")
    print("=" * 92)

    # --- MECHANISM: does the quote lag MORE (catch up MORE after) in high vol? ---
    # signed move direction; quote should move WITH r5. lag = quote catches up afterward (dnext same sign as r5)
    s = np.sign(r5)
    catchup = s * dnext                      # >0 = quote kept moving the move's way after = it had lagged
    print("  MECHANISM — quote catch-up AFTER the move (>0 = quote lagged, then caught up), by realized-vol tercile:")
    vt = np.quantile(rvol, [0, 1/3, 2/3, 1.0])
    for i in range(3):
        m = (rvol >= vt[i]) & (rvol <= vt[i+1] if i == 2 else rvol < vt[i+1]) & np.isfinite(catchup)
        lbl = ["low-vol", "mid-vol", "high-vol"][i]
        print(f"      {lbl:>8}: n={int(m.sum()):>5}  mean catch-up {np.nanmean(catchup[m]):+.5f}  "
              f"(quote moved {np.nanmean((s*dnow)[m]):+.5f} WITH the move during it)")

    # --- TRADABILITY: net-EV of the favored-side taker, by vol regime x move size ---
    print("\n  TRADABILITY — favored-side taker net-EV, by realized-vol tercile x |5s move| tercile:")
    print(f"      {'':>10} {'small move':>12} {'mid move':>12} {'big move':>12}")
    mt = np.quantile(np.abs(r5), [0, 1/3, 2/3, 1.0])
    def evcell(m):
        if m.sum() < 15:
            return "  n<15"
        per = [net_ev_per_dollar(a, w, "taker", "hold") for a, w in zip(ask[m], won[m])]
        return f"{np.mean(per):+.4f}(n{int(m.sum())})"
    for i in range(3):
        vm = (rvol >= vt[i]) & (rvol <= vt[i+1] if i == 2 else rvol < vt[i+1])
        cells = []
        for j in range(3):
            mm = vm & (np.abs(r5) >= mt[j]) & (np.abs(r5) <= mt[j+1] if j == 2 else np.abs(r5) < mt[j+1])
            cells.append(evcell(mm))
        print(f"      {['low-vol','mid-vol','high-vol'][i]:>10} {cells[0]:>12} {cells[1]:>12} {cells[2]:>12}")

    # the circuit-breaker cell = high-vol & big-move; gate it honestly
    cb = (rvol >= vt[2]) & (np.abs(r5) >= mt[2])
    print(f"\n  CIRCUIT-BREAKER CELL (high-vol & big-move): n={int(cb.sum())}")
    if cb.sum() >= 20:
        a = S.assess(ask[cb], won[cb], ws[cb], n_trials=S.N_PROGRAM, label="circuit-breaker fair-value taker")
        S.print_assess(a)
    print("\n  READ: MECHANISM confirmed if catch-up RISES with vol (quote lags more in spikes). TRADABLE if the")
    print("  high-vol/big-move cell is clearly +EV through the gate (staleness beats fee+spread). Prior: likely")
    print("  walled by the fee at these near-0.5 prices, but a real +EV high-vol cell would be the first taker edge.")


if __name__ == "__main__":
    main()

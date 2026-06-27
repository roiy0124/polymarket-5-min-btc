"""VRP HARVEST — buy the favorite when the maker over-charges volatility (trade the bot's sigma, not BTC).

The maker is a fair-value bot quoting up_mid = Phi(ln(spot/strike)/(sigma*sqrt(t))) (R2=0.91). Its ONE free
input is sigma. It pads vol (median implied/realized ~1.15 = a Variance Risk Premium, a documented 0DTE
edge). When it OVER-charges vol (implied sigma >> a causal estimate of realized), it pulls its probability
toward 0.5 and UNDER-PRICES the favorite -> buying the favorite harvests the VRP. This is the classic
short-implied/long-realized VRP harvest, expressed in this market.

CAUSAL signal at the decision instant (favorite-tail, tl~30, ask in [0.95,0.99)):
  implied_sigma  = back out from the quote:  sigma = |ln(spot/strike)/sqrt(tl)| / |Phi^-1(up_mid)|
  realized_sigma = per-sqrt-second realized vol of spot over the TRAILING window (tl in [30,150]) -- causal,
                   the best estimate of the forward (remaining-30s) flip risk.
  VRP_ratio      = implied / realized  (>1 = maker over-charging vol = favorite under-priced = harvest)
Then STACK with over-round-tight (the orthogonal maker-confidence read; corr(VRP, over_round) ~ -0.03).

HONEST TAIL NOTE: a VRP harvest IS short-vol -- it pays the premium until realized vol spikes and the
favorite flips (-100%). So the risk lives entirely in the loss count; report it and gate, don't hide it.

    python experiment_vrp_harvest.py
"""
import sqlite3

import numpy as np
from scipy import stats as ss

import coins
from analysis import stats as S
from net_ev import net_ev_per_dollar, wilson_lb, breakeven_winrate

PHIINV = ss.norm.ppf


def load(coin):
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute(
                "SELECT window_start, strike_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen or strike <= 0:
                continue
            seen.add(ws)
            path = con.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND down_ask IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY time_left DESC", (ws,)).fetchall()
            if len(path) < 30:
                continue
            dec = min(path, key=lambda r: abs(r[0] - 30))
            tl, um, ua, da, px = dec
            if abs(tl - 30) > 10 or not (0.95 <= max(ua, da) < 1.0) or not (0.02 < um < 0.98):
                continue
            z = PHIINV(um)
            if abs(z) < 0.3:                       # favorites only -> z is large -> implied sigma stable
                continue
            implied = abs(np.log(px / strike) / np.sqrt(tl) / z)
            # causal TRAILING realized vol over tl in [30,150] (the ~2 min before decision)
            tw = [(300 - r[0], r[4]) for r in path if 30 <= r[0] <= 150]
            if len(tw) < 15:
                continue
            tw.sort()
            t = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
            lr = np.diff(np.log(sp)); dt = np.diff(t); ok = dt > 0
            if ok.sum() < 10:
                continue
            realized = np.sqrt(np.mean(lr[ok] ** 2 / dt[ok]))
            if not (implied > 0 and realized > 0 and np.isfinite(implied) and np.isfinite(realized)):
                continue
            fav_up = px >= strike; fa = ua if fav_up else da
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fa, won, implied / realized, ua + da - 1.0))
        con.close()
    return out


def ev(A, W):
    if len(A) < 10:
        return None
    per = [net_ev_per_dollar(a, w, "taker", "hold") for a, w in zip(A, W)]
    return len(A), int((W == 0).sum()), 100 * W.mean(), sum(per) / len(per), \
        wilson_lb(int(W.sum()), len(W)) - breakeven_winrate(A.mean())


def main():
    rows = []
    for c in coins.ENABLED:
        rows += [(c,) + r for r in load(c)]
    ws = np.array([r[1] for r in rows]); A = np.array([r[2] for r in rows]); W = np.array([r[3] for r in rows])
    VRP = np.array([r[4] for r in rows]); OR = np.array([r[5] for r in rows])
    print(f"VRP HARVEST  favorite-tail ask[0.95,0.99) tl~30  n={len(rows)} losers={int((W==0).sum())}")
    print(f"  median VRP ratio (implied/trailing-realized) = {np.median(VRP):.2f}   "
          f"corr(VRP, over_round) = {np.corrcoef(VRP, OR)[0,1]:+.3f}  (orthogonal stack-partner?)")
    print("=" * 88)
    print(f"  {'VRP ratio bucket':>24} {'n':>5} {'loss':>4} {'win%':>6} {'EV':>8} {'wlb-be':>8}")
    qs = np.quantile(VRP, [0, 0.5, 0.7, 0.85, 1.0])
    for i in range(len(qs) - 1):
        m = (VRP >= qs[i]) & (VRP <= qs[i + 1] if i == len(qs) - 2 else VRP < qs[i + 1])
        e = ev(A[m], W[m])
        if e:
            print(f"  {f'[{qs[i]:.2f},{qs[i+1]:.2f})':>24} {e[0]:>5} {e[1]:>4} {e[2]:>5.1f}% {e[3]:>+8.4f} {e[4]:>+8.4f}")
    # the harvest gate + the stack with over-round-tight
    print()
    or_t = OR <= np.median(OR); vrp_hi = VRP >= np.quantile(VRP, 0.7)
    for lbl, m in [("baseline", np.ones(len(A), bool)), ("VRP-high (top 30%)", vrp_hi),
                   ("over-round tight", or_t), ("VRP-high & OR-tight STACK", vrp_hi & or_t)]:
        e = ev(A[m], W[m])
        if e:
            print(f"  {lbl:>26} n={e[0]:>4} loss={e[1]:>3} win={e[2]:.1f}% EV={e[3]:+.4f} wlb-be={e[4]:+.4f}")
    m = vrp_hi & or_t
    if m.sum() > 20:
        a = S.assess(A[m], W[m], ws[m], n_trials=S.N_PROGRAM, label="VRP-harvest x over-round stack")
        S.print_assess(a)
    print("\n  READ: harvest works if VRP-high favorites win MORE than priced (+EV), monotone in the ratio, AND")
    print("  the stack with over-round-tight (orthogonal) lifts it further with a non-trivial loss count.")


if __name__ == "__main__":
    main()

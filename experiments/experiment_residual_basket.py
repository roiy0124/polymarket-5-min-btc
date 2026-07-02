"""MOVE 2 — cross-sectional, beta-neutral RESIDUAL BASKET (Avellaneda-Lee on the alt tokens).

The one structurally-different corner the program never measured. Every prior test was a
SINGLE-NAME directional bet on a NEGATIVE-EV favorite base; this is market-neutral RELATIVE value:

  Each 5-min window, rank the present alts by their idiosyncratic SPOT residual z (adaptive
  cross-asset detector — how oversold/overbought the coin is vs BTC/ETH). LONG the Up-token of the
  most-OVERSOLD alt (z lowest -> expect mean-reversion UP) and SHORT the Up-token of the most-
  OVERBOUGHT (z highest -> buy its Down-token). Equal $, hold to 0/1, taker fee on BOTH legs.

Why it could clear walls that killed everything else: (a) the long/short cancels the COMMON market
move -> sidesteps the efficiency wall (it bets the RELATIVE residual, which the quote may not fully
price); (b) a long/short pair has BOUNDED loss, not the -100% single-name tail that makes every
n=18 test degenerate. HEADWIND: pays ~2 taker fees (~7% round-trip near p=0.5), and PC1 rose
61->84% so the idiosyncratic spread it harvests is shrinking ([[cross-asset-factor-structure]]).

Verdict via the rigor module (deflated-Sharpe / PSR / cluster-bootstrap). Causal: spot z uses only
data up to the decision second.

    python experiment_residual_basket.py [--tl 30] [--hl 300]
"""
import argparse
import sqlite3

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from analysis import stats as S
from net_ev import net_ev_per_dollar
from experiment_spike_fade import spot_z_lookups, z_at

ALTS = [c for c in coins.ENABLED if c not in ("btc", "eth")]


def load_tokens(coins_list, tl, tol):
    """data[coin][ws] = (up_ask, down_ask, up_mid, won) at the snapshot nearest time_left=tl."""
    data = {c: {} for c in coins_list}
    for c in coins_list:
        for db in coins.all_dbs(c):
            try:
                conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            except sqlite3.Error:
                continue
            try:
                wins = conn.execute("SELECT window_start, resolved_outcome FROM windows "
                                    "WHERE resolved_outcome IN ('Up','Down')").fetchall()
            except sqlite3.OperationalError:
                conn.close(); continue
            for ws, outcome in wins:
                if ws in data[c]:
                    continue
                snap = conn.execute(
                    "SELECT up_ask, down_ask, up_mid, time_left FROM snapshots WHERE window_start=? "
                    "AND up_ask IS NOT NULL AND down_ask IS NOT NULL ORDER BY ABS(time_left-?) LIMIT 1",
                    (ws, tl)).fetchone()
                if snap and abs(snap[3] - tl) <= tol:
                    data[c][ws] = (snap[0], snap[1], snap[2], 1 if outcome == "Up" else 0)
            conn.close()
    return data


def build_basket(data, lk, tl, band=(0.20, 0.85)):
    """Return (basket_returns, wsids, n_long_win, n_short_win). One basket per window with >=3 alts
    that have a valid spot z and mid-band tokens."""
    rets, wsids = [], []
    all_ws = set().union(*[set(data[c]) for c in ALTS])
    for ws in all_ws:
        cand = {}
        for c in ALTS:
            if ws not in data[c]:
                continue
            ua, da, um, won = data[c][ws]
            if um is None or not (band[0] <= um <= band[1]):
                continue
            z = z_at(lk, c, ws + (300 - tl))          # idiosyncratic spot z at the decision second
            if z is not None:
                cand[c] = (z, ua, da, won)
        if len(cand) < 3:
            continue
        order = sorted(cand.items(), key=lambda kv: kv[1][0])   # ascending z
        (_, (_, ua_l, _, won_l)) = order[0]                      # most oversold -> long Up
        (_, (_, _, da_s, won_s)) = order[-1]                     # most overbought -> short Up = buy Down
        r_long = net_ev_per_dollar(ua_l, won_l, "taker", "hold")
        r_short = net_ev_per_dollar(da_s, 1 - won_s, "taker", "hold")   # Down-token wins iff overbought alt went Down
        if r_long is None or r_short is None:
            continue
        rets.append(0.5 * (r_long + r_short))                    # equal-$ market-neutral basket
        wsids.append(ws)
    return np.array(rets), np.array(wsids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--hl", type=float, default=300.0)
    ap.add_argument("--start", default="2026-06", help="spot month covering the token windows")
    ap.add_argument("--n-trials", type=int, default=10, help="honest # of basket configs searched")
    a = ap.parse_args()

    print("loading tokens ...", flush=True)
    data = load_tokens(ALTS, a.tl, 12.0)
    for c in ALTS:
        print(f"  {c}: {len(data[c])} windows")
    print("loading 1s spot + adaptive z ...", flush=True)
    lk = spot_z_lookups(a.start, a.hl)
    rets, wsids = build_basket(data, lk, a.tl)

    print(f"\nRESIDUAL BASKET  (long oversold Up / short overbought Up, equal-$, hold 0/1, 2 taker legs)")
    print(f"  baskets n={len(rets)}")
    if len(rets) < 10:
        print("  too few baskets to assess."); return
    mean, lo, hi, p1, pdef = S.deflated_resid_p(rets, wsids, a.n_trials)
    survives = bool(np.isfinite(pdef) and pdef < 0.05 and lo > 0)
    print(f"  mean basket EV/$1 {mean:+.4f}  cluster-CI[{lo:+.4f},{hi:+.4f}]  Sharpe {S.sharpe(rets):+.3f}  "
          f"skew {float(__import__('scipy.stats',fromlist=['skew']).skew(rets)):+.2f}")
    print(f"  PRIMARY: deflated cluster-bootstrap p (vs N={a.n_trials}) = {pdef:.3f}   (raw one-sided p={p1:.3f})")
    print(f"  => {'SURVIVES' if survives else 'FAILS'}   (gate: deflated p<0.05 AND cluster-CI>0)")
    print("\n  NOTE: basket pays ~2 taker fees (~7% near p=0.5); the relative-residual edge must clear that.")
    print("  A market-neutral basket has bounded loss (no -100% tail), so n_loss-gating doesn't apply here.")


if __name__ == "__main__":
    main()

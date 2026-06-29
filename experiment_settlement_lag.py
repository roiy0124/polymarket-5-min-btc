"""SETTLEMENT-CONVERGENCE LAG — buy the near-locked late winner before it converges to 1.0 (NEW 2026-06-26).

A DIFFERENT mechanism from the over-round gate (which is maker-confidence at tl~30). Here: in the FINAL
seconds (tl~5), when spot is CLEARLY past the strike (large Binance margin = the Chainlink outcome is
effectively locked, spot can't cross back in 5s), the winning token still trades a few tenths of a percent
BELOW 1.0 (it hasn't fully converged). Buy that near-certain winner at its ask, hold to 0/1 — collect the
convergence lag. The taker fee is tiny here (0.07*(1-p) ~ 0.1% at ask 0.99), so a ~0.3-0.6% lag clears it.

Causal: margin = |price_binance - strike|/strike at the decision instant (tl~5). Margin self-normalized
PER COIN (the same bps means a different #-of-seconds-of-vol on BTC vs DOGE; per-coin percentile is the
regime-correct certainty measure — adaptivity policy).

VERDICT (2026-06-26, second-mind reviewed agent abfc1a9a): DEAD -> ideas_old/settlement-lag.md. The +0.0063
at margin>=3bp is a MARGIN CHERRY-PICK (the ungated effect is NEGATIVE -0.0015; EV shrinks monotonically as
margin tightens), it FAILS honest deflation (deflated p=0.89 at the correct N=200), and the KILLER is the
SETTLEMENT BASIS: the favorite is picked on BINANCE but settles on CHAINLINK. An independent oracle (Pyth)
disagrees with Binance on the favored side 2.79% of the time at the decision instant -- the edge needs the
true flip rate < 1.24% (=1-ask). All 5 in-sample losers were already basis flips; the 0.53% in-sample rate is
a lucky small-sample draw from a true ~2.8% flip-proneness. At the true rate net-EV is NEGATIVE (-0.006 to
-0.017). Plus thin depth (~$70 median fill). The convergence-lag is self-defeating: the boundary where the
token lags is exactly where the Binance/Chainlink basis flips outcomes (the resolution-source caveat in
CLAUDE.md). Kept as a tooling artifact; the flip-rate-bound test is the reusable part.

    python experiment_settlement_lag.py [--adaptive]
"""
import argparse
import sqlite3

import numpy as np

import coins
from analysis import stats as S
from analysis.adaptive import rolling_pct_rank
from net_ev import wilson_lb, breakeven_winrate


def load(coin, tl=5.0, lo=2.0, hi=8.0, ask_lo=0.95):
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = conn.execute(
                "SELECT window_start, strike_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            conn.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen:
                continue
            seen.add(ws)
            r = conn.execute(
                "SELECT time_left, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_ask IS NOT NULL AND down_ask IS NOT NULL AND price_binance IS NOT NULL "
                "AND time_left<=? AND time_left>=? ORDER BY ABS(time_left-?) LIMIT 1", (ws, hi, lo, tl)).fetchone()
            if not r:
                continue
            t_l, ua, da, px = r
            fav_up = px >= strike
            fa = ua if fav_up else da
            if fa < ask_lo or fa >= 1.0 or not strike:
                continue
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fa, won, abs(px - strike) / strike * 1e4))
        conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adaptive", action="store_true", help="per-coin self-normalized margin (recommended)")
    ap.add_argument("--margin-bp", type=float, default=3.0, help="fixed margin threshold (bps) if not adaptive")
    ap.add_argument("--pct", type=float, default=0.5, help="adaptive: keep margin rolling-pct-rank >= this")
    ap.add_argument("--lookback", type=int, default=200)
    args = ap.parse_args()

    rows = []
    for c in coins.ENABLED:
        for r in load(c):
            rows.append((c,) + r)
    co = np.array([r[0] for r in rows]); ws = np.array([r[1] for r in rows]); A = np.array([r[2] for r in rows])
    W = np.array([r[3] for r in rows]); MG = np.array([r[4] for r in rows])
    print(f"SETTLEMENT-CONVERGENCE LAG  tl~5  ask>=0.95  n={len(rows)}  ({'adaptive per-coin' if args.adaptive else 'fixed'} margin)")
    print("=" * 84)
    if args.adaptive:
        gate = rolling_pct_rank(MG, ws, lookback=args.lookback, groups=co) >= args.pct
        gate = np.where(np.isnan(gate), False, gate).astype(bool)
        glabel = f"margin rolling-pct>={args.pct:g} (per-coin)"
    else:
        gate = MG >= args.margin_bp
        glabel = f"margin>={args.margin_bp:g}bp"
    a = S.assess(A[gate], W[gate], ws[gate], n_trials=S.N_PROGRAM, label=f"settlement-lag | {glabel}")
    S.print_assess(a)
    # the decisive honest test: can the in-sample 0/low losers bound the flip rate below what the edge needs?
    n = int(gate.sum()); k = int(W[gate].sum()); ask = A[gate].mean()
    wub_flip = 1 - wilson_lb(k, n)
    need = 1 - ask
    print(f"\n  FLIP-RATE BOUND (the binding test): gated ask {ask:.4f} -> edge needs true flip rate < {need:.4f} (=1-ask).")
    print(f"      Wilson-UB on flip rate = {wub_flip:.4f}  =>  {'OK (bound below need)' if wub_flip < need else 'NOT BOUNDED (could be negative) -> loss-light, INSUFFICIENT'}")
    print("\n  READ: real convergence lag (token < 1.0 when near-locked), net-positive in-sample, but the rare")
    print("  Binance/Chainlink basis flip is unbounded at this n. Pre-registered; re-gate at >=30 gated losers.")


if __name__ == "__main__":
    main()

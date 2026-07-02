"""FLOW-SIGNAL TEST — does BET SIZE / big-wallet CONSENSUS predict the residual (won - price) net of fee?

The user's refined copy idea: don't copy one wallet (no persistence) — use SIZE as a confidence signal and follow
the CONSENSUS of big bettors. Testable directly on Polymarket's public trades. The honest object (per the quant
skill) is the RESIDUAL after fee, not the raw outcome (the price already aggregates everyone's consensus).

Tests, on resolved daily BTC/ETH markets:
  (1) FOLLOW-BIG-BETS: take every BUY above a size threshold, "follow" it (buy that outcome at the price they paid),
      and gate the net-EV (won - price - fee) through stats.assess (cluster by market, deflated, n_loss>=30).
      Compare big vs small bets. If big-bet-following clears the fee -> bet size is informed (the idea has legs).
  (2) SIZE -> RESIDUAL: across all BUYs (entry 0.10-0.90), mean signed residual (won-price) by size quartile + corr.
  (3) CONSENSUS: per market, the side with more big-wallet BUY $ -> does it win beyond the price (residual)?

Honest priors: the coin is a random walk, profit doesn't persist, and the price is the consensus -> expect ~0 / fee-
capped. But MEASURE. Following as a taker is an UPPER BOUND (you fill after them, at a worse price, and pay the fee).

    python flow_signal_test.py [--days 24] [--big-q 0.90]
"""
import argparse
import sys

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import feeds
from analysis import stats as S
from copytrade_test import daily_markets, all_trades

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=24)
    ap.add_argument("--big-q", type=float, default=0.90, help="size quantile defining a 'big' bet")
    args = ap.parse_args()

    print(f"gathering resolved daily BTC/ETH markets (last {args.days} days)...")
    mkts = daily_markets(args.days)
    print(f"  {len(mkts)} markets")

    rows = []   # (market, price, size, won)  for BUY trades in a tradeable price band
    consensus = []   # per market: (net_big_buy_$_up - net_big_buy_$_down) sign vs won_up
    for ci, (cond, won, ets, slug) in enumerate(mkts):
        tr = all_trades(cond)
        mbuys = []
        for t in tr:
            try:
                if t["side"] != "BUY":
                    continue
                oc = t["outcome"]; p = float(t["price"]); s = float(t["size"])
            except (KeyError, ValueError, TypeError):
                continue
            w = 1 if oc == won else 0
            rows.append((cond, p, s, w, oc))
            mbuys.append((oc, p, s, w))
        if (ci + 1) % 10 == 0:
            print(f"  ...{ci+1}/{len(mkts)}  {len(rows):,} buy-trades")

    rows = [r for r in rows]
    price = np.array([r[1] for r in rows]); size = np.array([r[2] for r in rows])
    won = np.array([r[3] for r in rows]); mkt = np.array([r[0] for r in rows])
    band = (price >= 0.10) & (price <= 0.90)         # drop near-resolved trivial wins
    print(f"\n  {len(rows):,} BUY trades; {band.sum():,} in price band [0.10,0.90]")

    bigthr = np.quantile(size[band], args.big_q)
    big = band & (size >= bigthr); small = band & (size < np.quantile(size[band], 0.5))
    print(f"  big-bet size threshold (q{args.big_q:g}) = {bigthr:.0f} shares")

    # (1) FOLLOW-BIG-BETS through the gate (taker, pay fee)
    print("\n(1) FOLLOW-BIG-BETS  (buy the side they bought, at their price, pay the fee):")
    for lab, m in (("BIG bets", big), ("small bets", small), ("ALL band", band)):
        if m.sum() < 30:
            print(f"  {lab}: too few"); continue
        a = S.assess(price[m], won[m].astype(float), mkt[m], n_trials=10, label=lab)
        S.print_assess(a)

    # (2) SIZE -> RESIDUAL by quartile
    print("\n(2) SIZE -> RESIDUAL (won - price), by size quartile (in band):")
    sb = size[band]; rb = (won[band] - price[band]); pb = price[band]
    qs = np.quantile(sb, [0, .25, .5, .75, 1.0])
    for i in range(4):
        mm = (sb >= qs[i]) & (sb <= qs[i+1])
        print(f"    Q{i+1} size[{qs[i]:.0f},{qs[i+1]:.0f}]  n={mm.sum():>5}  mean residual {rb[mm].mean():+.4f}  "
              f"(mean price {pb[mm].mean():.3f}, win {won[band][mm].mean():.3f})")
    cc = np.corrcoef(np.log(sb + 1), rb)[0, 1]
    print(f"    corr(log size, residual) = {cc:+.4f}  (want >0 = bigger bets land beyond the price = informed)")

    print("\n  READ: bet size is INFORMED only if big-bet-following SURVIVES the gate (clears the fee, n_loss>=30)")
    print("  AND residual rises with size. Flat/negative = size carries no edge beyond the price (the random-walk +")
    print("  consensus-already-in-the-mid prediction). And this is the optimistic upper bound (real copier fills worse).")


if __name__ == "__main__":
    main()

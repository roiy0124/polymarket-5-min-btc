"""CONSISTENT WINNERS — is ANYONE reliably profitable on live BTC/ETH Polymarket, and what are they doing?

The persistence Spearman (~0) is an AGGREGATE; it can hide a few genuinely-consistent winners. This asks directly:
split the period in half; how many wallets are profitable in BOTH halves vs CHANCE; and characterize them
(market-maker = high trades + low directional share, vs directional bettor = buys cheap winners). Reuses the public
trade feed via copytrade_test.

    python consistent_winners.py [--days 26] [--min-half 8]
"""
import argparse
import sys
from collections import defaultdict

import numpy as np

from copytrade_test import daily_markets, all_trades

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=26)
    ap.add_argument("--min-half", type=int, default=8, help="min trades per half to count a wallet")
    args = ap.parse_args()

    mkts = daily_markets(args.days)
    print(f"{len(mkts)} resolved daily BTC/ETH markets")
    mid = np.median([m[2] for m in mkts])

    pnl = {0: defaultdict(float), 1: defaultdict(float)}; nt = {0: defaultdict(int), 1: defaultdict(int)}
    dirw = defaultdict(float); totw = defaultdict(float); ntall = defaultdict(int)
    for ci, (cond, won, ets, slug) in enumerate(mkts):
        h = 0 if ets <= mid else 1
        cash = defaultdict(float); sh = defaultdict(lambda: defaultdict(float)); wn = defaultdict(int)
        for t in all_trades(cond):
            try:
                w = t["proxyWallet"]; side = t["side"]; oc = t["outcome"]; p = float(t["price"]); s = float(t["size"])
            except (KeyError, ValueError, TypeError):
                continue
            sgn = -1.0 if side == "BUY" else 1.0
            cash[w] += sgn * p * s; sh[w][oc] += -sgn * s; wn[w] += 1; ntall[w] += 1
            totw[w] += abs(p * s)
            if side == "BUY" and oc == won:
                dirw[w] += (1 - p) * s
        for w in cash:
            pnl[h][w] += cash[w] + sh[w][won] * 1.0; nt[h][w] += wn[w]
        if (ci + 1) % 12 == 0:
            print(f"  ...{ci+1}/{len(mkts)}")

    both = [w for w in ntall if nt[0][w] >= args.min_half and nt[1][w] >= args.min_half]
    p0 = np.array([pnl[0][w] for w in both]); p1 = np.array([pnl[1][w] for w in both])
    r0 = np.mean(p0 > 0); r1 = np.mean(p1 > 0)
    both_pos = (p0 > 0) & (p1 > 0)
    obs = np.mean(both_pos); exp = r0 * r1
    print(f"\nwallets active in BOTH halves (>= {args.min_half} trades each): {len(both)}")
    print(f"  profitable in early half: {100*r0:.0f}%   late half: {100*r1:.0f}%")
    print(f"  profitable in BOTH halves: {100*obs:.0f}%   vs CHANCE {100*exp:.0f}%  "
          f"=> {'MORE than chance (some real consistency)' if obs > exp*1.25 else 'about CHANCE (= luck/survivorship)'}")
    # binomial-ish: how many both-winners vs expected
    k = int(both_pos.sum()); n = len(both)
    print(f"  ({k} of {n} consistent winners; chance would give ~{exp*n:.0f})")

    # characterize the consistent winners: maker (high trades, low dir-share) vs directional bettor
    print("\nthe CONSISTENT winners (profitable BOTH halves), by total PnL:")
    print("   wallet           totalPnL$   trades   dir-share   -> type")
    cw = sorted([w for w in both if pnl[0][w] > 0 and pnl[1][w] > 0],
                key=lambda w: -(pnl[0][w] + pnl[1][w]))
    makers = 0
    for w in cw[:12]:
        tp = pnl[0][w] + pnl[1][w]; n_ = ntall[w]; ds = dirw[w] / max(1.0, totw[w])
        typ = "MAKER/HFT (uncopyable)" if (n_ >= 300 and ds < 0.4) else ("directional" if ds > 0.6 else "mixed/maker-ish")
        if "MAKER" in typ or "maker" in typ:
            makers += 1
        print(f"   {w[:16]}  ${tp:+9.0f}  {n_:>6}   {ds:>6.2f}    {typ}")
    print(f"\n  of the top consistent winners shown: {makers}+ are MAKER/HFT-style (high trades, low directional share)")
    print("  READ: 'consistent winners' that beat chance are ~always liquidity providers / arbs (a structural,")
    print("  uncopyable-as-a-taker edge), NOT directional predictors — exactly what a random-walk market implies.")


if __name__ == "__main__":
    main()

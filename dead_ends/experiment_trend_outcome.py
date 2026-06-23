"""Does recent BTC TREND predict the 5-min outcome BEYOND the token price? (experiment)

The user's idea: correlate recent BTC price trend with the probable next-5-min outcome,
to assign a better probability and bet when the market disagrees.

The honest framing (the trap to avoid): trend almost certainly predicts the OUTCOME a
little (BTC well above strike late in the window tends to close Up). That is worthless if
the TOKEN PRICE already reflects it -- and the price is a very good predictor here
(Brier ~0.12 @ 60s left; see analysis.fair_vs_market). So we trade against the price, so
the only edge is whether trend predicts the RESIDUAL = outcome - market_price. We measure
BOTH, side by side:

  * corr(trend, outcome)            -- does trend predict the outcome at all?  (expected: yes)
  * corr(trend, outcome - market)   -- does trend beat the PRICE?  (the edge; expected: ~0)

One observation per window (independence). Window-bootstrap 95% CIs. Buckets show realized
P(Up) vs the market's price within trend bins -- if 'resid' CIs include 0, the price already
priced the trend = no edge. Reuses analysis.panel (honors BTC_ANALYSIS_DAYS to merge old_dbs).

    BTC_ANALYSIS_DAYS=30 python experiment_trend_outcome.py --horizon 60
    BTC_ANALYSIS_DAYS=30 python experiment_trend_outcome.py --horizon 180 --lookbacks 30,60,120

*** Even a real residual edge must still clear the taker fee (~3.5%+ of stake on crypto)
and the spread before it is money. This tests whether the SIGNAL exists at all. ***
"""

import os
import math
import random
import argparse

import coins
from analysis import panel


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def boot_corr(xs, ys, B=2000, seed=7):
    r = pearson(xs, ys)
    if r is None:
        return None
    rng = random.Random(seed)
    n = len(xs)
    draws = []
    for _ in range(B):
        sx = [0] * n
        ix = [rng.randrange(n) for _ in range(n)]
        rr = pearson([xs[i] for i in ix], [ys[i] for i in ix])
        if rr is not None:
            draws.append(rr)
    draws.sort()
    return (r, draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))])


def brier(preds, outs):
    return sum((p - o) ** 2 for p, o in zip(preds, outs)) / len(preds) if preds else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=float, default=60.0, help="time-left (s) at decision")
    ap.add_argument("--lookbacks", default="30,60,120", help="trend windows in seconds")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--coin", default=coins.default_coin(), choices=list(coins.COINS),
                    help="which coin's data to analyze (default: env ANALYSIS_COIN or btc)")
    args = ap.parse_args()
    lbs = [float(x) for x in args.lookbacks.split(",")]

    conn = panel.connect(coin=args.coin)
    windows = conn.execute(
        "SELECT window_start, resolved_outcome, strike_binance FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL "
        "ORDER BY window_start").fetchall()

    # per window: market price + outcome + trend over each lookback, at the horizon
    rows = []   # (outcome, market, {lb: trend_return})
    for ws, outcome, K in windows:
        snaps = conn.execute(
            "SELECT time_left, price_binance, up_mid FROM snapshots WHERE window_start=? "
            "AND price_binance IS NOT NULL AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        if len(snaps) < 20:
            continue
        tl = [s[0] for s in snaps]; btc = [s[1] for s in snaps]; mid = [s[2] for s in snaps]

        def at(target_tl):
            j = min(range(len(tl)), key=lambda i: abs(tl[i] - target_tl))
            return j

        di = at(args.horizon)
        if abs(tl[di] - args.horizon) > 20:    # need a snapshot near the horizon
            continue
        S = btc[di]; market = mid[di]
        trends = {}
        ok = True
        for lb in lbs:
            pj = at(args.horizon + lb)          # snapshot ~lb seconds earlier
            if abs(tl[pj] - (args.horizon + lb)) > max(10, 0.25 * lb):
                ok = False; break
            trends[lb] = S - btc[pj]            # BTC $ change over the last lb seconds
        if not ok:
            continue
        rows.append((1 if outcome == "Up" else 0, market, trends))

    n = len(rows)
    print(f"TREND -> OUTCOME vs PRICE   |  horizon {args.horizon:g}s left  |  {n} windows  "
          f"|  boot={args.boot}")
    if n < 40:
        print("  too few windows; widen BTC_ANALYSIS_DAYS or loosen horizon."); return
    outs = [r[0] for r in rows]
    mkts = [r[1] for r in rows]
    base = sum(outs) / n
    print(f"  base P(Up)={base:.3f}   Brier(market)={brier(mkts,outs):.4f}   "
          f"Brier(base)={brier([base]*n,outs):.4f}")
    resid = [o - m for o, m in zip(outs, mkts)]

    print(f"\n  {'lookback':>9} | {'corr(trend,OUTCOME)':>26} | {'corr(trend,RESIDUAL=out-mkt)':>30}")
    print(f"  {'(s)':>9} | {'r [95% CI]  (predicts?)':>26} | {'r [95% CI]  (* = beats price)':>30}")
    for lb in lbs:
        tr = [r[2][lb] for r in rows]
        co = boot_corr(tr, outs, args.boot, 11)
        cr = boot_corr(tr, resid, args.boot, 22)
        def fmt(c, star=False):
            if not c:
                return "n/a"
            s = "*" if (star and (c[1] > 0 or c[2] < 0)) else " "
            return f"{c[0]:+.3f} [{c[1]:+.3f},{c[2]:+.3f}]{s}"
        print(f"  {lb:>9g} | {fmt(co):>26} | {fmt(cr, True):>30}")

    # bucket the residual by the (first) lookback's trend, like fair_vs_market
    lb0 = lbs[0]
    trv = sorted(r[2][lb0] for r in rows)
    qs = [trv[int(q * (n - 1))] for q in (0.2, 0.4, 0.6, 0.8)]
    edges = [-1e9] + qs + [1e9]
    print(f"\n  residual by trend quintile (lookback {lb0:g}s):  "
          f"resid CI excluding 0 => trend beats the price")
    print(f"    {'trend $range':>20} {'n':>4} {'mkt_p':>6} {'realized':>9} {'resid':>8} "
          f"{'95% CI':>20}")
    for lo, hi in zip(edges[:-1], edges[1:]):
        sub = [(o, m) for o, m, t in ((r[0], r[1], r[2][lb0]) for r in rows) if lo <= t < hi]
        k = len(sub)
        if k < 5:
            continue
        mp = sum(m for _, m in sub) / k
        rp = sum(o for o, _ in sub) / k
        rs = [o - m for o, m in sub]
        # mean residual bootstrap CI
        rng = random.Random(33)
        md = []
        for _ in range(args.boot):
            md.append(sum(rs[rng.randrange(k)] for _ in range(k)) / k)
        md.sort()
        lo_ci, hi_ci = md[int(0.025 * len(md))], md[int(0.975 * len(md))]
        star = "*" if (lo_ci > 0 or hi_ci < 0) else " "
        loS = "-inf" if lo < -1e8 else f"{lo:+.1f}"
        hiS = "+inf" if hi > 1e8 else f"{hi:+.1f}"
        print(f"    [{loS:>7},{hiS:>7}) {k:>4} {mp:>6.2f} {rp:>9.2f} {rp-mp:>+8.3f} "
              f"[{lo_ci:+.3f},{hi_ci:+.3f}]{star}")

    print("\n  READ: corr(trend,OUTCOME) will likely be POSITIVE (trend does predict the")
    print("  outcome). The one that matters is corr(trend,RESIDUAL): if its CI includes 0")
    print("  (no *), the market PRICE already prices the trend -> no edge, no matter how")
    print("  well trend predicts the outcome. A * (CI excludes 0) is the first sign of a")
    print("  real probability edge -- which would then still have to clear fee + spread.")


if __name__ == "__main__":
    main()

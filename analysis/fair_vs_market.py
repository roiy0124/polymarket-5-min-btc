"""Does the BTC-implied fair value beat the token price? (the underreaction edge)

Your point: price alone isn't the state -- the SAME price means different things
at different time-left and BTC-distance-to-strike. So we use the fundamental state
(time-left T, BTC gap S-K, vol sigma) -> fair P(Up) = Phi((S-K)/(sigma*sqrt(T))),
and ask the only question that yields a tradeable edge:

  When the BTC-implied fair value DISAGREES with the token price, which one does
  the outcome actually follow?

  * If the outcome follows the TOKEN price -> market is efficient, no edge.
  * If the outcome follows the FAIR value -> the token price is LAGGING (under-
    reaction), and the gap (fair - market) is your margin. You trade toward fair.

Rigor (same as calibration_test): one observation per window (independence),
buckets by the signal (fair - market), realized win-rate per bucket, residual
(outcome - market_price) with bootstrap CIs, and a Brier head-to-head. Honest
caveats: sigma is a noisy causal estimate from a Binance proxy (not the Chainlink
settlement); small sample; fills/fees not modeled.

    python -m analysis.fair_vs_market [--horizon 240]
"""

import math
import argparse

from . import panel
from .fairvalue import fair_up
from .calibration_test import bootstrap_ci

SIGNAL_BINS = [(-1.0, -0.10), (-0.10, -0.03), (-0.03, 0.03), (0.03, 0.10), (0.10, 1.0)]


def brier(preds, outs):
    return sum((p - o) ** 2 for p, o in zip(preds, outs)) / len(preds) if preds else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=float, default=240.0)
    args = ap.parse_args()
    conn = panel.connect()

    rows = []  # (market_p, fair_p, outcome)
    for r in panel.build_panel(conn, horizon_s=args.horizon):
        fp = fair_up(conn, r["window_start"], args.horizon)
        if fp is None:
            continue
        rows.append((r["pred_up"], fp, r["outcome"]))
    conn.close()

    n = len(rows)
    print(f"Fair-vs-market underreaction test  |  {n} windows  |  horizon ~{args.horizon:.0f}s")
    if n < 20:
        print("  too few windows with a strike+BTC path yet — keep collecting.")
        return

    market = [m for m, _, _ in rows]
    fair = [f for _, f, _ in rows]
    outs = [o for _, _, o in rows]
    base = sum(outs) / n
    print(f"  base P(Up)={base:.3f}   Brier(market)={brier(market,outs):.4f}   "
          f"Brier(fair)={brier(fair,outs):.4f}   "
          f"Brier(blend)={brier([(m+f)/2 for m,f in zip(market,fair)],outs):.4f}")
    better = "FAIR (market lags -> edge!)" if brier(fair, outs) < brier(market, outs) \
             else "MARKET (no clear lag)"
    print(f"  better predictor: {better}")

    # correlation between signal (fair-market) and residual (outcome-market)
    sig = [f - m for m, f, _ in rows]
    res = [o - m for m, _, o in rows]
    ms, mr = sum(sig) / n, sum(res) / n
    cov = sum((s - ms) * (r - mr) for s, r in zip(sig, res)) / n
    sds = math.sqrt(sum((s - ms) ** 2 for s in sig) / n)
    sdr = math.sqrt(sum((r - mr) ** 2 for r in res) / n)
    corr = cov / (sds * sdr) if sds > 0 and sdr > 0 else 0.0
    print(f"\n  corr(signal=fair-market, residual=outcome-market) = {corr:+.3f}  "
          f"(>0 => market underreacts, edge toward fair)")

    print(f"\n  Bucketed by signal (fair - market):")
    print(f"  {'signal bin':>13} {'n':>4} {'mkt_p':>6} {'fair_p':>7} {'realized':>9} "
          f"{'resid':>7} {'resid 95% CI':>18}")
    for (lo, hi) in SIGNAL_BINS:
        sub = [(m, f, o) for (m, f, o) in rows if lo <= (f - m) < hi]
        k = len(sub)
        if k == 0:
            continue
        mkt = sum(m for m, _, _ in sub) / k
        frp = sum(f for _, f, _ in sub) / k
        real = sum(o for _, _, o in sub) / k
        resid = real - mkt
        ci = bootstrap_ci([o - m for m, _, o in sub], lambda s: sum(s) / len(s))
        excl = "*" if (ci[0] is not None and (ci[0] > 0 or ci[1] < 0)) else " "
        cis = f"[{ci[0]:+.3f},{ci[1]:+.3f}]" if ci[0] is not None else "n/a"
        print(f"  [{lo:+.2f},{hi:+.2f}) {k:>4} {mkt:>6.2f} {frp:>7.2f} {real:>9.2f} "
              f"{resid:>+7.3f} {cis:>17}{excl}")

    print("\n  HOW TO READ: in a bucket where fair >> market (signal>0), if 'realized'")
    print("  tracks fair_p (resid CI excludes 0 and is positive), the market is")
    print("  underreacting and you'd buy -- that's the edge. If resid CIs include 0,")
    print("  the token price already had it right: no edge. Then: fills + fees + more data.")


if __name__ == "__main__":
    main()

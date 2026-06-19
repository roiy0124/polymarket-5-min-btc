"""Calibration study — is the market's Up price calibrated to realized outcomes?

The FIRST analysis to run (needs no fill model). If the market is well-calibrated,
the Up mid-price equals the realized Up frequency in each bin and there is no
fundamental edge from price alone. Systematic deviations (e.g. longshots at 0.2
winning more/less than 20% of the time) are where mispricing lives.

    python -m analysis.calibrate [horizon_seconds]

Stdlib only. As the dataset grows this becomes meaningful; with few settled
windows it is just a sanity check. Remember (DATA-ANALYSIS-TOOLKIT.md): you need
many windows and out-of-sample discipline before trusting any pattern here.
"""

import sys

from . import panel


def reliability(preds, outcomes, nbins=10):
    bins = [[] for _ in range(nbins)]
    for p, o in zip(preds, outcomes):
        idx = min(nbins - 1, max(0, int(p * nbins)))
        bins[idx].append((p, o))
    table = []
    for i, b in enumerate(bins):
        lo, hi = i / nbins, (i + 1) / nbins
        if not b:
            table.append((lo, hi, 0, None, None))
        else:
            n = len(b)
            mean_pred = sum(p for p, _ in b) / n
            freq = sum(o for _, o in b) / n
            table.append((lo, hi, n, mean_pred, freq))
    return table


def brier(preds, outcomes):
    if not preds:
        return None
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def log_loss(preds, outcomes, eps=1e-12):
    if not preds:
        return None
    import math
    s = 0.0
    for p, o in zip(preds, outcomes):
        p = min(1 - eps, max(eps, p))
        s += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return s / len(preds)


def main():
    horizon = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    conn = panel.connect()
    rows = panel.build_panel(conn, horizon_s=horizon)
    conn.close()
    n = len(rows)
    print(f"Calibration of Up mid-price @ ~{horizon:.0f}s time-left   (settled windows: {n})")
    if n == 0:
        print("  no settled windows yet — let the collectors run and retry.")
        return
    preds = [r["pred_up"] for r in rows]
    outs = [r["outcome"] for r in rows]
    base = sum(outs) / n
    print(f"  base rate P(Up) = {base:.3f}   Brier = {brier(preds, outs):.4f}   "
          f"LogLoss = {log_loss(preds, outs):.4f}")
    print(f"  {'bin':>11} {'n':>4} {'mean_pred':>10} {'realized_Up':>12}  reliability")
    for lo, hi, cnt, mp, freq in reliability(preds, outs):
        if cnt == 0:
            continue
        gap = freq - mp
        flag = "well-cal" if abs(gap) < 0.05 else ("Up>price" if gap > 0 else "Up<price")
        print(f"  [{lo:.1f},{hi:.1f}) {cnt:>4} {mp:>10.3f} {freq:>12.3f}  {flag} ({gap:+.3f})")
    print("\n  NOTE: deviations are hypotheses, not edges -- re-validate out-of-sample")
    print("  with many windows and multiple-testing correction (see DATA-ANALYSIS-TOOLKIT.md).")


if __name__ == "__main__":
    main()

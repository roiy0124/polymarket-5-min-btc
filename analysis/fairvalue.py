"""Digital-option fair value — the second strategy, and a head-to-head vs market.

Prices each window as a binary option (ANALYSIS.md sec.1): over a short horizon
with ~zero drift, P(Up) = Phi( (S - K) / (sigma * sqrt(T)) ), where S = current BTC,
K = strike (price at window start), T = time left, sigma = short-horizon BTC vol
estimated causally from the window's own 1-second BTC path up to that instant.

Then compares, on settled windows:
  * Brier(fair P(Up))   vs   Brier(market Up mid-price)   vs   Brier(base rate)
to see whether the model's probability or the market's price predicts the realized
outcome better — i.e. whether a fair-value edge plausibly exists.

    python -m analysis.fairvalue [horizon_seconds]

Stdlib only. Small-sample caveats from DATA-ANALYSIS-TOOLKIT.md apply.
"""

import sys
import math

from . import panel


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_up(conn, ws, horizon_s):
    """Causal fair P(Up) for one window at ~horizon_s time-left, or None."""
    snaps = conn.execute(
        "SELECT ts, time_left, price_binance FROM snapshots WHERE window_start=? AND "
        "price_binance IS NOT NULL ORDER BY ts", (ws,)).fetchall()
    strike = conn.execute(
        "SELECT strike_binance FROM windows WHERE window_start=?", (ws,)).fetchone()
    if not snaps or not strike or strike[0] is None:
        return None
    K = strike[0]
    # find the snapshot closest to the horizon
    idx = min(range(len(snaps)), key=lambda i: abs(snaps[i][1] - horizon_s))
    S = snaps[idx][2]
    T = max(1.0, snaps[idx][1])
    # causal per-second vol from BTC diffs up to the horizon snapshot
    prices = [r[2] for r in snaps[:idx + 1]]
    diffs = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    if len(diffs) < 5:
        return None
    mean_d = sum(diffs) / len(diffs)
    var = sum((d - mean_d) ** 2 for d in diffs) / (len(diffs) - 1)
    sigma_step = math.sqrt(var)
    if sigma_step <= 1e-9:
        return None
    move_std = sigma_step * math.sqrt(T)     # ~1s steps -> sqrt(T) seconds
    return phi((S - K) / move_std)


def brier(preds, outs):
    return sum((p - o) ** 2 for p, o in zip(preds, outs)) / len(preds) if preds else None


def main():
    horizon = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    conn = panel.connect()
    rows = panel.build_panel(conn, horizon_s=horizon)   # gives market pred_up + outcome
    fair, market, outs = [], [], []
    for r in rows:
        fv = fair_up(conn, r["window_start"], horizon)
        if fv is None:
            continue
        fair.append(fv)
        market.append(r["pred_up"])
        outs.append(r["outcome"])
    conn.close()

    n = len(outs)
    print(f"Fair-value vs market  @ ~{horizon:.0f}s time-left   (usable windows: {n})")
    if n == 0:
        print("  not enough windows with a strike + BTC path yet — let it run.")
        return
    base = sum(outs) / n
    base_pred = [base] * n
    print(f"  base rate P(Up) = {base:.3f}")
    print(f"  Brier(market price) = {brier(market, outs):.4f}")
    print(f"  Brier(fair value)   = {brier(fair, outs):.4f}")
    print(f"  Brier(base rate)    = {brier(base_pred, outs):.4f}   (skill floor)")
    # average disagreement = candidate edge magnitude
    avg_dev = sum(abs(m - f) for m, f in zip(market, fair)) / n
    print(f"  mean |market - fair| = {avg_dev:.3f}  (bigger => more candidate mispricing)")
    better = "fair value" if brier(fair, outs) < brier(market, outs) else "market price"
    print(f"  lower Brier (better predictor): {better}")
    print("\n  CAVEAT: tiny sample; sigma from a noisy proxy (Binance, not Chainlink).")
    print("  A real edge needs many windows + walk-forward + cost-aware backtest.")


if __name__ == "__main__":
    main()

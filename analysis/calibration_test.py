"""Rigorous calibration test — is a token's price a fair probability, or are cheap
tokens underpriced? Built to AVOID the ways this analysis usually lies to you.

Pre-registered hypothesis (stated before fitting):
  H0 (efficient): for tokens observed at price p, the realized win-rate == p.
  H1 (longshot underpricing): cheap tokens (low p) win MORE often than p.

Method (per DATA-ANALYSIS-TOOLKIT.md):
  * ONE observation per window (5-min markets are ~independent). Pooling the
    1/sec snapshots would manufacture significance via autocorrelation -> we do
    NOT do that.
  * Two clean views: (A) the Up token every window (unbiased), and (B) the
    cheaper of the two tokens each window (the strategy-relevant longshot).
  * Wilson score CIs + EXACT two-sided binomial tests vs the null win-rate = mean
    price in each bin.
  * Benjamini-Hochberg FDR across bins (we test several bins -> control false
    discoveries).
  * Bootstrap CI (resample windows) on the pooled edge = mean(win - price).
  * Walk-forward (first half -> second half) and horizon sensitivity.

IMPORTANT SCOPE: this tests CALIBRATION (does holding-to-resolution have edge?).
It does NOT prove a tradeable profit: actually buying at p needs a fill, and
resting bids fill adversely (you get filled as it heads to 0). Treat a positive
result as "worth a fill-aware backtest", not "free money".

    python -m analysis.calibration_test [--horizon 240]
"""

import math
import random
import argparse

from . import panel

Z = 1.959963985            # 95%
BINS = [(0.0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.50)]
HORIZONS = [180.0, 240.0, 270.0]
SEED = 20260619


# ---- stats (stdlib) ---------------------------------------------------------

def wilson(k, n):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def binom_pmf(k, n, p):
    if p <= 0:
        return 1.0 if k == 0 else 0.0
    if p >= 1:
        return 1.0 if k == n else 0.0
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def binom_test_two_sided(k, n, p):
    """Exact two-sided binomial p-value (sum of outcomes no more likely than k)."""
    if n == 0:
        return 1.0
    pk = binom_pmf(k, n, p)
    tol = pk * (1 + 1e-9)
    return sum(binom_pmf(i, n, p) for i in range(n + 1) if binom_pmf(i, n, p) <= tol)


def bh_significant(pvals, q=0.10):
    """Benjamini-Hochberg: return set of indices significant at FDR q."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    sig = set()
    kmax = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= q * rank / m:
            kmax = rank
    for rank, i in enumerate(order, start=1):
        if rank <= kmax:
            sig.add(i)
    return sig


def bootstrap_ci(data, statfn, B=5000, alpha=0.05):
    rng = random.Random(SEED)
    n = len(data)
    if n == 0:
        return (None, None)
    stats = []
    for _ in range(B):
        sample = [data[rng.randrange(n)] for _ in range(n)]
        stats.append(statfn(sample))
    stats.sort()
    return (stats[int(alpha / 2 * B)], stats[int((1 - alpha / 2) * B)])


# ---- data -------------------------------------------------------------------

def load(conn, horizon):
    """One row per settled window: (up_price, up_won, cheap_price, cheap_won, ws)."""
    rows = []
    for ws, outcome in conn.execute(
            "SELECT window_start, resolved_outcome FROM windows "
            "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start"):
        snap = conn.execute(
            "SELECT up_mid, down_mid FROM snapshots WHERE window_start=? AND "
            "up_mid IS NOT NULL AND down_mid IS NOT NULL ORDER BY ABS(time_left-?) "
            "LIMIT 1", (ws, horizon)).fetchone()
        if not snap:
            continue
        up_p, dn_p = snap
        up_won = 1 if outcome == "Up" else 0
        if up_p <= dn_p:
            cheap_p, cheap_won = up_p, up_won
        else:
            cheap_p, cheap_won = dn_p, (1 - up_won)
        rows.append((up_p, up_won, cheap_p, cheap_won, ws))
    return rows


def bin_table(price_won):
    """price_won: list of (price, won). Print per-bin calibration with CIs + BH."""
    cells, pvals = [], []
    for (lo, hi) in BINS:
        sub = [(p, w) for (p, w) in price_won if lo <= p < hi]
        n = len(sub)
        if n == 0:
            cells.append((lo, hi, 0, None, None, None, None))
            pvals.append(1.0)
            continue
        mp = sum(p for p, _ in sub) / n
        k = sum(w for _, w in sub)
        wr = k / n
        ci = wilson(k, n)
        pv = binom_test_two_sided(k, n, mp)
        cells.append((lo, hi, n, mp, wr, ci, pv))
        pvals.append(pv)
    sig = bh_significant(pvals, q=0.10)
    print(f"  {'price bin':>11} {'n':>4} {'mean_p':>7} {'win%':>6} "
          f"{'win 95% CI':>15} {'edge':>7} {'p':>6} {'sig':>4}")
    for i, (lo, hi, n, mp, wr, ci, pv) in enumerate(cells):
        if n == 0:
            continue
        edge = wr - mp
        cis = f"[{ci[0]:.2f},{ci[1]:.2f}]"
        flag = "FDR*" if i in sig else ""
        print(f"  [{lo:.2f},{hi:.2f}) {n:>4} {mp:>7.3f} {wr*100:>5.0f}% "
              f"{cis:>15} {edge:>+7.3f} {pv:>6.3f} {flag:>4}")


def pooled_edge(rows, which, pmax):
    """Bootstrap CI on mean(won - price) for tokens with price < pmax."""
    if which == "up":
        data = [(p, w) for (p, w, _, _, _) in rows if p < pmax]
    else:
        data = [(cp, cw) for (_, _, cp, cw, _) in rows if cp < pmax]
    if not data:
        return None, None, 0
    mean_edge = sum(w - p for p, w in data) / len(data)
    lo, hi = bootstrap_ci(data, lambda s: sum(w - p for p, w in s) / len(s))
    return mean_edge, (lo, hi), len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=float, default=240.0)
    args = ap.parse_args()
    conn = panel.connect()
    rows = load(conn, args.horizon)
    n = len(rows)
    print(f"Calibration test  |  {n} independent windows  |  horizon ~{args.horizon:.0f}s "
          f"time-left  |  null: win-rate == price")
    if n < 20:
        print("  too few windows for a meaningful test yet — keep collecting.")
        conn.close()
        return

    print(f"\n(A) UP token (unbiased) -- Brier {sum((p-w)**2 for p,w,_,_,_ in rows)/n:.4f}")
    bin_table([(p, w) for (p, w, _, _, _) in rows])

    print(f"\n(B) CHEAPER token each window (the longshot strategy view)")
    bin_table([(cp, cw) for (_, _, cp, cw, _) in rows])

    print("\n  Pooled edge = mean(win - price), bootstrap 95% CI (resampled windows):")
    for which in ("up", "cheap"):
        e, ci, m = pooled_edge(rows, which, pmax=0.30)
        if e is None:
            print(f"    {which:>5} (price<0.30): no obs")
            continue
        excl = "" if (ci[0] is None) else (" *EXCLUDES 0*" if ci[0] > 0 or ci[1] < 0 else " (includes 0)")
        print(f"    {which:>5} (price<0.30, n={m}): edge {e:+.3f}  CI [{ci[0]:+.3f},{ci[1]:+.3f}]{excl}")

    # walk-forward
    ws_sorted = sorted(r[4] for r in rows)
    cut = ws_sorted[len(ws_sorted) // 2]
    first = [r for r in rows if r[4] < cut]
    second = [r for r in rows if r[4] >= cut]
    print("\n  Walk-forward (cheaper token, price<0.30, mean edge):")
    for name, part in (("first half", first), ("second half", second)):
        e, ci, m = pooled_edge(part, "cheap", 0.30)
        if e is None:
            print(f"    {name}: no obs")
        else:
            print(f"    {name:>11} (n={m}): edge {e:+.3f}  CI [{ci[0]:+.3f},{ci[1]:+.3f}]")

    print("\n  Horizon sensitivity (cheaper token, price<0.30 pooled edge):")
    for h in HORIZONS:
        r2 = load(conn, h)
        e, ci, m = pooled_edge(r2, "cheap", 0.30)
        if e is not None:
            print(f"    t-left ~{h:>4.0f}s (n={m}): edge {e:+.3f}  CI [{ci[0]:+.3f},{ci[1]:+.3f}]")

    print("\n  READ HONESTLY: a positive edge whose CI excludes 0 AND replicates across")
    print("  halves/horizons is a real CALIBRATION edge -> then run the fill-aware backtest")
    print("  (adverse selection + fees will shrink it). A CI that includes 0 = not proven.")
    conn.close()


if __name__ == "__main__":
    main()

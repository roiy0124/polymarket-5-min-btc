"""B1 — does a cross-asset SMT gap exist & carry information? (simplest existence test)

Idea B (IDEAS.md): scan all coins, and when one coin's move DIVERGES from its peers (crypto is
correlated), the laggard should converge — an SMT gap. This is the SIMPLEST check, with the
fewest moving parts: NO spread, NO fee, NO fill model, NO market quotes yet. Just two questions
on the underlying (Binance) price series:

  1. SMT PREREQUISITE — do the coins actually move together? (pairwise correlation of bar
     %-returns; high off-diagonal => divergences are meaningful). Plus a quick lead-lag peek.
  2. CONVERGENCE — define each coin's GAP at time t = (peer-consensus recent %move) - (that
     coin's own recent %move). Does the gap predict the coin's FORWARD %return (does the
     laggard catch up)?  corr(gap, forward_return) > 0  =>  a real SMT margin exists.

If (1) is high AND (2) is positive (CI excludes 0) -> the gap exists and is informative -> proceed
to B's later layers (is it unpriced? is it tradeable net of spread+fee?). If (2) ~0 -> coins
don't converge informatively -> stop. 24h of data is enough for first conclusions.

Uses the per-coin snapshots' underlying price (data/<coin>/live.db), aligned to a common
second-grid. Stdlib only.

    python experiment_xasset_smt.py
    python experiment_xasset_smt.py --bar 5 --lookback 6 --forward 6 --hours 36

*** First-pass caveat: bar-return samples are autocorrelated, so the bootstrap CI understates
uncertainty — treat a marginal result as suggestive, not proven. This tests EXISTENCE of the
gap, not tradeable profit (that's B2, net of spread+fee). ***
"""

import os
import sys
import math
import time
import random
import argparse
import sqlite3

try:                                  # the user's console is cp1255; don't die on stray chars
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import coins


def load_price_per_sec(coin, cutoff_ts):
    """{int_second: last underlying price that second} from the coin's snapshots."""
    db = coins.live_db(coin)
    if not os.path.exists(db):
        return {}
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    rows = conn.execute(
        "SELECT ts, price_binance FROM snapshots WHERE ts>=? AND price_binance IS NOT NULL "
        "ORDER BY ts", (cutoff_ts,)).fetchall()
    conn.close()
    out = {}
    for ts, px in rows:
        out[int(ts)] = px      # last price in that second
    return out


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bar", type=int, default=5, help="bar size in seconds for returns")
    ap.add_argument("--lookback", type=int, default=6, help="bars for the gap window (xbar s)")
    ap.add_argument("--forward", type=int, default=6, help="bars for the forward return")
    ap.add_argument("--hours", type=float, default=36.0, help="how far back to load")
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()

    now = int(time.time())
    cutoff = now - args.hours * 3600
    cl = list(coins.ENABLED)

    # 1) per-coin price on a common bar grid
    persec = {c: load_price_per_sec(c, cutoff) for c in cl}
    for c in cl:
        print(f"  {c}: {len(persec[c])} sec-samples")
    # common seconds (intersection), bucketed to bars
    common = set(persec[cl[0]])
    for c in cl[1:]:
        common &= set(persec[c])
    if len(common) < 200:
        print(f"\nonly {len(common)} overlapping seconds across all coins — need more "
              f"multi-coin data; try --hours larger or wait.")
        return
    secs = sorted(common)
    t0, t1 = secs[0], secs[-1]
    print(f"\noverlap: {len(secs)} sec across all {len(cl)} coins "
          f"(~{(t1 - t0) / 3600:.1f}h, {time.strftime('%m-%d %H:%M', time.gmtime(t0))}->"
          f"{time.strftime('%H:%M', time.gmtime(t1))} UTC)")

    # bar grid: sample price at each bar boundary, log-returns
    barlen = args.bar
    grid = list(range(t0, t1 + 1, barlen))
    # nearest available second <= g (forward-fill within the common set)
    cs = secs
    import bisect
    def price_at(coin, g):
        i = bisect.bisect_right(cs, g) - 1
        return persec[coin][cs[i]] if i >= 0 else None
    rets = {c: [] for c in cl}          # aligned bar log-returns
    gridkeep = []
    for k in range(1, len(grid)):
        ok = True
        row = {}
        for c in cl:
            p0 = price_at(c, grid[k - 1]); p1 = price_at(c, grid[k])
            if not p0 or not p1 or p0 <= 0 or p1 <= 0:
                ok = False; break
            row[c] = math.log(p1 / p0)
        if ok:
            for c in cl:
                rets[c].append(row[c])
            gridkeep.append(grid[k])
    nb = len(gridkeep)
    print(f"bars: {nb} x {barlen}s\n")

    # ---- Part 1: do they move together? pairwise correlation ----
    print("(1) SMT prerequisite — pairwise correlation of "
          f"{barlen}s %-returns (do they move together?)")
    hdr = "        " + " ".join(f"{c:>6}" for c in cl)
    print(hdr)
    corrs = []
    for a in cl:
        cells = []
        for b in cl:
            r = pearson(rets[a], rets[b])
            cells.append(f"{r:>6.2f}" if r is not None else "   n/a")
            if a < b and r is not None:
                corrs.append(r)
        print(f"  {a:>5} " + " ".join(cells))
    if corrs:
        print(f"  mean off-diagonal corr = {sum(corrs) / len(corrs):+.2f}  "
              f"(higher => divergences are meaningful)")

    # ---- Part 2: do divergence gaps converge? ----
    L, F = args.lookback, args.forward
    samples = []   # (gap, forward_return)
    for c in cl:
        r = rets[c]
        peers = [p for p in cl if p != c]
        for k in range(L, nb - F):
            own_back = sum(r[k - L:k])
            peer_back = sum(sum(rets[p][k - L:k]) for p in peers) / len(peers)
            gap = peer_back - own_back            # >0: peers rose more than c (c lagged up)
            fwd = sum(r[k:k + F])                 # c's next F bars
            samples.append((gap, fwd))
    gaps = [s[0] for s in samples]; fwds = [s[1] for s in samples]
    rc = pearson(gaps, fwds)
    # block bootstrap CI (blocks to respect autocorrelation)
    ci = None
    if rc is not None and len(samples) > 100:
        rng = random.Random(12345)
        blk = max(1, (nb - L - F))   # per-coin contiguous length ~ one block
        # simpler: resample contiguous index blocks of length ~F across the flat sample list
        bl = max(10, F * 3)
        nblocks = len(samples) // bl
        draws = []
        idxblocks = [samples[i * bl:(i + 1) * bl] for i in range(nblocks)]
        for _ in range(args.boot):
            pool = []
            for _ in range(nblocks):
                pool.extend(idxblocks[rng.randrange(nblocks)])
            rr = pearson([p[0] for p in pool], [p[1] for p in pool])
            if rr is not None:
                draws.append(rr)
        if draws:
            draws.sort()
            ci = (draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))])

    print(f"\n(2) CONVERGENCE — gap = peers' last {L * barlen}s %move - own; "
          f"forward = next {F * barlen}s %move")
    star = ""
    if ci:
        star = " *" if (ci[0] > 0 or ci[1] < 0) else ""
    cis = f"  95% CI [{ci[0]:+.3f},{ci[1]:+.3f}]{star}" if ci else ""
    print(f"  corr(gap, forward_return) = {rc:+.3f}   (n={len(samples)}){cis}")
    print(f"  >0 => laggards CATCH UP toward peers (SMT margin exists).  "
          f"~0 => no convergence edge.")

    print("\n  READ: high Part-1 corr + a clearly-positive Part-2 (CI excludes 0) => the SMT")
    print("  gap EXISTS and is informative -> next: is it unpriced (gap vs the QUOTE) and")
    print("  tradeable net of spread+fee (B2). If Part-2 ~0 => no convergence edge, stop.")
    print("  CAVEAT: bar samples autocorrelate -> block-bootstrap CI still understates noise;")
    print("  treat marginal results as suggestive. This is EXISTENCE, not tradeable profit.")


if __name__ == "__main__":
    main()

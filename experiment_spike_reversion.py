"""BTC instant-spike mean-reversion study (side experiment, not in the menu).

Hypothesis (from the round charts): when BTC makes a big move in a split second, it
often snaps back -- i.e. fast spikes are transient (panic/forced flow) more than
trend. If true, a token repricing on such a spike is a FAKE gap signal we should
fade / not chase; a spike that does NOT revert is a real trend.

Method: build the global BTC price series (1/sec snapshots, continuous across
windows). For each fast move >= --spike-usd over <= --window-s seconds, measure how
much of it is GIVEN BACK over the next --revert-s seconds:
    retrace = (price_peak - price_after) / (price_peak - price_before)
    retrace = 1.0 -> fully reverted to pre-spike;  <=0 -> kept going (trend).
Report the reversion distribution overall and by spike magnitude, vs a small-move
baseline. Greedy non-overlapping spikes to avoid double counting.

    python experiment_spike_reversion.py [--spike-usd 15 --window-s 10 --revert-s 30]

PILOT on ~3 days; exploratory. Uses 1/sec snapshots -- for sub-second spikes switch
the source to btc_ticks later.
"""

import os
import bisect
import argparse
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiment_walkforward import open_merged


def nearest(ts, target, tol):
    """Index of the ts entry closest to `target`, within `tol` seconds, else None."""
    i = bisect.bisect_left(ts, target)
    best, bestd = None, tol
    for j in (i - 1, i):
        if 0 <= j < len(ts):
            d = abs(ts[j] - target)
            if d <= bestd:
                best, bestd = j, d
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spike-usd", type=float, default=15.0, dest="spike_usd")
    ap.add_argument("--window-s", type=float, default=10.0, dest="window_s",
                    help="a 'fast' move = this size within this many seconds")
    ap.add_argument("--revert-s", type=float, default=30.0, dest="revert_s",
                    help="reversion horizon measured after the spike")
    args = ap.parse_args()

    conn, dbs = open_merged()
    rows = conn.execute("SELECT ts, btc_binance FROM snapshots WHERE btc_binance "
                        "IS NOT NULL ORDER BY ts").fetchall()
    conn.close()
    ts = [r[0] for r in rows]
    px = [r[1] for r in rows]
    n = len(ts)
    print(f"data: {len(dbs)} db(s), {n} BTC samples spanning {(ts[-1]-ts[0])/3600:.1f}h")
    print(f"spike = |move| >= ${args.spike_usd:g} within {args.window_s:g}s; "
          f"retrace measured over the next {args.revert_s:g}s\n")

    spikes, baseline = [], []      # retrace fractions
    i = 0
    while i < n:
        lb = nearest(ts, ts[i] - args.window_s, 5)
        fw = nearest(ts, ts[i] + args.revert_s, 10)
        if lb is None or fw is None:
            i += 1
            continue
        # verify the actual spans are close to the intended windows (skip data gaps)
        if not (args.window_s * 0.4 <= ts[i] - ts[lb] <= args.window_s * 1.6):
            i += 1
            continue
        if not (args.revert_s * 0.4 <= ts[fw] - ts[i] <= args.revert_s * 1.6):
            i += 1
            continue
        move = px[i] - px[lb]
        if abs(move) < 1e-9:
            i += 1
            continue
        retrace = (px[i] - px[fw]) / move
        if abs(move) >= args.spike_usd:
            spikes.append((retrace, abs(move)))
            i = fw            # greedy: skip past this spike's window (non-overlapping)
        else:
            if abs(move) >= args.spike_usd * 0.2:   # small but real moves = baseline
                baseline.append(retrace)
            i += 1

    def report(name, fracs):
        if not fracs:
            print(f"  {name}: none")
            return
        rev_half = sum(1 for r in fracs if r >= 0.5) / len(fracs)
        rev_full = sum(1 for r in fracs if r >= 1.0) / len(fracs)
        kept = sum(1 for r in fracs if r <= 0.0) / len(fracs)
        print(f"  {name:>22}: n={len(fracs):>4}  median retrace {statistics.median(fracs):>+5.2f}  "
              f"reverted>=50% {rev_half:>4.0%}  fully {rev_full:>4.0%}  kept-going {kept:>4.0%}")

    sp = [r for r, m in spikes]
    report("FAST SPIKES", sp)
    report("small-move baseline", baseline)
    if spikes:
        # by magnitude bucket
        print("\n  fast spikes by size:")
        for lo, hi, lbl in [(args.spike_usd, args.spike_usd * 2, "1x-2x"),
                            (args.spike_usd * 2, args.spike_usd * 4, "2x-4x"),
                            (args.spike_usd * 4, 1e9, "4x+")]:
            b = [r for r, m in spikes if lo <= m < hi]
            report(f"  {lbl} (${lo:.0f}-{hi if hi<1e8 else '...'})", b)

    # histogram
    if sp:
        fig, ax = plt.subplots(figsize=(6.2, 4.0), dpi=85)
        clipped = [max(-1.0, min(2.0, r)) for r in sp]
        ax.hist(clipped, bins=30, color="#e8833a", alpha=0.85)
        ax.axvline(0.0, color="#888", ls=":", label="0 = kept going (trend)")
        ax.axvline(1.0, color="#2ea043", ls="--", label="1 = fully reverted")
        ax.axvline(statistics.median(sp), color="#8957e5", lw=2, label=f"median {statistics.median(sp):+.2f}")
        ax.set_xlabel("retrace fraction of the spike (clipped to [-1,2])")
        ax.set_ylabel("# spikes")
        ax.set_title(f"BTC fast-spike reversion  (>=${args.spike_usd:g}/{args.window_s:g}s, "
                     f"{args.revert_s:g}s horizon, n={len(sp)})")
        ax.legend(fontsize=8)
        fig.tight_layout()
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike_reversion.png")
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
        print(f"\n  histogram -> {os.path.basename(out)}")
    print("\n  >0.5 reverted = spike tends to be transient (fadeable); <=0 kept going = trend.")


if __name__ == "__main__":
    main()

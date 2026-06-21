"""Nested gap->time strategy, walk-forward OOS (experiment, not in the menu).

The strategy we converged on:
  1. From PAST data, find the favorable gap BUY-zone (best_conditional, Screen B).
  2. FILTER the dots to that gap zone, then fit the TIME-based sell line
     (best_sell_window) on the filtered subset (Screen A on the conditioned data).
  3. Keep it only if that filtered line passes the DYNAMIC guard: its n >=
     FILT_LINE_FRAC * the map's ORIGINAL dot count (else too thin -> no signal).
  4. LIVE: buy entry z only when the window's gap is in the zone AND time is in the
     buy-window; sell at T. Realistic queue-based fills.

Run side-by-side with the BASELINE (plain time line, no gap filter) so we can answer:
does nesting the gap filter actually raise out-of-sample EV, or just cut volume?

    python experiment_nested.py [--filt-frac 0.10 --block-h 6 --warmup-h 24]

*** PILOT -- ~3 days is underpowered; screens are fit optimistically though fills are
realistic. Tests whether the NESTED strat beats the baseline; not a verdict. ***
"""

import os
import math
import argparse

from experiment_combined import load_full, train_dots
from experiment_walkforward import open_merged, replay_leg
from analysis.exit_maps import (best_conditional, best_sell_window,
                                entry_and_exit, entry_margin)
from exec_engine.config import SafetyConfig

WINDOW = 300.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-h", type=float, default=24.0, dest="warmup_h")
    ap.add_argument("--block-h", type=float, default=6.0, dest="block_h")
    ap.add_argument("--entry-lo", type=int, default=20, dest="entry_lo")
    ap.add_argument("--entry-hi", type=int, default=75, dest="entry_hi")
    ap.add_argument("--filt-frac", type=float, default=0.10, dest="filt_frac",
                    help="filtered line must have n >= this * original dots (dynamic guard)")
    ap.add_argument("--usd", type=float, default=2.0)
    args = ap.parse_args()

    conn, dbs = open_merged()
    windows = load_full(conn)
    by_ws = {w["ws"]: w for w in windows}
    all_ws = [w["ws"] for w in windows]
    t_end = all_ws[-1] + WINDOW
    t_start = all_ws[0] + args.warmup_h * 3600
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    cents = list(range(args.entry_lo, args.entry_hi + 1))
    print(f"data: {len(dbs)} db(s), {len(windows)} windows; warmup {args.warmup_h:g}h, "
          f"blocks {args.block_h:g}h, entries {args.entry_lo}-{args.entry_hi}c, "
          f"filt_frac {args.filt_frac}")
    print("*** PILOT -- nested-vs-baseline, not a verdict ***\n")

    base_recs, nest_recs = [], []
    T = t_start
    nsig_base = nsig_nest = 0
    while T < t_end:
        train = [w for w in windows if w["ws"] + WINDOW <= T]
        test = [w for w in windows if T <= w["ws"] < T + args.block_h * 3600
                and w["ws"] + WINDOW <= t_end]
        baseA, nestA = {}, {}
        for side in ("up", "down"):
            for c in cents:
                z = c / 100.0
                d = train_dots(train, side, c)              # [(entry_x, exit_value, gap)]
                if len(d) < 24:
                    continue
                # BASELINE: plain time line on all dots
                bb = best_sell_window([(x, y) for x, y, g in d], z)
                if bb and bb[5] > 0 and bb[2] > z:
                    baseA[(side, c)] = {"entry": z, "sell": bb[2], "t1": bb[0],
                                        "t2": bb[1], "shares": round(args.usd / z, 2)}
                # NESTED: gap zone -> filter -> time line (with dynamic guard)
                mdots = [(g, y, "x") for x, y, g in d if g is not None]
                bc = best_conditional(mdots, z)
                if not bc:
                    continue
                zones = bc[2]
                filt = [(x, y) for x, y, g in d
                        if g is not None and any(lo <= g <= hi for lo, hi in zones)]
                floor = math.ceil(args.filt_frac * len(d))
                bf = best_sell_window(filt, z)
                if bf and bf[5] > 0 and bf[2] > z and bf[6] >= floor:
                    nestA[(side, c)] = {"entry": z, "sell": bf[2], "t1": bf[0],
                                        "t2": bf[1], "shares": round(args.usd / z, 2),
                                        "zones": zones}
        nsig_base += len(baseA)
        nsig_nest += len(nestA)
        # trade the block OOS with realistic fills
        for w in test:
            for side in ("up", "down"):
                token = w["tu"] if side == "up" else w["td"]
                for c in cents:
                    won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
                    sb = baseA.get((side, c))
                    if sb:
                        r = replay_leg(conn, w["ws"], token, side, sb, w["outcome"], scfg)
                        if r:
                            base_recs.append((r[0], r[1], sb["shares"] * sb["entry"]))
                    sn = nestA.get((side, c))
                    if sn:
                        gW = entry_margin(w[side], c)
                        if gW is not None and any(lo <= gW <= hi for lo, hi in sn["zones"]):
                            r = replay_leg(conn, w["ws"], token, side, sn, w["outcome"], scfg)
                            if r:
                                nest_recs.append((r[0], r[1], sn["shares"] * sn["entry"]))
        T += args.block_h * 3600

    def summ(name, rows, nsig):
        fills = [r for r in rows if r[0]]
        n = len(fills)
        if n == 0:
            print(f"  {name:>22}: 0 fills  (armed signals total: {nsig})")
            return
        wins = sum(1 for r in fills if r[1] > 1e-9)
        pnl = sum(r[1] for r in fills)
        stake = sum(r[2] for r in fills)
        print(f"  {name:>22}: fills {n:>4}  win {wins/n:>4.0%}  pnl {pnl:>+8.1f}  "
              f"EV/fill {pnl/stake if stake else 0:>+5.2f}  (armed sigs {nsig})")

    print(f"out-of-sample fills: baseline {sum(1 for r in base_recs if r[0])}, "
          f"nested {sum(1 for r in nest_recs if r[0])}\n")
    summ("BASELINE (time only)", base_recs, nsig_base)
    summ("NESTED (gap->time)", nest_recs, nsig_nest)
    print("\n  Nesting helps only if NESTED EV/fill clearly beats BASELINE (not just")
    print("  fewer trades at the same EV). PILOT: ~3 days, confirm over weeks + net of fees.")
    conn.close()


if __name__ == "__main__":
    main()

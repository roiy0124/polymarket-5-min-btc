"""Nested gap->time strategy, 30-min refit cadence, broken down by TIME-OF-DAY.

Same nested strategy as experiment_nested.py (gap BUY-zone -> filter -> time sell
line with the dynamic guard, traded OOS with realistic fills), but:
  * signals are RE-EVALUATED every 30 minutes of simulated trading (walk-forward
    refit on all past data, trade the next 30 min), and
  * every out-of-sample fill is tagged with its hour-of-day (local/Israel) so we can
    see whether the edge lives in the overnight regime (as the regime analysis hinted)
    rather than averaged across day+night.

Reports NESTED (and BASELINE) overall and by 3-hour time bucket + day vs night.

    python experiment_nested_tod.py [--filt-frac 0.10 --warmup-h 24]

PILOT (~3 days, screens fit optimistically though fills realistic) -- a breakdown to
locate the edge in time, not a verdict.
"""

import os
import math
import time
import argparse
from collections import defaultdict

from experiment_combined import load_full
from experiment_walkforward import open_merged, replay_leg
from analysis.exit_maps import (best_conditional, best_sell_window,
                                entry_and_exit, entry_margin)
from exec_engine.config import SafetyConfig

WINDOW = 300.0
REFRESH = 1800.0   # 30 minutes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-h", type=float, default=24.0, dest="warmup_h")
    ap.add_argument("--entry-lo", type=int, default=20, dest="entry_lo")
    ap.add_argument("--entry-hi", type=int, default=75, dest="entry_hi")
    ap.add_argument("--filt-frac", type=float, default=0.10, dest="filt_frac")
    ap.add_argument("--usd", type=float, default=2.0)
    args = ap.parse_args()

    conn, dbs = open_merged()
    windows = load_full(conn)
    cents = list(range(args.entry_lo, args.entry_hi + 1))

    # precompute per-(side,cent) dot lists (sorted by ws) + per-window dot lookup
    dotmap = {(s, c): [] for s in ("up", "down") for c in cents}
    wdots = defaultdict(dict)          # ws -> {(side,cent): (x,y,gap)}
    winmap = {}
    for w in windows:
        winmap[w["ws"]] = w
        for side in ("up", "down"):
            won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
            for c in cents:
                eb = entry_and_exit(w[side], c, won)
                if eb is None:
                    continue
                x, y = eb
                g = entry_margin(w[side], c)
                dotmap[(side, c)].append((w["ws"], x, y, g))
                wdots[w["ws"]][(side, c)] = (x, y, g)

    all_ws = sorted(winmap)
    t_end = all_ws[-1] + WINDOW
    t_start = all_ws[0] + args.warmup_h * 3600
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    print(f"data: {len(dbs)} db(s), {len(windows)} windows; warmup {args.warmup_h:g}h; "
          f"refit every 30min; entries {args.entry_lo}-{args.entry_hi}c; filt {args.filt_frac}")
    print("*** PILOT -- time-of-day breakdown, not a verdict ***\n")

    base_recs, nest_recs = [], []      # (filled, pnl, stake, hour)
    T = t_start
    while T < t_end:
        baseA, nestA = {}, {}
        for (side, c), lst in dotmap.items():
            train = [(x, y, g) for (ws, x, y, g) in lst if ws + WINDOW <= T]
            if len(train) < 24:
                continue
            z = c / 100.0
            bb = best_sell_window([(x, y) for x, y, g in train], z)
            if bb and bb[5] > 0 and bb[2] > z:
                baseA[(side, c)] = {"entry": z, "sell": bb[2], "t1": bb[0], "t2": bb[1],
                                    "shares": round(args.usd / z, 2)}
            mdots = [(g, y, "x") for x, y, g in train if g is not None]
            bc = best_conditional(mdots, z)
            if not bc:
                continue
            zones = bc[2]
            filt = [(x, y) for x, y, g in train
                    if g is not None and any(lo <= g <= hi for lo, hi in zones)]
            bf = best_sell_window(filt, z)
            if bf and bf[5] > 0 and bf[2] > z and bf[6] >= math.ceil(args.filt_frac * len(train)):
                nestA[(side, c)] = {"entry": z, "sell": bf[2], "t1": bf[0], "t2": bf[1],
                                    "shares": round(args.usd / z, 2), "zones": zones}
        # trade the next 30 min out-of-sample
        for ws in all_ws:
            if not (T <= ws < T + REFRESH and ws + WINDOW <= t_end):
                continue
            w = winmap[ws]
            hour = time.localtime(ws).tm_hour
            for (side, c), (x, y, g) in wdots[ws].items():
                token = w["tu"] if side == "up" else w["td"]
                won_out = w["outcome"]
                sb = baseA.get((side, c))
                if sb:
                    r = replay_leg(conn, ws, token, side, sb, won_out, scfg)
                    if r:
                        base_recs.append((r[0], r[1], sb["shares"] * sb["entry"], hour))
                sn = nestA.get((side, c))
                if sn and g is not None and any(lo <= g <= hi for lo, hi in sn["zones"]):
                    r = replay_leg(conn, ws, token, side, sn, won_out, scfg)
                    if r:
                        nest_recs.append((r[0], r[1], sn["shares"] * sn["entry"], hour))
        T += REFRESH

    def stat(rows):
        fills = [r for r in rows if r[0]]
        n = len(fills)
        if n == 0:
            return None
        wins = sum(1 for r in fills if r[1] > 1e-9)
        pnl = sum(r[1] for r in fills)
        stake = sum(r[2] for r in fills)
        return n, wins / n, pnl, (pnl / stake if stake else 0)

    def show(name, rows):
        s = stat(rows)
        if not s:
            print(f"  {name}: 0 fills"); return
        n, wr, pnl, ev = s
        print(f"  {name:>26}: fills {n:>4}  win {wr:>4.0%}  pnl {pnl:>+8.1f}  EV/fill {ev:>+5.2f}")

    print("=== OVERALL (30-min cadence) ===")
    show("BASELINE (time only)", base_recs)
    show("NESTED (gap->time)", nest_recs)

    for label, rows in [("BASELINE", base_recs), ("NESTED", nest_recs)]:
        print(f"\n=== {label} by 3h time-of-day (IL) ===")
        for b in range(8):
            sub = [r for r in rows if b * 3 <= r[3] < b * 3 + 3]
            show(f"{b*3:02d}:00-{b*3+3:02d}:00", sub)
        night = [r for r in rows if r[3] >= 18 or r[3] < 6]
        day = [r for r in rows if 6 <= r[3] < 18]
        print("  --")
        show("NIGHT (18:00-06:00)", night)
        show("DAY   (06:00-18:00)", day)

    print("\n  PILOT: ~3 days; screens optimistic, fills realistic. Look for whether the")
    print("  NESTED NIGHT slice crosses positive while DAY drags the blend down.")
    conn.close()


if __name__ == "__main__":
    main()

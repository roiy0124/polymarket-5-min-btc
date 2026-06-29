"""Lookback-combo sweep, baseline vs nested, 30-min cadence (experiment, not in menu).

Finds the sweet-spot 3-lookback combination from {24,16,8,6,4}h. A signal is armed
only if its line is ROBUST across all three lookbacks in the combo: fit the line on
the LONGEST lookback (most data), then require that same line to still be EV>0 when
evaluated on the other two (shorter) lookback subsets. Run for BASELINE (plain time
line) and NESTED (gap-zone -> filter -> time line, dynamic guard), entry from 5c,
30-min walk-forward refit, realistic fills.

    python experiment_lookback_sweep.py [--filt-frac 0.10 --warmup-h 24]

*** PILOT / OVERFIT WARNING: picking the best of 10 combos x 2 strategies on ~3 days
is multiple-comparison. Read the FULL ranking -- a real sweet spot is CONSISTENTLY
ahead; if all combos cluster near the same negative number, there is no sweet spot. ***
"""

import os
import math
import time
import bisect
import argparse
import itertools

from experiment_combined import load_full
from experiment_walkforward import open_merged, replay_leg
from analysis.exit_maps import best_conditional, best_sell_window, entry_and_exit, entry_margin
from exec_engine.config import SafetyConfig

WINDOW = 300.0
REFRESH = 1800.0
LOOKBACKS_H = [4, 6, 8, 16, 24]
COMBOS = list(itertools.combinations(LOOKBACKS_H, 3))   # 10 combos


def eval_line(xy, z, t1, t2, T):
    """EV of a FIXED (buy-window, sell T) line on a dot subset. -100% on a miss."""
    sub = [y for x, y in xy if t1 <= x <= t2]
    n = len(sub)
    if n < 5:
        return None
    reach = sum(1 for y in sub if y >= T - 1e-9) / n
    roi = (T - z) / z
    return reach * roi - (1.0 - reach)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-h", type=float, default=24.0, dest="warmup_h")
    ap.add_argument("--entry-lo", type=int, default=5, dest="entry_lo")
    ap.add_argument("--entry-hi", type=int, default=75, dest="entry_hi")
    ap.add_argument("--filt-frac", type=float, default=0.10, dest="filt_frac")
    ap.add_argument("--usd", type=float, default=2.0)
    args = ap.parse_args()

    conn, dbs = open_merged()
    windows = load_full(conn)
    cents = list(range(args.entry_lo, args.entry_hi + 1))
    dotmap, ws_arr, wdots, winmap = {}, {}, {}, {}
    for w in windows:
        winmap[w["ws"]] = w
        wdots[w["ws"]] = {}
        for side in ("up", "down"):
            won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
            for c in cents:
                eb = entry_and_exit(w[side], c, won)
                if eb is None:
                    continue
                x, y = eb
                g = entry_margin(w[side], c)
                dotmap.setdefault((side, c), []).append((w["ws"], x, y, g))
                wdots[w["ws"]][(side, c)] = (x, y, g)
    for k in dotmap:
        ws_arr[k] = [d[0] for d in dotmap[k]]

    all_ws = sorted(winmap)
    t_end = all_ws[-1] + WINDOW
    t_start = all_ws[0] + args.warmup_h * 3600
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    print(f"data: {len(dbs)} db(s), {len(windows)} windows; entries {args.entry_lo}-"
          f"{args.entry_hi}c; 30-min cadence; combos={len(COMBOS)}")
    print("*** OVERFIT WARNING: read the full ranking, not just the top ***\n")

    # results[(strat, combo)] = list of (filled, pnl, stake)
    res = {(s, cb): [] for s in ("base", "nest") for cb in COMBOS}
    replay_memo = {}

    def do_replay(ws, token, side, sig):
        key = (ws, side, sig["entry"], round(sig["sell"], 2), sig["t1"], sig["t2"])
        if key not in replay_memo:
            replay_memo[key] = replay_leg(conn, ws, token, side, sig, winmap[ws]["outcome"], scfg)
        return replay_memo[key]

    T = t_start
    while T < t_end:
        # per slot: fit per-lookback baseline + nested lines on PAST data
        armed = {(s, cb): {} for s in ("base", "nest") for cb in COMBOS}
        for (side, c), lst in dotmap.items():
            ws_a = ws_arr[(side, c)]
            hi = bisect.bisect_right(ws_a, T - WINDOW)        # dots fully closed before T
            if hi < 24:
                continue
            z = c / 100.0
            past = lst[:hi]                                   # (ws,x,y,g) closed before T
            # per-lookback subsets (xy) and gap-filtered xy
            mdots = [(g, y, "x") for (ws, x, y, g) in past if g is not None]
            bc = best_conditional(mdots, z)
            zones = bc[2] if bc else None
            subxy, subxy_f = {}, {}
            for L in LOOKBACKS_H:
                lo = bisect.bisect_left(ws_a, T - L * 3600)
                seg = lst[lo:hi]
                subxy[L] = [(x, y) for (ws, x, y, g) in seg]
                if zones is not None:
                    subxy_f[L] = [(x, y) for (ws, x, y, g) in seg
                                  if g is not None and any(a <= g <= b for a, b in zones)]
            bw = {L: best_sell_window(subxy[L], z) for L in LOOKBACKS_H}
            bwf = {L: best_sell_window(subxy_f[L], z) for L in LOOKBACKS_H} if zones else {}
            for cb in COMBOS:
                longest = max(cb)
                # baseline: line from longest, must be EV>0 on all three lookbacks
                b = bw[longest]
                if b and b[5] > 0 and b[2] > z:
                    ok = all((eval_line(subxy[L], z, b[0], b[1], b[2]) or -9) > 0 for L in cb)
                    if ok:
                        armed[("base", cb)][(side, c)] = {
                            "entry": z, "sell": b[2], "t1": b[0], "t2": b[1],
                            "shares": round(args.usd / z, 2)}
                # nested: same but on gap-filtered, with the dynamic guard
                if zones:
                    f = bwf.get(longest)
                    floor = math.ceil(args.filt_frac * len(subxy[longest]))
                    if f and f[5] > 0 and f[2] > z and f[6] >= floor:
                        ok = all((eval_line(subxy_f[L], z, f[0], f[1], f[2]) or -9) > 0 for L in cb)
                        if ok:
                            armed[("nest", cb)][(side, c)] = {
                                "entry": z, "sell": f[2], "t1": f[0], "t2": f[1],
                                "shares": round(args.usd / z, 2), "zones": zones}
        # trade the next 30 min OOS
        for ws in all_ws:
            if not (T <= ws < T + REFRESH and ws + WINDOW <= t_end):
                continue
            w = winmap[ws]
            for (side, c), (x, y, g) in wdots[ws].items():
                token = w["tu"] if side == "up" else w["td"]
                for cb in COMBOS:
                    sb = armed[("base", cb)].get((side, c))
                    if sb:
                        r = do_replay(ws, token, side, sb)
                        if r:
                            res[("base", cb)].append((r[0], r[1], sb["shares"] * sb["entry"]))
                    sn = armed[("nest", cb)].get((side, c))
                    if sn and g is not None and any(a <= g <= b for a, b in sn["zones"]):
                        r = do_replay(ws, token, side, sn)
                        if r:
                            res[("nest", cb)].append((r[0], r[1], sn["shares"] * sn["entry"]))
        T += REFRESH

    def ev(rows):
        fills = [r for r in rows if r[0]]
        n = len(fills)
        if n == 0:
            return (0, 0.0, 0.0)
        pnl = sum(r[1] for r in fills)
        stake = sum(r[2] for r in fills)
        wins = sum(1 for r in fills if r[1] > 1e-9)
        return (n, wins / n, pnl / stake if stake else 0.0)

    print(f"  {'combo (h)':>12} | {'BASE n':>7} {'win':>4} {'EV/fill':>7} | "
          f"{'NEST n':>7} {'win':>4} {'EV/fill':>7}")
    rankrows = []
    for cb in COMBOS:
        bn, bw_, be = ev(res[("base", cb)])
        nn, nw, ne = ev(res[("nest", cb)])
        rankrows.append((cb, bn, bw_, be, nn, nw, ne))
    for cb, bn, bw_, be, nn, nw, ne in sorted(rankrows, key=lambda r: -max(r[3], r[6])):
        lbl = "/".join(str(h) for h in cb)
        print(f"  {lbl:>12} | {bn:>7} {bw_:>3.0%} {be:>+7.2f} | {nn:>7} {nw:>3.0%} {ne:>+7.2f}")
    print("\n  Sweet spot only matters if it's CONSISTENTLY ahead; if all rows cluster")
    print("  near the same negative EV, it's noise. PILOT ~3 days; confirm over weeks.")
    conn.close()


if __name__ == "__main__":
    main()

"""Config brute-force x time-of-day, 30-min cadence (experiment, not in the menu).

For every config (3-lookback combo from {24,16,8,6,4}h x {baseline, nested}) at a
30-min refresh, tag each OOS fill by time-of-day. Then answer:
  * OVERALL: which single config has the best pooled OOS EV? (the "optimal overall
    config to determine signals")
  * PER TIME WINDOW: which config is best in each 3h bucket? (brute force per window)
  * CONSISTENCY: does one config win across most buckets (a real overall optimum) or a
    different config per bucket (noise -> no stable config)?

    python experiment_config_tod.py [--filt-frac 0.10 --warmup-h 24]

*** OVERFIT WARNING (max): per-3h-bucket best-config on ~3 days is ~noise (each bucket
holds ~3 windows-per-slot). Trust the CONSISTENCY, not any single best cell. ***
"""

import os
import math
import time
import bisect
import argparse
import itertools
from collections import defaultdict

from experiment_combined import load_full
from experiment_walkforward import open_merged, replay_leg
from analysis.exit_maps import best_conditional, best_sell_window, entry_and_exit, entry_margin
from exec_engine.config import SafetyConfig

WINDOW = 300.0
REFRESH = 1800.0
LOOKBACKS_H = [4, 6, 8, 16, 24]
COMBOS = list(itertools.combinations(LOOKBACKS_H, 3))
FIXED = ("nest", (8, 16, 24))   # the best stable overall config, for the honest "best times"


def eval_line(xy, z, t1, t2, T):
    sub = [y for x, y in xy if t1 <= x <= t2]
    n = len(sub)
    if n < 5:
        return None
    reach = sum(1 for y in sub if y >= T - 1e-9) / n
    return reach * (T - z) / z - (1.0 - reach)


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
    configs = [(s, cb) for s in ("base", "nest") for cb in COMBOS]
    print(f"data: {len(dbs)} db(s), {len(windows)} windows; entries {args.entry_lo}-"
          f"{args.entry_hi}c; 30-min cadence; {len(configs)} configs")
    print("*** OVERFIT WARNING: trust consistency, not the top cell ***\n")

    # res[config] = list of (filled, pnl, stake, hour)
    res = {cfg: [] for cfg in configs}
    memo = {}

    def do_replay(ws, token, side, sig):
        key = (ws, side, sig["entry"], round(sig["sell"], 2), sig["t1"], sig["t2"])
        if key not in memo:
            memo[key] = replay_leg(conn, ws, token, side, sig, winmap[ws]["outcome"], scfg)
        return memo[key]

    T = t_start
    while T < t_end:
        armed = {cfg: {} for cfg in configs}
        for (side, c), lst in dotmap.items():
            ws_a = ws_arr[(side, c)]
            hi = bisect.bisect_right(ws_a, T - WINDOW)
            if hi < 24:
                continue
            z = c / 100.0
            past = lst[:hi]
            mdots = [(g, y, "x") for (ws, x, y, g) in past if g is not None]
            bc = best_conditional(mdots, z)
            zones = bc[2] if bc else None
            floor = math.ceil(args.filt_frac * len(past))
            subxy, subxy_f = {}, {}
            for L in LOOKBACKS_H:
                lo = bisect.bisect_left(ws_a, T - L * 3600)
                seg = lst[lo:hi]
                subxy[L] = [(x, y) for (ws, x, y, g) in seg]
                if zones:
                    subxy_f[L] = [(x, y) for (ws, x, y, g) in seg
                                  if g is not None and any(a <= g <= b for a, b in zones)]
            bw = {L: best_sell_window(subxy[L], z) for L in LOOKBACKS_H}
            bwf = {L: best_sell_window(subxy_f[L], z) for L in LOOKBACKS_H} if zones else {}
            for cb in COMBOS:
                longest = max(cb)
                b = bw[longest]
                if b and b[5] > 0 and b[2] > z and all(
                        (eval_line(subxy[L], z, b[0], b[1], b[2]) or -9) > 0 for L in cb):
                    armed[("base", cb)][(side, c)] = {"entry": z, "sell": b[2], "t1": b[0],
                                                      "t2": b[1], "shares": round(args.usd / z, 2)}
                if zones:
                    f = bwf.get(longest)
                    if f and f[5] > 0 and f[2] > z and f[6] >= floor and all(
                            (eval_line(subxy_f[L], z, f[0], f[1], f[2]) or -9) > 0 for L in cb):
                        armed[("nest", cb)][(side, c)] = {"entry": z, "sell": f[2], "t1": f[0],
                                                          "t2": f[1], "shares": round(args.usd / z, 2),
                                                          "zones": zones}
        for ws in all_ws:
            if not (T <= ws < T + REFRESH and ws + WINDOW <= t_end):
                continue
            w = winmap[ws]
            hour = time.localtime(ws).tm_hour
            for (side, c), (x, y, g) in wdots[ws].items():
                token = w["tu"] if side == "up" else w["td"]
                for cb in COMBOS:
                    sb = armed[("base", cb)].get((side, c))
                    if sb:
                        r = do_replay(ws, token, side, sb)
                        if r:
                            res[("base", cb)].append((r[0], r[1], sb["shares"] * sb["entry"], hour))
                    sn = armed[("nest", cb)].get((side, c))
                    if sn and g is not None and any(a <= g <= b for a, b in sn["zones"]):
                        r = do_replay(ws, token, side, sn)
                        if r:
                            res[("nest", cb)].append((r[0], r[1], sn["shares"] * sn["entry"], hour))
        T += REFRESH

    def ev(rows):
        fills = [r for r in rows if r[0]]
        n = len(fills)
        if n == 0:
            return None
        pnl = sum(r[1] for r in fills)
        stake = sum(r[2] for r in fills)
        return (n, pnl / stake if stake else 0.0)

    def cname(cfg):
        return f"{cfg[0]}:{'/'.join(str(h) for h in cfg[1])}"

    # OVERALL ranking
    print("=== OVERALL best configs (pooled OOS EV/fill) ===")
    ov = [(cfg, ev(res[cfg])) for cfg in configs]
    ov = [(cfg, s) for cfg, s in ov if s and s[0] >= 30]
    for cfg, (n, e) in sorted(ov, key=lambda r: -r[1][1])[:8]:
        print(f"  {cname(cfg):>16}  n={n:>4}  EV/fill {e:>+5.2f}")

    # PER TIME WINDOW best config
    print("\n=== best config per 3h time window (brute force) ===")
    print(f"  {'window':>11} | {'best config':>16} {'EV':>6} {'n':>4} | runner-up")
    winners = []
    for b in range(8):
        cand = []
        for cfg in configs:
            sub = [r for r in res[cfg] if b * 3 <= r[3] < b * 3 + 3]
            s = ev(sub)
            if s and s[0] >= 15:
                cand.append((cfg, s[1], s[0]))
        cand.sort(key=lambda r: -r[1])
        if cand:
            cfg, e, n = cand[0]
            ru = cname(cand[1][0]) if len(cand) > 1 else "-"
            winners.append(cfg)
            print(f"  {b*3:02d}:00-{b*3+3:02d}:00 | {cname(cfg):>16} {e:>+6.2f} {n:>4} | {ru}")
        else:
            print(f"  {b*3:02d}:00-{b*3+3:02d}:00 | (too few fills)")

    # BEST TIMES with ONE fixed config (honest -- no per-window argmax overfit)
    print(f"\n=== best times to trade with the FIXED best config ({cname(FIXED)}) ===")
    print("  (one strategy, fair across all hours -- this is the trustworthy 'when to trade')")
    rows_tod = []
    for b in range(8):
        sub = [r for r in res.get(FIXED, []) if b * 3 <= r[3] < b * 3 + 3]
        s = ev(sub)
        rows_tod.append((b, s))
    for b, s in sorted(rows_tod, key=lambda r: -(r[1][1] if r[1] else -9)):
        if s and s[0] >= 8:
            print(f"  {b*3:02d}:00-{b*3+3:02d}:00 : EV/fill {s[1]:>+5.2f}  (n={s[0]})")
        else:
            print(f"  {b*3:02d}:00-{b*3+3:02d}:00 : (too few fills)")

    # CONSISTENCY
    print("\n=== consistency ===")
    cnt = defaultdict(int)
    for cfg in winners:
        cnt[cfg] += 1
    if cnt:
        top = max(cnt.items(), key=lambda kv: kv[1])
        print(f"  most-frequent per-window winner: {cname(top[0])} wins {top[1]}/{len(winners)} buckets")
        print(f"  distinct winning configs across {len(winners)} buckets: {len(cnt)}")
        print("  -> few distinct winners = a stable config exists; many = noise/no stable config")
    print("\n  PILOT ~3 days: per-bucket cells are tiny -> mostly noise. Confirm over weeks.")
    conn.close()


if __name__ == "__main__":
    main()

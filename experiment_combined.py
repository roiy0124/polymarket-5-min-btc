"""Combined two-screen decision evaluator (experiment, not in the menu).

The strategy you described: BUY only when BOTH screens agree, out-of-sample.
  SCREEN A (time-based exit line, static edge): for this entry price, best_sell_window
    finds a (buy-window, sell T) that is positive confidence-adjusted EV AND backed by
    a real share of the map's dots (coverage). [fit on PAST data]
  SCREEN B (gap response, conditional edge): at the moment of entry, the CURRENT BTC
    gap sits where the realized win-rate (reaching sell T) BEATS breakeven -- estimated
    locally (k nearest training gaps), so it's "how the price responds to the gap,"
    not a gap>0 rule. [fit on PAST data]

We trade Screen A's line with realistic queue-based fills, and tag each trade by
whether B also passed -- then compare BOTH vs A-alone vs A-but-not-B. The question:
does ANDing the gap-response screen onto the exit-line screen actually raise EV, or
just cut volume?

    python experiment_combined.py

*** PILOT -- one ~3-day sample CANNOT decide edge (and both screens are the optimistic
mid-fill metric). This tests whether the COMBINATION beats its parts; a real verdict
needs weeks of data + the realistic-fill caveat. ***
"""

import os
import time
import argparse

from experiment_walkforward import open_merged, replay_leg
from analysis.exit_maps import best_sell_window, entry_and_exit, entry_margin
from exec_engine.config import SafetyConfig

WINDOW = 300.0


def load_full(conn):
    out = []
    for ws, outcome, strike, tu, td in conn.execute(
            "SELECT window_start, resolved_outcome, strike_binance, token_up, token_down "
            "FROM windows WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start"):
        snaps = conn.execute(
            "SELECT time_left, up_mid, down_mid, btc_binance FROM snapshots "
            "WHERE window_start=? AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        if not snaps:
            continue
        up, dn = [], []
        for tl, um, dm, btc in snaps:
            x = max(0.0, (WINDOW - tl) / 60.0)
            g = (btc - strike) if (btc is not None and strike is not None) else None
            up.append((x, um, g))
            if dm is not None:
                dn.append((x, dm, g))
        out.append({"ws": ws, "outcome": outcome, "tu": tu, "td": td, "up": up, "down": dn})
    return out


def train_dots(windows, side, cent):
    res = []
    for w in windows:
        won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
        eb = entry_and_exit(w[side], cent, won)
        if eb is None:
            continue
        res.append((eb[0], eb[1], entry_margin(w[side], cent)))   # (entry_x, exit_value, gap)
    return res


def screen_b_reach(dots, T, g, k):
    """Local realized win-rate (reach sell T) among the k training dots whose gap is
    nearest to g -- the gap RESPONSE at g. Returns None if <k dots have a gap."""
    cand = sorted((abs(d[2] - g), d[1]) for d in dots if d[2] is not None)
    if len(cand) < k:
        return None
    near = cand[:k]
    return sum(1 for _, y in near if y >= T - 1e-9) / k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-h", type=float, default=24.0, dest="warmup_h")
    ap.add_argument("--block-h", type=float, default=6.0, dest="block_h")
    ap.add_argument("--entry-lo", type=int, default=20, dest="entry_lo")
    ap.add_argument("--entry-hi", type=int, default=75, dest="entry_hi")
    ap.add_argument("--k", type=int, default=30, help="kNN for the gap-response screen")
    ap.add_argument("--min-ev-a", type=float, default=0.0, dest="min_ev_a")
    ap.add_argument("--usd", type=float, default=2.0)
    args = ap.parse_args()

    conn, dbs = open_merged()
    windows = load_full(conn)
    all_ws = [w["ws"] for w in windows]
    by_ws = {w["ws"]: w for w in windows}
    t0, t_end = all_ws[0], all_ws[-1] + WINDOW
    t_start = t0 + args.warmup_h * 3600
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    print(f"data: {len(dbs)} db(s), {len(windows)} windows; warmup {args.warmup_h:g}h, "
          f"blocks {args.block_h:g}h, entries {args.entry_lo}-{args.entry_hi}c, k={args.k}")
    print("*** PILOT -- combination test only; not a verdict ***\n")

    cents = list(range(args.entry_lo, args.entry_hi + 1))
    recs = []                       # each: (filled, pnl, stake, b_pass)
    T = t_start
    blk = 0
    while T < t_end:
        train = [w for w in windows if w["ws"] + WINDOW <= T]
        test = [w for w in windows if T <= w["ws"] < T + args.block_h * 3600
                and w["ws"] + WINDOW <= t_end]
        # fit screens on PAST data
        scrA, tcache = {}, {}
        for side in ("up", "down"):
            for c in cents:
                d = train_dots(train, side, c)
                tcache[(side, c)] = d
                z = c / 100.0
                bw = best_sell_window([(x, y) for x, y, g in d], z)
                if bw and bw[5] > args.min_ev_a and bw[2] > z:   # bw=(t1,t2,T,win,roi,ev,n)
                    scrA[(side, c)] = {"entry": z, "sell": bw[2], "t1": bw[0], "t2": bw[1],
                                       "shares": round(args.usd / z, 2)}
        # trade the block out-of-sample
        for w in test:
            for side in ("up", "down"):
                for c in cents:
                    sig = scrA.get((side, c))
                    if not sig:
                        continue
                    won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
                    eb = entry_and_exit(w[side], c, won)
                    if eb is None:
                        continue
                    gW = entry_margin(w[side], c)
                    if gW is None:
                        continue
                    reachB = screen_b_reach(tcache[(side, c)], sig["sell"], gW, args.k)
                    if reachB is None:
                        continue
                    b_pass = reachB > (sig["entry"] / sig["sell"])       # beats breakeven at g
                    token = w["tu"] if side == "up" else w["td"]
                    r = replay_leg(conn, w["ws"], token, side, sig, w["outcome"], scfg)
                    if r is None:
                        continue
                    recs.append((r[0], r[1], sig["shares"] * sig["entry"], b_pass))
        blk += 1
        T += args.block_h * 3600

    def summ(name, rows):
        fills = [r for r in rows if r[0]]
        n = len(fills)
        if n == 0:
            print(f"  {name:>16}: 0 fills")
            return
        wins = sum(1 for r in fills if r[1] > 1e-9)
        pnl = sum(r[1] for r in fills)
        stake = sum(r[2] for r in fills)
        print(f"  {name:>16}: fills {n:>4}  win {wins/n:>4.0%}  pnl {pnl:>+8.1f}  "
              f"EV/fill {pnl/stake if stake else 0:>+5.2f}")

    print(f"out-of-sample trades: {len(recs)} attempts, {blk} blocks\n")
    summ("A only (all)", recs)
    summ("A & B (both)", [r for r in recs if r[3]])
    summ("A & NOT-B", [r for r in recs if not r[3]])
    print("\n  If 'A & B' EV/fill clearly beats 'A only' AND 'A & NOT-B', the gap-response")
    print("  screen adds value. If it just cuts volume at similar EV, it doesn't.")
    print("  PILOT: optimistic-fill + ~3 days; confirm over weeks before believing it.")
    conn.close()


if __name__ == "__main__":
    main()

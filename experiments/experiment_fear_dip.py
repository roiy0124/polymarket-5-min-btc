"""FEAR-DIP (contrarian SMT) — STANDALONE strategy test.

The user's idea (named: short-term reversal / liquidity-provision to panic sellers, SMT-gated):
when peers are bullish but a laggard coin's UP token gets PANIC-DUMPED (because its spot hasn't
followed yet), the token overshoots DOWN to a fear discount; the laggard then tends to catch up to
the correlated move, so the token reverts. We BUY the discount (taker) and HOLD to 0/1 resolution.

CAUSAL. At a decision time (time_left = tau on a 30s grid), for coin X:
  drop_X   = up_mid_X(tau) - up_mid_X(tau+30)        # recent token capitulation  (< -DROP)
  peer_cons= mean up_mid of the OTHER coins at tau   # cross-asset thesis still bullish (>= PEER)
  laggard  = up_mid_X(tau) < peer_cons - LAG         # X is below the pack (the gap to close)
Fire on the FIRST qualifying tau per (coin, window) [one obs/window]. Entry = up_ask_X(tau);
outcome = resolved_outcome==Up. EV via net_ev (taker entry fee, hold-to-resolution, -100% on loss).

HONEST: includes every fired window (incl. the dips that were RIGHT and resolved Down). The key
question = does the signal pick windows where realized Up-rate > the discounted entry price (overshoot)?
Tested vs a same-price-band PLACEBO (random mid-band buys) + Wilson-LB(win) vs breakeven + per-coin.

    python experiment_fear_dip.py --drop 0.08 --peer 0.55 --lag 0.10
"""

import argparse
import random
import sqlite3

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb

GRID = [240, 210, 180, 150, 120, 90, 60]   # time_left decision points (30s apart)
TOL = 12.0                                  # max |time_left - tau| to accept a snapshot for a grid point


def load_all(coins_list):
    """data[coin][ws] = {tau: (up_mid, up_ask)}; meta[coin][ws] = won(1/0). Merged across all_dbs."""
    data, meta = {c: {} for c in coins_list}, {c: {} for c in coins_list}
    for c in coins_list:
        for db in coins.all_dbs(c):
            try:
                conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            except sqlite3.Error:
                continue
            try:
                wins = conn.execute(
                    "SELECT window_start, resolved_outcome FROM windows "
                    "WHERE resolved_outcome IN ('Up','Down')").fetchall()
            except sqlite3.OperationalError:
                conn.close(); continue
            for ws, outcome in wins:
                if ws in data[c]:
                    continue
                snaps = conn.execute(
                    "SELECT time_left, up_mid, up_ask FROM snapshots WHERE window_start=? AND "
                    "up_mid IS NOT NULL AND up_ask IS NOT NULL ORDER BY time_left DESC", (ws,)).fetchall()
                if len(snaps) < 10:
                    continue
                grid = {}
                for tau in GRID:
                    best = min(snaps, key=lambda r: abs(r[0] - tau))
                    if abs(best[0] - tau) <= TOL:
                        grid[tau] = (best[1], best[2])     # (up_mid, up_ask)
                if grid:
                    data[c][ws] = grid
                    meta[c][ws] = 1 if outcome == "Up" else 0
            conn.close()
    return data, meta


def scan(data, meta, coins_list, drop, peer, lag, band):
    """Return (fired, universe). fired/universe items = (coin, ws, tau, up_mid, up_ask, won)."""
    fired, universe = [], []
    # peer consensus needs all coins' up_mid at (ws, tau); precompute per (ws, tau)
    all_ws = set().union(*[set(data[c]) for c in coins_list])
    for ws in all_ws:
        present = [c for c in coins_list if ws in data[c]]
        if len(present) < 3:
            continue
        for X in present:
            won = meta[X][ws]
            firstfire = None
            for tau in GRID:
                if tau == GRID[0]:
                    continue                              # need tau+30 (earlier)
                g = data[X][ws]
                if tau not in g or (tau + 30) not in g:
                    continue
                um, ua = g[tau]
                um_prev = g[tau + 30][0]
                peers = [data[p][ws][tau][0] for p in present if p != X and tau in data[p][ws]]
                if len(peers) < 2:
                    continue
                pc = sum(peers) / len(peers)
                # universe = any mid-band Up buy opportunity (for the placebo baseline)
                if band[0] <= um <= band[1]:
                    universe.append((X, ws, tau, um, ua, won))
                # fear-dip signal
                dropX = um - um_prev
                if dropX <= -drop and pc >= peer and um <= pc - lag and band[0] <= um <= band[1]:
                    if firstfire is None:
                        firstfire = (X, ws, tau, um, ua, won)
            if firstfire:
                fired.append(firstfire)
    return fired, universe


def ev_stats(rows):
    if not rows:
        return None
    per = [net_ev_per_dollar(ua, won, "taker", "hold") for (_, _, _, um, ua, won) in rows]
    per = [x for x in per if x is not None]
    n = len(rows); k = sum(won for *_, won in rows)
    mean_ask = sum(ua for (_, _, _, um, ua, won) in rows) / n
    mean_mid = sum(um for (_, _, _, um, ua, won) in rows) / n
    return dict(n=n, win=k / n, mid=mean_mid, ask=mean_ask, ev=sum(per) / len(per),
                wlb=wilson_lb(k, n), be=breakeven_winrate(mean_ask),
                resid=k / n - mean_mid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", type=float, default=0.08, help="min recent up_mid drop (capitulation)")
    ap.add_argument("--peer", type=float, default=0.55, help="min peer Up-consensus (thesis bullish)")
    ap.add_argument("--lag", type=float, default=0.10, help="min (peer_cons - X up_mid) (X is the laggard)")
    ap.add_argument("--band", default="0.20,0.70", help="entry up_mid band (where fear-dips live)")
    ap.add_argument("--boot", type=int, default=4000)
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))
    cl = list(coins.ENABLED)

    print("loading (merged across all DBs) ...", flush=True)
    data, meta = load_all(cl)
    for c in cl:
        print(f"  {c}: {len(data[c])} windows")
    fired, universe = scan(data, meta, cl, args.drop, args.peer, args.lag, band)

    print(f"\nFEAR-DIP standalone  |  drop<=-{args.drop} peer>={args.peer} lag>={args.lag} "
          f"band={band}  |  buy Up @ask, hold to 0/1, taker fee")
    s = ev_stats(fired)
    u = ev_stats(universe)
    if not s:
        print("  no fired signals — loosen thresholds."); return
    print(f"\n  {'set':>14} {'n':>5} {'win%':>6} {'mid':>5} {'ask':>5} {'net EV/$1':>10} "
          f"{'resid':>7} {'WilsonLB':>9} {'be':>6}")
    print(f"  {'FEAR-DIP fired':>14} {s['n']:>5} {100*s['win']:>5.1f}% {s['mid']:>5.2f} {s['ask']:>5.2f} "
          f"{s['ev']:>+10.4f} {s['resid']:>+7.3f} {s['wlb']:>9.3f} {s['be']:>6.3f}")
    print(f"  {'mid-band univ':>14} {u['n']:>5} {100*u['win']:>5.1f}% {u['mid']:>5.2f} {u['ask']:>5.2f} "
          f"{u['ev']:>+10.4f} {u['resid']:>+7.3f} {u['wlb']:>9.3f} {u['be']:>6.3f}  (baseline)")

    # PLACEBO: random same-size subset of the mid-band universe -> does the signal beat random buying?
    rng = random.Random(7)
    k = s['n']
    if len(universe) > k:
        evf = s['ev']
        draws = []
        for _ in range(args.boot):
            sub = rng.sample(universe, k)
            per = [net_ev_per_dollar(ua, won, "taker", "hold") for (_, _, _, um, ua, won) in sub]
            draws.append(sum(per) / len(per))
        draws.sort()
        p = sum(1 for x in draws if x >= evf) / len(draws)
        print(f"\n  PLACEBO (random {k} mid-band buys): mean EV {sum(draws)/len(draws):+.4f}, "
              f"95th {draws[int(0.95*len(draws))]:+.4f}; signal EV {evf:+.4f} -> p={p:.3f} "
              f"{'(signal beats random)' if p<0.05 else '(NOT distinguishable from random)'}")

    # per-coin (replication)
    print(f"\n  per-coin fired:")
    for c in cl:
        sc = ev_stats([r for r in fired if r[0] == c])
        if sc:
            print(f"    {c:>5}: n={sc['n']:>3} win {100*sc['win']:>5.1f}% EV {sc['ev']:>+7.4f} "
                  f"resid {sc['resid']:>+6.3f} (wlb-be {sc['wlb']-sc['be']:>+.3f})")
    print("\n  READ: real overreaction edge iff FEAR-DIP win% & EV & resid clearly beat the mid-band")
    print("  baseline AND the placebo (p<0.05) AND it replicates per-coin AND Wilson-LB(win)>breakeven")
    print("  net of the mid-price taker fee. loss-light per-coin cells => Wilson, not the point estimate.")


if __name__ == "__main__":
    main()

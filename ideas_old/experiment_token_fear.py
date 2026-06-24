"""TOKEN-FEAR (stock-vs-stock) — the user's sharpened fear idea + the FOLLOW flip.

Fear is a PREDICTION-MARKET event, so the reference is the OTHER tokens, not spot:
compare an alt's UP-token move to the PEER tokens' moves. When the alt token gets DUMPED
but the peer tokens did NOT drop, the alt moved UN-PROPORTIONATELY down.
  --fade   (the user's thesis): BUY the alt UP token (the dump is unjustified fear -> reverts)
  --follow (the flip)         : BUY the alt DOWN token (the dump is INFORMED -> keeps going)
Hold to 0/1, taker fee. The --fade test (n=496) came back resid -0.056, all-6-coins negative,
placebo p=0.999 => the dump is INFORMED, not fear. This file also tests --follow to see if the
informed dump is a tradable Down signal net of the Down-side ask+fee.

CAUSAL. At time_left = tau on a 30s grid, for coin X (peers = the other present coins):
  dropX = up_mid_X(tau) - up_mid_X(tau+30)              # alt token change (<= -DROP)
  pchg  = mean_p[ up_mid_p(tau) - up_mid_p(tau+30) ]    # peer token change
  FEAR iff dropX <= -DROP  AND  pchg >= -PEER_TOL (peers ~flat/up)  AND (dropX-pchg) <= -GAP.
Entry = up_ask (fade) or down_ask (follow); outcome = Up / Down. EV via net_ev (taker, hold).

    python experiment_token_fear.py --fade        # buy Up  (the fear-fade thesis)
    python experiment_token_fear.py --follow       # buy Down (follow the informed dump)
"""
import argparse
import os
import random
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (archived in ideas_old/)

import coins
from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb
from experiment_fear_dip import GRID, TOL


def load_sides(coins_list):
    """data[c][ws] = {tau: (up_mid, up_ask, down_mid, down_ask)}; meta[c][ws] = won_up(1/0)."""
    data, meta = {c: {} for c in coins_list}, {c: {} for c in coins_list}
    for c in coins_list:
        for db in coins.all_dbs(c):
            try:
                conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            except sqlite3.Error:
                continue
            try:
                wins = conn.execute("SELECT window_start, resolved_outcome FROM windows "
                                    "WHERE resolved_outcome IN ('Up','Down')").fetchall()
            except sqlite3.OperationalError:
                conn.close(); continue
            for ws, outcome in wins:
                if ws in data[c]:
                    continue
                snaps = conn.execute(
                    "SELECT time_left, up_mid, up_ask, down_mid, down_ask FROM snapshots "
                    "WHERE window_start=? AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND "
                    "down_ask IS NOT NULL ORDER BY time_left DESC", (ws,)).fetchall()
                if len(snaps) < 10:
                    continue
                grid = {}
                for tau in GRID:
                    best = min(snaps, key=lambda r: abs(r[0] - tau))
                    if abs(best[0] - tau) <= TOL:
                        grid[tau] = (best[1], best[2], best[3], best[4])
                if grid:
                    data[c][ws] = grid
                    meta[c][ws] = 1 if outcome == "Up" else 0
            conn.close()
    return data, meta


def scan(data, meta, coins_list, drop, peer_tol, gap, band, follow):
    """Returns (fired, universe); items = (coin, ws, tau, mid, ask, won) for the CHOSEN side."""
    fired, universe = [], []
    all_ws = set().union(*[set(data[c]) for c in coins_list])
    for ws in all_ws:
        present = [c for c in coins_list if ws in data[c]]
        if len(present) < 3:
            continue
        for X in present:
            won_up = meta[X][ws]
            # the chosen side's (mid, ask, won): fade=Up, follow=Down
            def row_for(tau):
                um, ua, dm, da = data[X][ws][tau]
                return (X, ws, tau, dm, da, 1 - won_up) if follow else (X, ws, tau, um, ua, won_up)
            firstfire = None
            for tau in GRID:
                if tau == GRID[0]:
                    continue
                g = data[X][ws]
                if tau not in g or (tau + 30) not in g:
                    continue
                um = g[tau][0]; dropX = um - g[tau + 30][0]
                peer_chg = [data[p][ws][tau][0] - data[p][ws][tau + 30][0]
                            for p in present if p != X
                            and tau in data[p][ws] and (tau + 30) in data[p][ws]]
                if len(peer_chg) < 2:
                    continue
                pchg = sum(peer_chg) / len(peer_chg)
                if band[0] <= um <= band[1]:
                    universe.append(row_for(tau))
                if (dropX <= -drop and pchg >= -peer_tol and (dropX - pchg) <= -gap
                        and band[0] <= um <= band[1]):
                    if firstfire is None:
                        firstfire = row_for(tau)
            if firstfire:
                fired.append(firstfire)
    return fired, universe


def ev_stats(rows):
    if not rows:
        return None
    per = [net_ev_per_dollar(ask, won, "taker", "hold") for (_, _, _, mid, ask, won) in rows]
    per = [x for x in per if x is not None]
    n = len(rows); k = sum(won for *_, won in rows)
    mean_ask = sum(r[4] for r in rows) / n; mean_mid = sum(r[3] for r in rows) / n
    return dict(n=n, win=k / n, mid=mean_mid, ask=mean_ask, ev=sum(per) / len(per),
                wlb=wilson_lb(k, n), be=breakeven_winrate(mean_ask), resid=k / n - mean_mid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--follow", action="store_true", help="BUY Down (follow the informed dump); default = fade (buy Up)")
    ap.add_argument("--drop", type=float, default=0.05)
    ap.add_argument("--peer-tol", type=float, default=0.02)
    ap.add_argument("--gap", type=float, default=0.05)
    ap.add_argument("--band", default="0.20,0.85", help="entry up_mid band (the gate is on the UP token)")
    ap.add_argument("--boot", type=int, default=4000)
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))
    cl = list(coins.ENABLED)
    side = "FOLLOW (buy Down)" if args.follow else "FADE (buy Up)"

    print("loading (merged across all DBs) ...", flush=True)
    data, meta = load_sides(cl)
    for c in cl:
        print(f"  {c}: {len(data[c])} windows")
    fired, universe = scan(data, meta, cl, args.drop, args.peer_tol, args.gap, band, args.follow)

    print(f"\nTOKEN-FEAR {side}  |  alt up_mid drop<=-{args.drop} peers>=-{args.peer_tol} "
          f"gap<=-{args.gap} band={band}  |  hold to 0/1, taker fee")
    s = ev_stats(fired); u = ev_stats(universe)
    if not s:
        print("  no fired signals — loosen thresholds."); return
    print(f"\n  {'set':>14} {'n':>5} {'win%':>6} {'mid':>5} {'ask':>5} {'net EV/$1':>10} "
          f"{'resid':>7} {'WilsonLB':>9} {'be':>6}")
    print(f"  {'fired':>14} {s['n']:>5} {100*s['win']:>5.1f}% {s['mid']:>5.2f} {s['ask']:>5.2f} "
          f"{s['ev']:>+10.4f} {s['resid']:>+7.3f} {s['wlb']:>9.3f} {s['be']:>6.3f}")
    print(f"  {'mid-band univ':>14} {u['n']:>5} {100*u['win']:>5.1f}% {u['mid']:>5.2f} {u['ask']:>5.2f} "
          f"{u['ev']:>+10.4f} {u['resid']:>+7.3f} {u['wlb']:>9.3f} {u['be']:>6.3f}  (baseline)")

    rng = random.Random(7); k = s['n']
    if len(universe) > k:
        draws = []
        for _ in range(args.boot):
            sub = rng.sample(universe, k)
            per = [net_ev_per_dollar(r[4], r[5], "taker", "hold") for r in sub]
            draws.append(sum(per) / len(per))
        draws.sort()
        p = sum(1 for x in draws if x >= s['ev']) / len(draws)
        print(f"\n  PLACEBO (random {k} mid-band buys, same side): mean EV {sum(draws)/len(draws):+.4f}, "
              f"95th {draws[int(0.95*len(draws))]:+.4f}; signal {s['ev']:+.4f} -> p={p:.3f} "
              f"{'(beats random)' if p < 0.05 else '(NOT distinguishable from random)'}")

    print("\n  per-coin fired:")
    for c in cl:
        sc = ev_stats([r for r in fired if r[0] == c])
        if sc:
            print(f"    {c:>5}: n={sc['n']:>3} win {100*sc['win']:>5.1f}% EV {sc['ev']:>+7.4f} "
                  f"resid {sc['resid']:>+6.3f} (wlb-be {sc['wlb']-sc['be']:>+.3f})")
    print("\n  READ: tradable iff fired EV>0 AND beats placebo (p<0.05) AND replicates per-coin")
    print("  AND Wilson-LB(win)>breakeven, net of the (Down-side) ask + taker fee. In-sample => needs OOS.")


if __name__ == "__main__":
    main()

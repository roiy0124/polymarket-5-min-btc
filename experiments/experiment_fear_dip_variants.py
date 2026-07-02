"""FEAR-DIP variants the stress-test was meant to try (run inline; the workflow choked on schema).

Two fairer versions of the user's reversion idea, both CAUSAL, buy Up @ask hold to 0/1 (taker fee),
one obs/window/coin, vs a SAME-PRICE-BAND placebo + per-coin:

  AFTER-RECOVERY: the token DROPPED earlier (tau+60->tau+30) and is now TURNING BACK UP (tau+30->tau),
                  peers still bullish, X still a laggard. Enter on the recovery turn, not the bottom.
  PEER-SURGE:     peer Up-consensus SURGED recently (tau+30->tau) while X did NOT rise / lagged and is
                  below the pack. Enter X Up betting it catches up (the lead-lag thesis directly).

    python experiment_fear_dip_variants.py
"""

import argparse
import random

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb
from experiment_fear_dip import load_all, GRID


def peer_cons(data, present, ws, X, tau):
    vals = [data[p][ws][tau][0] for p in present if p != X and tau in data[p][ws]]
    return (sum(vals) / len(vals)) if len(vals) >= 2 else None


def scan(data, meta, cl, mode, p, band):
    fired, universe = [], []
    all_ws = set().union(*[set(data[c]) for c in cl])
    for ws in all_ws:
        present = [c for c in cl if ws in data[c]]
        if len(present) < 3:
            continue
        for X in present:
            won = meta[X][ws]; g = data[X][ws]; first = None
            for tau in GRID:
                if tau not in g:
                    continue
                um, ua = g[tau]
                if band[0] <= um <= band[1]:
                    universe.append((X, ws, tau, um, ua, won))
                pc = peer_cons(data, present, ws, X, tau)
                if pc is None or not (band[0] <= um <= band[1]):
                    continue
                ok = False
                if mode == "after-recovery":
                    if (tau + 60) in g and (tau + 30) in g:
                        drop_earlier = g[tau + 30][0] - g[tau + 60][0]
                        recover_now = um - g[tau + 30][0]
                        ok = (drop_earlier <= -p["drop"] and recover_now >= p["rec"]
                              and pc >= p["peer"] and um <= pc - p["lag"])
                elif mode == "peer-surge":
                    if (tau + 30) in g:
                        pc_prev = peer_cons(data, present, ws, X, tau + 30)
                        x_move = um - g[tau + 30][0]
                        if pc_prev is not None:
                            surge = pc - pc_prev
                            ok = (surge >= p["surge"] and x_move <= p["xmove"]
                                  and um <= pc - p["lag"])
                if ok and first is None:
                    first = (X, ws, tau, um, ua, won)
            if first:
                fired.append(first)
    return fired, universe


def ev_stats(rows):
    if not rows:
        return None
    per = [net_ev_per_dollar(ua, won, "taker", "hold") for (_, _, _, um, ua, won) in rows]
    per = [x for x in per if x is not None]
    n = len(rows); k = sum(won for *_, won in rows)
    mask = sum(ua for (_, _, _, um, ua, won) in rows) / n
    msm = sum(um for (_, _, _, um, ua, won) in rows) / n
    return dict(n=n, win=k / n, mid=msm, ask=mask, ev=sum(per) / len(per),
                wlb=wilson_lb(k, n), be=breakeven_winrate(mask), resid=k / n - msm)


def report(name, fired, universe, boot=4000):
    s = ev_stats(fired); u = ev_stats(universe)
    print(f"\n==== {name} ====")
    if not s:
        print("  no fired signals."); return
    print(f"  {'set':>14} {'n':>5} {'win%':>6} {'mid':>5} {'ask':>5} {'EV/$1':>9} {'resid':>7} {'wlb-be':>7}")
    print(f"  {'fired':>14} {s['n']:>5} {100*s['win']:>5.1f}% {s['mid']:>5.2f} {s['ask']:>5.2f} "
          f"{s['ev']:>+9.4f} {s['resid']:>+7.3f} {s['wlb']-s['be']:>+7.3f}")
    print(f"  {'mid-band base':>14} {u['n']:>5} {100*u['win']:>5.1f}% {u['mid']:>5.2f} {u['ask']:>5.2f} "
          f"{u['ev']:>+9.4f} {u['resid']:>+7.3f} {u['wlb']-u['be']:>+7.3f}")
    rng = random.Random(7); k = s['n']
    if len(universe) > k:
        draws = []
        for _ in range(boot):
            sub = rng.sample(universe, k)
            pr = [net_ev_per_dollar(ua, won, "taker", "hold") for (_, _, _, um, ua, won) in sub]
            draws.append(sum(pr) / len(pr))
        draws.sort()
        pv = sum(1 for x in draws if x >= s['ev']) / len(draws)
        print(f"  placebo (random {k}): mean {sum(draws)/len(draws):+.4f}; signal {s['ev']:+.4f} -> "
              f"p={pv:.3f} {'(beats random)' if pv<0.05 else '(NOT vs random)'}")
    pc = {c: ev_stats([r for r in fired if r[0] == c]) for c in coins.ENABLED}
    print("  per-coin: " + "  ".join(
        f"{c}:n{pc[c]['n']}/ev{pc[c]['ev']:+.2f}" for c in coins.ENABLED if pc[c]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", default="0.20,0.70")
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))
    cl = list(coins.ENABLED)
    print("loading ...", flush=True)
    data, meta = load_all(cl)

    fa, ua = scan(data, meta, cl, "after-recovery",
                  dict(drop=0.06, rec=0.03, peer=0.55, lag=0.05), band)
    report("AFTER-RECOVERY (buy the bounce, not the bottom)", fa, ua)

    fb, ub = scan(data, meta, cl, "peer-surge",
                  dict(surge=0.05, xmove=0.01, lag=0.05), band)
    report("PEER-SURGE (peers jumped, X lagged -> buy X to catch up)", fb, ub)

    print("\n  BAR: beats same-price placebo (p<0.05) + cross-coin (not 1-coin) + wlb-be>0 net of fee.")


if __name__ == "__main__":
    main()

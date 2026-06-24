"""HYBRID: favorite-tail (our best strategy) + fear-dip (the new contrarian signal), both deciding.

Common action = BUY the UP token, HOLD to 0/1 (taker entry fee, via net_ev). Two independent,
causal triggers per (coin, window):
  FAV  = favorite-tail Up side: at time_left~30s, Up is a deep favorite (ask>=0.95).  [our best strategy]
  DIP  = fear-dip: mid-round, peers bullish + X's Up token panic-dumped + X laggard.  [the new idea]

Reports how they combine: FAV-only, DIP-only, BOTH (the same window fired both -> a dip that
RECOVERED into a favorite, the user's exact pattern), and the UNION. Plus the tradeable GATE view:
do FAV trades whose coin had an earlier fear-dip (dip-then-recover, all info before 30s) win more or
less than always-favorites? = "does the dip signal help the favorite-tail decide?"

    python experiment_hybrid.py
"""

import argparse

import coins
from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb
from experiment_b_component import load_alt_positions          # favorite-tail loader (exposes sign)
import experiment_fear_dip as fd


def ev_stats(rows):                                            # rows: (ask, won)
    if not rows:
        return None
    per = [net_ev_per_dollar(a, w, "taker", "hold") for a, w in rows]
    per = [x for x in per if x is not None]
    n = len(rows); k = sum(w for _, w in rows)
    a = sum(a for a, _ in rows) / n
    return dict(n=n, win=k / n, ev=sum(per) / len(per), wlb=wilson_lb(k, n), be=breakeven_winrate(a))


def line(tag, s, note=""):
    if not s:
        print(f"  {tag:>22}  (none)"); return
    star = "*" if (s["wlb"] > s["be"]) else " "
    print(f"  {tag:>22}  n={s['n']:>4} win {100*s['win']:>5.1f}%  EV/$1 {s['ev']:>+8.4f}  "
          f"wlb-be {s['wlb']-s['be']:>+.3f}{star}  {note}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", type=float, default=0.08)
    ap.add_argument("--peer", type=float, default=0.55)
    ap.add_argument("--lag", type=float, default=0.10)
    ap.add_argument("--band", default="0.20,0.70")
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))
    cl = list(coins.ENABLED)

    print("loading ...", flush=True)
    # FAV-Up book: favorite-tail Up side (sign==+1), buy Up @ask, hold
    fav = {}     # (coin, ws) -> (ask, won)
    for c in cl:
        for ws, t, ask, sign, won in load_alt_positions(c, 30.0, 0.95, 9.0):
            if sign > 0:                                       # Up is the favorite
                fav[(c, ws)] = (ask, won)
    # DIP-Up book: fear-dip fired
    data, meta = fd.load_all(cl)
    dip_fired, _ = fd.scan(data, meta, cl, args.drop, args.peer, args.lag, band)
    dip = {(c, ws): (ua, won) for (c, ws, tau, um, ua, won) in dip_fired}

    favk, dipk = set(fav), set(dip)
    both = favk & dipk
    fav_only = favk - dipk
    dip_only = dipk - favk

    print(f"\nHYBRID  favorite-tail(Up) + fear-dip  |  action: buy Up, hold to 0/1  |  "
          f"FAV n={len(fav)}  DIP n={len(dip)}  overlap(BOTH)={len(both)}")
    print()
    line("FAV-only", ev_stats([fav[k] for k in fav_only]), "(favorite, no dip)")
    line("DIP-only", ev_stats([dip[k] for k in dip_only]), "(dip, never a favorite)")
    line("BOTH: FAV entry", ev_stats([fav[k] for k in both]), "(dip that RECOVERED to a favorite)")
    line("BOTH: DIP entry", ev_stats([dip[k] for k in both]), "(same windows, the mid-round dip entry)")
    print()
    line("FAV total (the base)", ev_stats(list(fav.values())))
    line("UNION (FAV+DIP book)", ev_stats(list(fav.values()) + list(dip.values())),
         "(does adding the dip book help the base?)")
    print()
    # GATE: does an earlier fear-dip improve the favorite-tail decision? (info all before 30s)
    print("  GATE -- does the dip signal help the favorite-tail decide? (FAV trades split):")
    line("FAV w/ earlier dip", ev_stats([fav[k] for k in both]), "(coin dip-then-recovered)")
    line("FAV w/o earlier dip", ev_stats([fav[k] for k in fav_only]), "(always a favorite)")
    print("\n  READ: the hybrid helps only if UNION beats FAV-total, or the GATE split is")
    print("  meaningfully + (dip-confirmed favorites win more) with wlb>be. A negative/again-")
    print("  -breakeven DIP book just drags the base. loss-light cells: judge by wlb-be, not EV.")


if __name__ == "__main__":
    main()

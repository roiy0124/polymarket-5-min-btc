"""INDEPENDENT TEST — apply the score-selectivity theory to the favorite-tail strategy.

Does NOT touch experiment_favorite_tail.py / the saved strategy. It re-implements the same
causal favorite-tail position (at time_left~TL, buy the favorite (price vs strike) at its ask if
ask>=MIN_ASK, hold to 0/1, taker entry fee 0.07*a*(1-a)), then SCORES each position causally and
asks the user's question: if we only ENTER when the score beats the expected (mean) by a margin,
do we get fewer-but-better positions and a higher EV?

POSITION SCORE (causal, decision-time only): the fair-value model's estimated edge =
  score = fair_P(favorite) - ask
where fair_P(up) = Phi((S-K)/(sigma*sqrt(T))) from analysis.fairvalue.fair_up (sigma estimated
from the window's own Binance path UP TO the decision, so no look-ahead). score>0 = the model
thinks this favorite is UNDER-priced vs its ask. (This is also the A x H combination.)

Reports, per coin + pooled: baseline (all favorites), the LOW vs HIGH score tercile, and
score>=mean+margin for a few margins -- with win% and the honest n. One obs/window.

    python experiment_favtail_selectivity.py --coin all --min-ask 0.90 --tl 30
"""

import argparse
import sqlite3
import random

import coins
from analysis.fairvalue import fair_up


def load(coin, tl_target, min_ask, tol):
    rows = []   # (ws, ask, won, score)
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = conn.execute(
                "SELECT window_start, strike_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL "
                "ORDER BY window_start").fetchall()
        except sqlite3.OperationalError:
            conn.close(); continue
        for ws, strike, outcome in wins:
            snap = conn.execute(
                "SELECT up_ask, down_ask, price_binance, time_left FROM snapshots "
                "WHERE window_start=? AND price_binance IS NOT NULL AND up_ask IS NOT NULL "
                "AND down_ask IS NOT NULL ORDER BY ABS(time_left - ?) LIMIT 1",
                (ws, tl_target)).fetchone()
            if not snap:
                continue
            up_ask, dn_ask, px, tl = snap
            if abs(tl - tl_target) > tol:
                continue
            fav = "up" if px >= strike else "down"
            ask = up_ask if fav == "up" else dn_ask
            if ask is None or ask < min_ask or ask >= 1.0:
                continue
            fp = fair_up(conn, ws, tl)              # causal fair P(up) at this horizon
            if fp is None:
                continue
            fav_p = fp if fav == "up" else 1.0 - fp
            score = fav_p - ask                     # model-estimated underpricing of the favorite
            won = 1 if outcome == ("Up" if fav == "up" else "Down") else 0
            rows.append((ws, ask, won, score))
        conn.close()
    return rows


def ev_stats(rows, boot=3000, seed=1):
    n = len(rows)
    if n == 0:
        return None
    def fee(a):
        return 0.07 * a * (1.0 - a)
    per = [(w - a) / a - fee(a) / a for _, a, w, _ in rows]
    wr = sum(w for _, _, w, _ in rows) / n
    ev = sum(per) / n
    rng = random.Random(seed)
    draws = []
    for _ in range(boot):
        s = 0.0
        for _ in range(n):
            s += per[rng.randrange(n)]
        draws.append(s / n)
    draws.sort()
    return dict(n=n, wr=wr, ev=ev, lo=draws[int(0.025*len(draws))], hi=draws[int(0.975*len(draws))],
                nloss=sum(1 for _, _, w, _ in rows if w == 0))


def line(tag, s):
    if not s:
        print(f"    {tag:>16}  (no positions)"); return
    star = "*" if (s["lo"] > 0 or s["hi"] < 0) else " "
    print(f"    {tag:>16}  n={s['n']:>4} loss={s['nloss']:>3} win={100*s['wr']:>5.1f}%  "
          f"EV/$1 {s['ev']:>+7.4f}  [{s['lo']:+.4f},{s['hi']:+.4f}]{star}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="all")
    ap.add_argument("--min-ask", type=float, default=0.90, dest="min_ask")
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--tol", type=float, default=None)
    ap.add_argument("--margins", default="0.0,0.005,0.01",
                    help="enter only if score >= mean(score)+margin; comma list")
    args = ap.parse_args()
    tol = args.tol if args.tol is not None else max(3.0, 0.3 * args.tl)
    cl = list(coins.ENABLED) if args.coin == "all" else [args.coin]
    margins = [float(x) for x in args.margins.split(",")]

    print(f"FAVORITE-TAIL + SCORE-SELECTIVITY (independent test)  |  decision @ time_left~{args.tl:g}s "
          f"|  ask>= {args.min_ask:.2f}  |  score = fair_P(fav) - ask")
    pooled = []
    for c in cl:
        rows = load(c, args.tl, args.min_ask, tol)
        pooled += rows
        print(f"\n  === {c} ===")
        if not rows:
            print("    (no positions)"); continue
        line("baseline(all)", ev_stats(rows))
        sc = sorted(r[3] for r in rows)
        t = len(sc) // 3
        lo_cut, hi_cut = sc[t], sc[2 * t]
        line("LOW score 1/3", ev_stats([r for r in rows if r[3] <= lo_cut]))
        line("HIGH score 1/3", ev_stats([r for r in rows if r[3] >= hi_cut]))
        mean_s = sum(r[3] for r in rows) / len(rows)
        for m in margins:
            line(f"score>=mean+{m:g}", ev_stats([r for r in rows if r[3] >= mean_s + m]))
    if len(cl) > 1 and pooled:
        print(f"\n  === POOLED ===")
        line("baseline(all)", ev_stats(pooled))
        sc = sorted(r[3] for r in pooled)
        t = len(sc) // 3
        line("LOW score 1/3", ev_stats([r for r in pooled if r[3] <= sc[t]]))
        line("HIGH score 1/3", ev_stats([r for r in pooled if r[3] >= sc[2*t]]))
        mean_s = sum(r[3] for r in pooled) / len(pooled)
        for m in margins:
            line(f"score>=mean+{m:g}", ev_stats([r for r in pooled if r[3] >= mean_s + m]))
    print("\n  READ: if HIGH score 1/3 EV clearly beats LOW score 1/3, the score sorts winners and")
    print("  selectivity helps. If they're similar (both ~0, CIs overlap), the score is already in")
    print("  the ask (market calibrated) -> selectivity doesn't help. Watch n shrink with the margin.")
    print("  CAVEAT: 100%-win subsets have a zero-variance bootstrap CI (falsely *) -- judge by EV+n, "
          "not the star, in loss=0 rows.")


if __name__ == "__main__":
    main()

"""ADAPTIVE score-threshold for the favorite-tail (walk-forward, causal, OOS by construction).

User's refinement: the "exceed expectations" bar should NOT be a fixed number -- it should be
CALCULATED from the data when choosing signals, optimized for CONSISTENCY (not raw EV), and become
the new standard each refresh. Implemented honestly:

Base position (causal): at time_left~TL, buy the favorite (price vs strike) at its ask if ask>=MIN_ASK,
hold to 0/1, taker entry fee 0.07*a*(1-a). Score = fair_P(favorite) - ask (forward model edge;
fair_P from analysis.fairvalue, causal vol).

Walk-forward every 30 min: using ONLY past positions (< T), choose the score CUTOFF (over a grid of
past-score percentiles) that maximizes the WILSON LOWER BOUND of (win-rate - breakeven) -- the most
CONSISTENT cutoff, requiring >= MIN_N past positions (realistic coverage). Apply that cutoff to the
next 30 min of windows (out-of-sample). Step forward, repeat.

Compares, over the SAME OOS period: BASELINE (all favorites) vs ADAPTIVE (the chosen cutoff each
refresh) vs ORACLE (the single best in-sample fixed cutoff = overfit upper bound). Window-clustered
bootstrap CI; honest about loss=0 zero-variance subsets.

    python experiment_favtail_adaptive.py --coin all --min-ask 0.90 --tl 30 --warmup-h 8
"""

import argparse
import math
import sqlite3
import random

import coins
from analysis.fairvalue import fair_up

WINDOW = 300.0
REFRESH = 1800.0


def wilson_lb(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d


def fee(a):
    return 0.07 * a * (1.0 - a)


def net_per_dollar(ask, won):
    return (won - ask) / ask - fee(ask) / ask


def load_positions(coin, tl_target, min_ask, tol):
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
            fp = fair_up(conn, ws, tl)
            if fp is None:
                continue
            fav_p = fp if fav == "up" else 1.0 - fp
            won = 1 if outcome == ("Up" if fav == "up" else "Down") else 0
            rows.append((int(ws), ask, won, fav_p - ask))
        conn.close()
    rows.sort(key=lambda r: r[0])
    return rows


def best_cutoff(past, min_n):
    """Choose the score cutoff (a past-score percentile) maximizing Wilson-LB(win - breakeven).
    Returns the chosen cutoff (score threshold). -inf => trade all."""
    if len(past) < min_n:
        return float("-inf")
    scores = sorted(p[3] for p in past)
    cands = [float("-inf")] + [scores[int(q * len(scores))] for q in (0.2, 0.4, 0.6, 0.8)]
    best_c, best_edge = float("-inf"), -9.9
    for c in cands:
        sel = [p for p in past if p[3] >= c]
        n = len(sel)
        if n < min_n:
            continue
        k = sum(p[2] for p in sel)
        a = sum(p[1] for p in sel) / n
        be = a + fee(a)                       # breakeven win-rate (per share)
        edge = wilson_lb(k, n) - be           # consistency-penalized edge
        if edge > best_edge:
            best_edge, best_c = edge, c
    return best_c


def boot_ci(rows, boot=3000, seed=3):
    """window-clustered (here 1 obs/window already) bootstrap CI of net EV/$1."""
    n = len(rows)
    if n == 0:
        return None
    per = [net_per_dollar(a, w) for _, a, w, _ in rows]
    ev = sum(per) / n
    rng = random.Random(seed)
    draws = []
    for _ in range(boot):
        s = 0.0
        for _ in range(n):
            s += per[rng.randrange(n)]
        draws.append(s / n)
    draws.sort()
    return dict(n=n, ev=ev, wr=sum(w for _, _, w, _ in rows) / n,
                nloss=sum(1 for _, _, w, _ in rows if w == 0),
                lo=draws[int(0.025 * len(draws))], hi=draws[int(0.975 * len(draws))])


def walk(coin, tl, min_ask, tol, warmup_h, min_n):
    pos = load_positions(coin, tl, min_ask, tol)
    if len(pos) < 30:
        return None
    t0, t1 = pos[0][0], pos[-1][0]
    t_start = t0 + warmup_h * 3600
    base_oos, adapt_oos = [], []
    cutoffs = []
    T = t_start
    while T < t1 + WINDOW:
        past = [p for p in pos if p[0] < T]
        nxt = [p for p in pos if T <= p[0] < T + REFRESH]
        if nxt:
            c = best_cutoff(past, min_n)
            cutoffs.append(c)
            base_oos += nxt
            adapt_oos += [p for p in nxt if p[3] >= c]
        T += REFRESH
    # oracle: single best fixed cutoff over the WHOLE oos period (in-sample upper bound)
    oracle_c = best_cutoff(base_oos, min_n)
    oracle = [p for p in base_oos if p[3] >= oracle_c]
    finite = [c for c in cutoffs if c != float("-inf")]
    return dict(base=boot_ci(base_oos), adapt=boot_ci(adapt_oos), oracle=boot_ci(oracle),
                n_refresh=len(cutoffs), n_alltrade=sum(1 for c in cutoffs if c == float("-inf")),
                cut_mean=(sum(finite) / len(finite) if finite else None), n_finite=len(finite))


def show(coin, r):
    print(f"\n  === {coin} ===")
    if not r:
        print("    (too few positions)"); return
    def ln(tag, s):
        if not s:
            print(f"    {tag:>16}  (none)"); return
        star = "*" if (s["lo"] > 0 or s["hi"] < 0) else " "
        print(f"    {tag:>16}  n={s['n']:>4} loss={s['nloss']:>3} win={100*s['wr']:>5.1f}%  "
              f"EV/$1 {s['ev']:>+7.4f}  [{s['lo']:+.4f},{s['hi']:+.4f}]{star}")
    ln("BASELINE(all)", r["base"])
    ln("ADAPTIVE(OOS)", r["adapt"])
    ln("oracle(in-samp)", r["oracle"])
    cm = f"{r['cut_mean']:+.4f}" if r["cut_mean"] is not None else "n/a"
    print(f"    refreshes={r['n_refresh']}  chose 'trade-all' {r['n_alltrade']}x  "
          f"mean finite cutoff={cm}  (cutoff thrash = noise)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="all")
    ap.add_argument("--min-ask", type=float, default=0.90, dest="min_ask")
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--tol", type=float, default=None)
    ap.add_argument("--warmup-h", type=float, default=8.0, dest="warmup_h")
    ap.add_argument("--min-n", type=int, default=20, dest="min_n")
    args = ap.parse_args()
    tol = args.tol if args.tol is not None else max(3.0, 0.3 * args.tl)
    cl = list(coins.ENABLED) if args.coin == "all" else [args.coin]

    print(f"ADAPTIVE favorite-tail (walk-forward, OOS)  |  time_left~{args.tl:g}s  ask>= {args.min_ask:.2f}  "
          f"|  cutoff by Wilson-LB(win-breakeven), refit/30min, warmup {args.warmup_h:g}h, min_n {args.min_n}")
    agg = {"base": [], "adapt": [], "oracle": []}
    for c in cl:
        r = walk(c, args.tl, args.min_ask, tol, args.warmup_h, args.min_n)
        show(c, r)
    # pooled re-walk (concat OOS across coins by re-running and merging the raw rows)
    if len(cl) > 1:
        base_all, adapt_all, oracle_all = [], [], []
        for c in cl:
            pos = load_positions(c, args.tl, args.min_ask, tol)
            if len(pos) < 30:
                continue
            t0 = pos[0][0]; t_start = t0 + args.warmup_h * 3600; t1 = pos[-1][0]
            T = t_start
            while T < t1 + WINDOW:
                past = [p for p in pos if p[0] < T]
                nxt = [p for p in pos if T <= p[0] < T + REFRESH]
                if nxt:
                    cut = best_cutoff(past, args.min_n)
                    base_all += nxt
                    adapt_all += [p for p in nxt if p[3] >= cut]
                T += REFRESH
            oc = best_cutoff([p for p in pos if p[0] >= t_start], args.min_n)
            oracle_all += [p for p in pos if p[0] >= t_start and p[3] >= oc]
        print("\n  === POOLED (all coins) ===")
        def ln(tag, rows):
            s = boot_ci(rows)
            if not s:
                print(f"    {tag:>16}  (none)"); return
            star = "*" if (s["lo"] > 0 or s["hi"] < 0) else " "
            print(f"    {tag:>16}  n={s['n']:>4} loss={s['nloss']:>3} win={100*s['wr']:>5.1f}%  "
                  f"EV/$1 {s['ev']:>+7.4f}  [{s['lo']:+.4f},{s['hi']:+.4f}]{star}")
        ln("BASELINE(all)", base_all)
        ln("ADAPTIVE(OOS)", adapt_all)
        ln("oracle(in-samp)", oracle_all)
    print("\n  READ: ADAPTIVE beats BASELINE only if its EV is higher AND its CI clears 0 (and it")
    print("  shouldn't need the oracle's hindsight). If ADAPTIVE ~= BASELINE or worse, the data-chosen")
    print("  threshold tracks noise. loss=0 subsets have a degenerate CI -- judge by EV+n, not the *.")


if __name__ == "__main__":
    main()

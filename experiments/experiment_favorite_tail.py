"""Favorite-tail taker, HOLD-to-resolution — strictly CAUSAL backtest (no look-ahead).

Idea A's late-window favorite-buy, implemented exactly as a live bot could:
  At a fixed decision time (time_left ~ --tl), pick the FAVORITE side from the CURRENT
  Binance price vs the strike (both observable live), and if that side's ASK >= --min-ask,
  BUY 1 share at the ask as a TAKER (fee = 0.07*ask*(1-ask) per share) and HOLD to the
  official 0/1 resolution. NEVER taker-exit. Settlement is the bet result, never an input.

Causality: every decision input (price_binance, strike_binance, up_ask/down_ask, time_left)
is available at the decision instant; the script reads ONE snapshot per window chosen by
nearest time_left to --tl and uses nothing after it. The realized outcome is only used to
SCORE the bet, exactly as a live bot would learn it at resolution. One observation per window
(independence). Window-clustered bootstrap CI (per coin = iid over windows).

    python experiment_favorite_tail.py --coin btc --min-ask 0.90 --tl 30
    python experiment_favorite_tail.py --coin all --min-ask 0.95 --tl 10
"""

import argparse
import sqlite3
import random

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins


def load(coin, tl_target, min_ask, tol, min_gap_bps=0.0):
    rows = []   # (window_start, ask, won)
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
            if abs(tl - tl_target) > tol:          # need a snapshot near the decision time
                continue
            fav = "up" if px >= strike else "down"  # CAUSAL: current price vs strike
            gap_bps = (abs(px - strike) / px * 1e4) if px else 0.0   # idea-D basis-flip risk filter
            if gap_bps < min_gap_bps:               # too close to strike -> basis can flip -> skip
                continue
            ask = up_ask if fav == "up" else dn_ask
            if ask is None or ask < min_ask or ask >= 1.0:
                continue
            won = 1 if outcome == ("Up" if fav == "up" else "Down") else 0
            rows.append((ws, ask, won))
        conn.close()
    return rows


def summarize(rows, boot=4000, seed=1):
    """per-share net EV (after taker entry fee) + per-$1, win-rate, window-clustered CI."""
    n = len(rows)
    if n == 0:
        return None
    def fee(a):
        return 0.07 * a * (1.0 - a)
    net_share = [won - a - fee(a) for _, a, won in rows]          # profit per 1 share
    per_dollar = [(won - a) / a - fee(a) / a for _, a, won in rows]  # profit per $1 staked
    wr = sum(w for _, _, w in rows) / n
    n_loss = sum(1 for _, _, w in rows if w == 0)
    mean_ask = sum(a for _, a, _ in rows) / n
    ev_share = sum(net_share) / n
    ev_dollar = sum(per_dollar) / n
    rng = random.Random(seed)
    draws = []
    for _ in range(boot):
        s = 0.0
        for _ in range(n):
            s += per_dollar[rng.randrange(n)]
        draws.append(s / n)
    draws.sort()
    lo, hi = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))]
    return dict(n=n, wr=wr, n_loss=n_loss, mean_ask=mean_ask, ev_share=ev_share,
                ev_dollar=ev_dollar, lo=lo, hi=hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="all")
    ap.add_argument("--min-ask", type=float, default=0.90, dest="min_ask")
    ap.add_argument("--tl", type=float, default=30.0, help="decision time_left (s)")
    ap.add_argument("--tol", type=float, default=None, help="max |time_left-tl| (default max(3,0.3*tl))")
    ap.add_argument("--min-gap-bps", type=float, default=0.0, dest="min_gap_bps",
                    help="idea-D risk filter: require |price-strike|/price >= this many bps "
                         "(skip near-boundary windows where the Binance/Chainlink basis can flip)")
    args = ap.parse_args()
    tol = args.tol if args.tol is not None else max(3.0, 0.3 * args.tl)
    cl = list(coins.ENABLED) if args.coin == "all" else [args.coin]

    print(f"FAVORITE-TAIL taker, HOLD-to-resolution (CAUSAL)  |  decision @ time_left~{args.tl:g}s "
          f"(+-{tol:g}s)  |  buy favorite if ask>= {args.min_ask:.2f}  |  fee 0.07*a*(1-a) on entry"
          f"  |  D-filter: gap>= {args.min_gap_bps:g}bps")
    print(f"  {'coin':>5} {'n':>5} {'loss':>4} {'win%':>6} {'meanAsk':>8} {'EV/share':>9} {'EV/$1':>8} "
          f"{'95% CI/$1':>20}")
    pooled = []
    for c in cl:
        rows = load(c, args.tl, args.min_ask, tol, args.min_gap_bps)
        pooled += rows
        s = summarize(rows)
        if not s:
            print(f"  {c:>5}  (no qualifying windows)"); continue
        star = "*" if (s["lo"] > 0 or s["hi"] < 0) else " "
        print(f"  {c:>5} {s['n']:>5} {s['n_loss']:>4} {100*s['wr']:>5.1f}% {s['mean_ask']:>8.3f} "
              f"{s['ev_share']:>+9.4f} {s['ev_dollar']:>+8.4f} "
              f"{f'[{s[chr(108)+chr(111)]:+.4f},{s[chr(104)+chr(105)]:+.4f}]':>19}{star}")
    if len(cl) > 1:
        # pooled, clustered by window_start (same-time windows across coins are correlated)
        by = {}
        for ws, a, w in pooled:
            by.setdefault(ws, []).append((a, w))
        def fee(a):
            return 0.07 * a * (1 - a)
        flat = [( (w - a) / a - fee(a) / a) for ws, a, w in pooled]
        n = len(pooled)
        ev = sum(flat) / n
        wr = sum(w for _, _, w in pooled) / n
        keys = list(by)
        rng = random.Random(7)
        draws = []
        for _ in range(4000):
            sp = sn = 0.0
            for _ in range(len(keys)):
                for a, w in by[keys[rng.randrange(len(keys))]]:
                    sp += (w - a) / a - fee(a) / a; sn += 1
            draws.append(sp / sn)
        draws.sort()
        lo, hi = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))]
        star = "*" if (lo > 0 or hi < 0) else " "
        print(f"  {'POOL':>5} {n:>5} {100*wr:>5.1f}% {'':>8} {'':>9} {ev:>+8.4f} "
              f"{f'[{lo:+.4f},{hi:+.4f}]':>19}{star}  (time-clustered)")
    print("  CAUSAL: favorite = current Binance px vs strike; ask = live; outcome only scores. "
          "EV/$1 net of the taker entry fee. * = CI excludes 0.")


if __name__ == "__main__":
    main()

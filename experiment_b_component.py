"""Idea B as a COMPONENT on the favorite-tail: a forward cross-asset (BTC->alt) underpricing gate.

NOT a standalone strategy. The favorite-tail is breakeven because each alt's own quote already prices
its own move (intra-asset efficient). The one real signal is LATENCY (BTC leads ~1s, sign-consistent),
dead intra-asset. This routes it CROSS-ASSET: at the alt favorite-tail decision instant, use BTC's
just-realized move to predict whether the alt favorite is UNDER-priced by its own (laggy) quote.

CAUSAL. For each ALT (btc excluded = the leader), at time_left~TL, the base position is: favorite =
(alt_price >= alt_strike), buy its ask if ask>=MIN_ASK, hold to 0/1. The B SIGNAL at that instant:
  btc_sig = sign_fav * (BTC return over last L s)        # BTC confirms the favorite's direction
  gap_sig = sign_fav * (BTC return - alt return, last L) # alt is LAGGING BTC toward the favorite
where sign_fav = +1 if favorite is Up else -1. All inputs known at the decision; outcome only scores.

STEP 1 (existence / Part 3 -- the decider): corr(signal, residual = won - ask) per alt + pooled,
time-clustered bootstrap CI. >0 with CI excluding 0 = the alt quote does NOT fully price BTC's lead
=> a real unpriced cross-asset margin => proceed to gate it. ~0 => dead, like every other component.
STEP 2 (gate): if positive, sweep a signal threshold; gated favorite-tail EV vs baseline, Wilson-LB.

    python experiment_b_component.py --tl 30 --min-ask 0.90
"""

import argparse
import math
import bisect
import random
import sqlite3

import coins


def load_persec(coin, hours):
    out = {}
    import time as _t
    cutoff = 0
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            for ts, px in conn.execute(
                    "SELECT ts, price_binance FROM snapshots WHERE price_binance IS NOT NULL "
                    "ORDER BY ts"):
                out[int(ts)] = px
        except sqlite3.OperationalError:
            pass
        conn.close()
    return out


class Series:
    def __init__(self, d):
        self.keys = sorted(d)
        self.d = d
    def at(self, t):
        i = bisect.bisect_right(self.keys, t) - 1
        return self.d[self.keys[i]] if i >= 0 else None


def load_alt_positions(coin, tl_target, min_ask, tol):
    rows = []   # (ws, t_decision, ask, sign_fav, won)
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
            sign = 1.0 if fav == "up" else -1.0
            won = 1 if outcome == ("Up" if fav == "up" else "Down") else 0
            t = int(ws) + (300 - tl)
            rows.append((int(ws), t, ask, sign, won))
        conn.close()
    return rows


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def boot_corr_clustered(items, B=3000, seed=5):
    """items: list of (cluster_key, x, y). resample clusters; corr of pooled."""
    by = {}
    for k, x, y in items:
        by.setdefault(k, []).append((x, y))
    keys = list(by)
    r = pearson([it[1] for it in items], [it[2] for it in items])
    if r is None:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(B):
        xs, ys = [], []
        for _ in range(len(keys)):
            for x, y in by[keys[rng.randrange(len(keys))]]:
                xs.append(x); ys.append(y)
        rr = pearson(xs, ys)
        if rr is not None:
            draws.append(rr)
    draws.sort()
    return r, draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--min-ask", type=float, default=0.90, dest="min_ask")
    ap.add_argument("--tol", type=float, default=None)
    ap.add_argument("--lookbacks", default="5,15,30", help="BTC move lookback seconds")
    ap.add_argument("--hours", type=float, default=200.0)
    args = ap.parse_args()
    tol = args.tol if args.tol is not None else max(3.0, 0.3 * args.tl)
    Ls = [int(x) for x in args.lookbacks.split(",")]
    alts = [c for c in coins.ENABLED if c != "btc"]

    print("Loading BTC + alt per-second price ...", flush=True)
    btc = Series(load_persec("btc", args.hours))
    altpx = {c: Series(load_persec(c, args.hours)) for c in alts}

    # build per-position signals
    data = {c: [] for c in alts}   # coin -> list of (ws, ask, sign, won, {(sig,L): value})
    for c in alts:
        for ws, t, ask, sign, won in load_alt_positions(c, args.tl, args.min_ask, tol):
            sigs = {}
            ok = True
            for L in Ls:
                b1 = btc.at(t); b0 = btc.at(t - L)
                a1 = altpx[c].at(t); a0 = altpx[c].at(t - L)
                if not (b1 and b0 and a1 and a0) or b0 <= 0 or a0 <= 0:
                    ok = False; break
                br = b1 / b0 - 1.0
                ar = a1 / a0 - 1.0
                sigs[("btc", L)] = sign * br
                sigs[("gap", L)] = sign * (br - ar)
            if ok:
                data[c].append((ws, ask, sign, won, sigs))

    print(f"\nFAVORITE-TAIL + BTC->alt FORWARD GATE (component test)  |  time_left~{args.tl:g}s, "
          f"ask>= {args.min_ask:.2f}, alts={','.join(alts)}")
    for c in alts:
        print(f"  {c}: {len(data[c])} positions")

    # ---- STEP 1: existence -- corr(signal, residual=won-ask) ----
    print("\n(1) EXISTENCE -- corr(signal, residual = won - ask)  [>0 = BTC move predicts the alt")
    print("    favorite beyond its ask = UNPRICED cross-asset margin].  * = 95% CI excludes 0.")
    for kind in ("btc", "gap"):
        for L in Ls:
            pooled_items = []   # (ws, signal, residual) clustered by ws
            percoin = {}
            for c in alts:
                xs, ys = [], []
                for ws, ask, sign, won, sigs in data[c]:
                    s = sigs.get((kind, L))
                    if s is None:
                        continue
                    resid = won - ask
                    xs.append(s); ys.append(resid)
                    pooled_items.append((ws, s, resid))
                percoin[c] = pearson(xs, ys)
            res = boot_corr_clustered(pooled_items)
            if not res:
                continue
            r, lo, hi = res
            star = "*" if (lo > 0 or hi < 0) else " "
            pc = " ".join(f"{c}:{(f'{percoin[c]:+.2f}' if percoin[c] is not None else 'na')}" for c in alts)
            print(f"    {kind}/{L:>2}s  pooled r={r:+.3f} [{lo:+.3f},{hi:+.3f}]{star}   per-coin {pc}")

    # ---- STEP 2: gate sweep for the strongest a-priori signal (btc/5s) ----
    print("\n(2) GATE -- enter alt favorite-tail only when signal>=thr; net EV/$1 vs baseline.")
    def fee(a):
        return 0.07 * a * (1 - a)
    def evstats(rows):
        if not rows:
            return None
        per = [(w - a) / a - fee(a) / a for a, w in rows]
        n = len(per); wr = sum(w for _, w in rows) / n
        return n, wr, sum(per) / n, sum(1 for _, w in rows if w == 0)
    for kind, L in (("btc", 5), ("gap", 15)):
        print(f"  signal = {kind}/{L}s:")
        allrows = [(ask, won) for c in alts for (ws, ask, sign, won, sg) in data[c] if sg.get((kind, L)) is not None]
        b = evstats(allrows)
        if b:
            print(f"    {'baseline(all)':>18}  n={b[0]:>4} loss={b[3]:>3} win={100*b[1]:>5.1f}%  EV/$1 {b[2]:>+7.4f}")
        svals = sorted(sg[(kind, L)] for c in alts for (_, _, _, _, sg) in data[c] if sg.get((kind, L)) is not None)
        for q in (0.3, 0.5, 0.7):
            thr = svals[int(q * len(svals))]
            rows = [(ask, won) for c in alts for (ws, ask, sign, won, sg) in data[c]
                    if sg.get((kind, L)) is not None and sg[(kind, L)] >= thr]
            s = evstats(rows)
            if s:
                print(f"    signal>=q{int(q*100):>2}({thr:+.4f})  n={s[0]:>4} loss={s[3]:>3} win={100*s[1]:>5.1f}%  EV/$1 {s[2]:>+7.4f}")
    print("\n  READ: gate is real only if STEP-1 pooled corr excludes 0 AND replicates per-coin AND the")
    print("  gated EV beats baseline net of fee with a Wilson-LB(win)>breakeven (loss=0 subsets = artifact).")
    print("  If STEP-1 ~0, BTC's move is already in the alt ask -> B-as-component is dead too.")


if __name__ == "__main__":
    main()

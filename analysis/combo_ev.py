"""Combo EV scan — find statistically-profitable entry conditions, measured honestly.

Your approach, done with PROPER expected value. For a grid of combos
  (entry-price bucket z, time-left >= , spread/gap <= , exit rule)
it buys the token at z and computes the realized return-on-stake per entry:

  exit = target sell at z+delta:
        hit target before close      -> return = (target - z) / z
        miss, hold to resolution     -> return = (payout - z) / z   (payout 1 if won else 0)
  exit = hold to resolution (delta=None):
        return = (payout - z) / z

EV = mean return-on-stake over all entries in the combo. EV > 0 = profitable
(before fees). Also reports the breakdown hit / miss-but-won / miss-and-lost, so
you can see your insight directly: the best combos hit the target OR are cushioned
by a favorable resolution (low miss-and-lost %).

THE PART THAT MATTERS: it then splits windows by time (train/test) and checks
whether the best in-sample combo still makes money out-of-sample. A combo that
only wins in-sample is overfit (we test ~100+ combos, so the best is luck by
default -- see DATA-ANALYSIS-TOOLKIT.md).

    python -m analysis.combo_ev [--min-n 12 --fee 0.0]

CAVEATS: mid-based, unconditional-on-fill -> OPTIMISTIC (a real fill model only
lowers EV via adverse selection; see STRATEGY-MEAN-REVERSION.md). Reach rates
above ~0.5 are martingale-ceiling artifacts, not edges.
"""

import argparse

from . import panel

Z_BUCKETS = [(0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 0.30),
             (0.30, 0.35), (0.35, 0.40), (0.40, 0.45)]
MIN_LEFTS = [120.0, 180.0, 240.0]
SPREADS = [None, 0.02]
TARGET_DELTAS = [0.05, 0.10, 0.15, None]   # None = hold to resolution


def load_paths(conn):
    out = []
    windows = conn.execute(
        "SELECT window_start, resolved_outcome FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start").fetchall()
    for ws, outcome in windows:
        rows = conn.execute(
            "SELECT time_left, up_mid, down_mid, up_bid, up_ask, down_bid, down_ask "
            "FROM snapshots WHERE window_start=? AND up_mid IS NOT NULL ORDER BY ts",
            (ws,)).fetchall()
        if not rows:
            continue
        up, dn = [], []
        for tl, um, dm, ub, ua, db, da in rows:
            up.append((tl, um, (ua - ub) if (ua is not None and ub is not None) else None))
            if dm is not None:
                dn.append((tl, dm, (da - db) if (da is not None and db is not None) else None))
        out.append((ws, up, outcome == "Up"))
        out.append((ws, dn, outcome == "Down"))
    return out


def simulate(path, won, zlo, zhi, min_left, max_spread, delta, fee):
    """Return (ret_on_stake, category) for the first matching entry, else (None,None)."""
    z = None
    idx = None
    for i, (tl, mid, sp) in enumerate(path):
        if (zlo <= mid < zhi and tl >= min_left and
                (max_spread is None or (sp is not None and sp <= max_spread))):
            z, idx = mid, i
            break
    if z is None or z <= 0:
        return None, None
    payout = 1.0 if won else 0.0
    if delta is None:
        return (payout - z) / z - fee, ("res_win" if won else "res_lose")
    target = z + delta
    if target >= 1.0:
        return None, None
    for tl, mid, sp in path[idx + 1:]:
        if mid >= target:
            return (target - z) / z - fee, "hit"
    return (payout - z) / z - fee, ("miss_win" if won else "miss_lose")


def scan(paths, zlo, zhi, min_left, max_spread, delta, fee):
    n = 0
    sret = 0.0
    cats = {}
    for ws, path, won in paths:
        r, c = simulate(path, won, zlo, zhi, min_left, max_spread, delta, fee)
        if r is None:
            continue
        n += 1
        sret += r
        cats[c] = cats.get(c, 0) + 1
    return n, sret, cats


def combos():
    for (zlo, zhi) in Z_BUCKETS:
        for ml in MIN_LEFTS:
            for ms in SPREADS:
                for d in TARGET_DELTAS:
                    yield (zlo, zhi, ml, ms, d)


def label(zlo, zhi, ml, ms, d):
    sp = "any" if ms is None else f"{ms:.2f}"
    ex = "resolve" if d is None else f"+{d:.2f}"
    return f"z[{zlo:.2f},{zhi:.2f}) tL>={ml:.0f} sp<={sp} exit {ex}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=12)
    ap.add_argument("--fee", type=float, default=0.0,
                    help="round-trip fee as fraction of stake, subtracted per trade")
    args = ap.parse_args()

    conn = panel.connect()
    paths = load_paths(conn)
    n_windows = len(set(p[0] for p in paths))
    all_combos = list(combos())

    print(f"Combo EV scan  |  {n_windows} settled windows, {len(paths)} window-sides  |  "
          f"{len(all_combos)} combos tested  |  fee {args.fee:.3f}")
    print("(EV = mean return-on-stake; >0 = profitable. Many combos -> best is likely luck;")
    print(" the TRAIN/TEST block at the bottom is the real verdict.)\n")

    scored = []
    for (zlo, zhi, ml, ms, d) in all_combos:
        n, sret, cats = scan(paths, zlo, zhi, ml, ms, d, args.fee)
        if n >= args.min_n:
            scored.append((sret / n, n, cats, (zlo, zhi, ml, ms, d)))
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"  {'EV':>7} {'n':>4}  {'hit%':>5} {'missW%':>6} {'lose%':>6}  combo")
    for ev, n, cats, key in scored[:15]:
        hit = 100 * cats.get("hit", 0) / n
        missw = 100 * (cats.get("miss_win", 0) + cats.get("res_win", 0)) / n
        lose = 100 * (cats.get("miss_lose", 0) + cats.get("res_lose", 0)) / n
        print(f"  {ev:>+7.3f} {n:>4}  {hit:>5.0f} {missw:>6.0f} {lose:>6.0f}  {label(*key)}")
    if not scored:
        print("  no combo reached min-n yet — collect more or lower --min-n.")
        conn.close()
        return

    # --- the honest verdict: out-of-sample -----------------------------------
    ws_sorted = sorted(set(p[0] for p in paths))
    print("\n  --- TRAIN/TEST (the only result that matters) ---")
    if len(ws_sorted) < 12:
        print("  need >= 12 settled windows for a split.")
        conn.close()
        return
    cut = ws_sorted[len(ws_sorted) // 2]
    train = [p for p in paths if p[0] < cut]
    test = [p for p in paths if p[0] >= cut]
    best = None
    for (zlo, zhi, ml, ms, d) in all_combos:
        n, sret, _ = scan(train, zlo, zhi, ml, ms, d, args.fee)
        if n >= max(6, args.min_n // 2):
            ev = sret / n
            if best is None or ev > best[0]:
                best = (ev, n, (zlo, zhi, ml, ms, d))
    if not best:
        print("  not enough train entries for any combo.")
        conn.close()
        return
    ev_tr, n_tr, key = best
    n_te, sret_te, _ = scan(test, *key, args.fee)
    print(f"  best in-sample: {label(*key)}")
    print(f"    train EV {ev_tr:+.3f} (n={n_tr})")
    if n_te == 0:
        print(f"    test: no entries (n=0) -> inconclusive (combo too rare)")
    else:
        ev_te = sret_te / n_te
        verdict = "HOLDS out-of-sample (promising; needs more data + fills)" if ev_te > 0 \
                  else "FAILS out-of-sample -> overfit, not a real edge"
        print(f"    test  EV {ev_te:+.3f} (n={n_te})  ->  {verdict}")
    print("\n  Next: re-run with --fee set to the real round-trip fee, then add a fill")
    print("  model (adverse selection) before trusting any positive number.")
    conn.close()


if __name__ == "__main__":
    main()

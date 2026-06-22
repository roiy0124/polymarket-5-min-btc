"""Does a FASTER BTC feed buy an edge, and WHEN is it biggest? (experiment)

The hypothesis (the user's): Polymarket's quote lags real BTC by ~1-3s. A bot that
sees BTC sooner can TAKE the stale quote before it reprices. This is the structurally
sound "fair-value taker" idea -- the opposite of the passive resting-limit strategies
we ruled out (those are SHORT the option to informed flow; a taker is LONG it).

This script answers the two still-open questions, with statistical rigor:

  Q1. HOW MUCH does real-time price help?  -- the value of feed speed.
  Q2. WHEN is it best to trade?            -- time-of-day and the vol regime behind it.

Three measurements:

  (A) LEAD-LAG cross-correlation (structural, no trading assumptions):
      corr( BTC 1s return , Polymarket Up-mid return shifted by lag L ). A peak at L>0
      means BTC LEADS Polymarket by L sec -- that peak lag is how much "seeing BTC ahead"
      is worth. Peak at L<=0 => the quote already reflects BTC, no feed edge.

  (B) FEED-LEAD VALUE (Q1): a clairvoyant taker reads BTC at t+DELTA, and if the
      BTC-implied fair P beats the current ASK by --edge it TAKES. Two exits, both costed:
        * taker  (bid)  -- sell at the BID --exit-lag s later (cross the spread; pessimistic)
        * maker  (mid)  -- exit at the MID (rest a limit at the repriced fair; optimistic)
      The realistic EV sits BETWEEN these. We sweep DELTA in {0,.5,1,2,3}s; **DELTA=0 is the
      control** (no feed advantage). The LIFT from DELTA=0, with a window-clustered bootstrap
      CI on the DIFFERENCE, is the value of feed speed. Climbs with DELTA => a faster feed
      converts to edge, and we've quantified how much per second.

  (C) WHEN (Q2): the same fills bucketed by 3h UTC window and by BTC-volatility tercile,
      EV with clustered-bootstrap CIs. Time-of-day was UNSTABLE for the passive strategy,
      but for a TAKER there's a real mechanism -- the edge needs BTC to MOVE, so it should
      concentrate in high-vol hours. We test that directly.

Reads btc_updown.db + old_dbs/*.db (per-DB; windows disjoint). Sub-second BTC from
btc_ticks (~50-85/s); taker prices from 1Hz snapshots. Stdlib only.

    python experiment_lookahead_taker.py
    python experiment_lookahead_taker.py --edge 0.04 --exit-lag 1 --lead 1

*** Caveats: clairvoyant DELTA is an UPPER BOUND (zero feed latency, no race for the stale
quote) -- a real bot captures a fraction. CIs are clustered BY WINDOW (fills within a window
aren't independent) but ~590 windows / a few days is still thin -- confirm over weeks. sigma
is a Binance proxy, not the Chainlink settlement. This says whether the edge is THERE and
WHEN, not that you'll capture all of it. ***
"""

import os
import glob
import math
import bisect
import random
import argparse
import sqlite3
from time import gmtime

from analysis.fairvalue import phi

WINDOW = 300.0


def db_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    live = os.path.join(here, "btc_updown.db")
    if os.path.exists(live):
        paths.append(live)
    paths += sorted(glob.glob(os.path.join(here, "old_dbs", "*.db")))
    return paths


def load_windows(conn):
    rows = conn.execute(
        "SELECT window_start, strike_binance, "
        "COALESCE(resolved_outcome, our_outcome) AS outcome "
        "FROM windows WHERE strike_binance IS NOT NULL "
        "AND COALESCE(resolved_outcome, our_outcome) IS NOT NULL "
        "ORDER BY window_start").fetchall()
    return [(int(r[0]), float(r[1]), r[2]) for r in rows]


def nearest(ts_arr, val_arr, u):
    """value sampled at time u (nearest neighbour) from a time-sorted series; may be None."""
    i = bisect.bisect_left(ts_arr, u)
    if i <= 0:
        return val_arr[0]
    if i >= len(ts_arr):
        return val_arr[-1]
    return val_arr[i] if (ts_arr[i] - u) < (u - ts_arr[i - 1]) else val_arr[i - 1]


class Pearson:
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")

    def __init__(self):
        self.n = self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0

    def add(self, x, y):
        self.n += 1
        self.sx += x; self.sy += y
        self.sxx += x * x; self.syy += y * y; self.sxy += x * y

    def r(self):
        n = self.n
        if n < 3:
            return None
        cov = self.sxy - self.sx * self.sy / n
        vx = self.sxx - self.sx * self.sx / n
        vy = self.syy - self.sy * self.sy / n
        if vx <= 0 or vy <= 0:
            return None
        return cov / math.sqrt(vx * vy)


def boot_ev(ws_list, agg, B, seed):
    """pooled EV per fill over windows in ws_list, with a window-clustered bootstrap CI.
    agg: ws -> (sum_roi, n). Returns (ev, lo, hi, n_fills) or None."""
    pairs = [agg.get(w, (0.0, 0)) for w in ws_list]
    K = len(pairs)
    tot_r = sum(p[0] for p in pairs)
    tot_n = sum(p[1] for p in pairs)
    if K == 0 or tot_n == 0:
        return None
    ev = tot_r / tot_n
    rng = random.Random(seed)
    draws = []
    for _ in range(B):
        sr = sn = 0.0
        for _ in range(K):
            p = pairs[rng.randrange(K)]
            sr += p[0]; sn += p[1]
        if sn > 0:
            draws.append(sr / sn)
    draws.sort()
    return (ev, draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))], int(tot_n))


def boot_diff(ws_list, aggA, aggB, B, seed):
    """clustered-bootstrap CI of EV(A) - EV(B) over the SAME resampled windows (paired)."""
    A = [aggA.get(w, (0.0, 0)) for w in ws_list]
    Bp = [aggB.get(w, (0.0, 0)) for w in ws_list]
    K = len(ws_list)
    if K == 0:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(B):
        ar = an = br = bn = 0.0
        for _ in range(K):
            j = rng.randrange(K)
            ar += A[j][0]; an += A[j][1]
            br += Bp[j][0]; bn += Bp[j][1]
        if an > 0 and bn > 0:
            draws.append(ar / an - br / bn)
    if not draws:
        return None
    draws.sort()
    return (draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deltas", default="0,0.5,1,2,3",
                    help="look-ahead seconds to sweep (DELTA=0 = no-advantage control)")
    ap.add_argument("--edge", type=float, default=0.02,
                    help="trade only if fair(look-ahead) - ask >= edge")
    ap.add_argument("--exit-lag", type=float, default=2.0, dest="exit_lag",
                    help="exit this many seconds after entry (bid for taker, mid for maker)")
    ap.add_argument("--stride", type=float, default=5.0,
                    help="seconds between decision points within a window")
    ap.add_argument("--tau-min", type=float, default=15.0, dest="tau_min")
    ap.add_argument("--tau-max", type=float, default=270.0, dest="tau_max")
    ap.add_argument("--max-ask", type=float, default=0.95, dest="max_ask")
    ap.add_argument("--fee-bps", type=float, default=0.0, dest="fee_bps")
    ap.add_argument("--lead", type=float, default=1.0,
                    help="which DELTA to use for the WHEN breakdowns (the realistic lead)")
    ap.add_argument("--boot", type=int, default=1500, help="bootstrap iterations")
    ap.add_argument("--lag-range", type=int, default=4, dest="lag_range")
    args = ap.parse_args()

    deltas = [float(x) for x in args.deltas.split(",")]
    fee = args.fee_bps / 1e4
    paths = db_paths()
    if not paths:
        print("no DB found"); return

    lags = list(range(-args.lag_range, args.lag_range + 1))
    lagacc = {L: Pearson() for L in lags}

    # flat fill records: (delta, ws, hour, vol, roi_bid|None, roi_mid|None)
    recs = []
    win_meta = {}    # ws -> (hour, vol)
    n_windows = n_dbs = 0

    for path in paths:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        wins = load_windows(conn)
        if not wins:
            conn.close(); continue
        n_dbs += 1
        for ws, K, outcome in wins:
            snaps = conn.execute(
                "SELECT ts, time_left, up_bid, up_ask, down_bid, down_ask, btc_binance "
                "FROM snapshots WHERE window_start=? AND btc_binance IS NOT NULL "
                "AND up_ask IS NOT NULL ORDER BY ts", (ws,)).fetchall()
            if len(snaps) < 12:
                continue
            ticks = conn.execute(
                "SELECT recv_ts, mid FROM btc_ticks WHERE recv_ts>=? AND recv_ts<=? "
                "AND mid IS NOT NULL ORDER BY recv_ts", (ws - 2, ws + WINDOW + 5)).fetchall()
            if len(ticks) < 50:
                continue
            n_windows += 1
            t_ts = [r[0] for r in ticks]
            t_mid = [r[1] for r in ticks]
            s_ts = [r[0] for r in snaps]
            btc = [r[6] for r in snaps]
            up_mid = [((r[2] + r[3]) / 2.0) if (r[2] is not None and r[3] is not None)
                      else None for r in snaps]
            dn_mid = [((r[4] + r[5]) / 2.0) if (r[4] is not None and r[5] is not None)
                      else None for r in snaps]
            up_bid_arr = [r[2] for r in snaps]
            dn_bid_arr = [r[4] for r in snaps]

            # ---- (A) lead-lag cross-correlation ----
            for i in range(1, len(snaps)):
                dbtc = btc[i] - btc[i - 1]
                if dbtc == 0:
                    continue
                for L in lags:
                    j = i + L
                    if 0 < j < len(snaps) and up_mid[j] is not None and up_mid[j - 1] is not None:
                        lagacc[L].add(dbtc, up_mid[j] - up_mid[j - 1])

            # ---- per-window vol (realized, full window) + hour ----
            diffs = [btc[k + 1] - btc[k] for k in range(len(btc) - 1)]
            if len(diffs) >= 6:
                md = sum(diffs) / len(diffs)
                vol = math.sqrt(sum((x - md) ** 2 for x in diffs) / (len(diffs) - 1))
            else:
                vol = 0.0
            hour = gmtime(ws).tm_hour
            win_meta[ws] = (hour, vol)

            # ---- (B/C) lookahead-taker sim ----
            last_dec = -1e9
            for i in range(8, len(snaps)):
                ts_i, tau = snaps[i][0], snaps[i][1]
                if tau is None or not (args.tau_min <= tau <= args.tau_max):
                    continue
                if ts_i - last_dec < args.stride:
                    continue
                d_so_far = diffs[:i]
                if len(d_so_far) < 6:
                    continue
                m = sum(d_so_far) / len(d_so_far)
                var = sum((x - m) ** 2 for x in d_so_far) / (len(d_so_far) - 1)
                sig = math.sqrt(var)
                if sig <= 1e-9:
                    continue
                move_std = sig * math.sqrt(max(1.0, tau))
                up_ask_i, dn_ask_i = snaps[i][3], snaps[i][5]
                up_bid_i, dn_bid_i = snaps[i][2], snaps[i][4]
                last_dec = ts_i
                for d in deltas:
                    S_ahead = nearest(t_ts, t_mid, ts_i + d)
                    fair_up = phi((S_ahead - K) / move_std)
                    up_e = fair_up - up_ask_i if (up_ask_i and up_ask_i < args.max_ask) else -9
                    dn_e = (1.0 - fair_up) - dn_ask_i if (dn_ask_i and dn_ask_i < args.max_ask) else -9
                    if max(up_e, dn_e) < args.edge:
                        continue
                    if up_e >= dn_e:
                        ask, bid_now = up_ask_i, up_bid_i
                        bid_arr, mid_arr = up_bid_arr, up_mid
                    else:
                        ask, bid_now = dn_ask_i, dn_bid_i
                        bid_arr, mid_arr = dn_bid_arr, dn_mid
                    if not ask or ask <= 0:
                        continue
                    bid_exit = nearest(s_ts, bid_arr, ts_i + args.exit_lag)
                    mid_exit = nearest(s_ts, mid_arr, ts_i + args.exit_lag)
                    roi_bid = (bid_exit - ask) / ask - fee if (bid_now is not None and bid_exit) else None
                    roi_mid = (mid_exit - ask) / ask - fee if mid_exit else None
                    recs.append((d, ws, hour, vol, roi_bid, roi_mid))
        conn.close()

    # ---------- aggregates: agg[(delta, exit)] : ws -> [sum_roi, n] ----------
    def build_agg(delta, which, subset=None):
        idx = 4 if which == "bid" else 5
        agg = {}
        for r in recs:
            if r[0] != delta:
                continue
            if subset is not None and r[1] not in subset:
                continue
            v = r[idx]
            if v is None:
                continue
            a = agg.get(r[1])
            if a is None:
                agg[r[1]] = [v, 1]
            else:
                a[0] += v; a[1] += 1
        return {w: (a[0], a[1]) for w, a in agg.items()}

    traded_ws = sorted({r[1] for r in recs})
    pick = min(deltas, key=lambda d: abs(d - args.lead))   # delta used for breakdowns

    # ---------- report ----------
    print("=" * 78)
    print("FASTER-FEED EDGE  --  Q1: how much does real-time help?   Q2: best times?")
    print("=" * 78)
    print(f"data: {n_dbs} db(s), {n_windows} windows w/ strike+ticks+quotes; "
          f"edge>={args.edge:.2f}, exit-lag={args.exit_lag:g}s, stride={args.stride:g}s, "
          f"fee={args.fee_bps:g}bps, boot={args.boot}\n")

    # (A) lead-lag
    print("(A) LEAD-LAG  corr(BTC 1s return, Up-mid return @ lag L)  -- L>0 => BTC leads")
    rows = [(L, lagacc[L].r()) for L in lags]
    best = max((rr for rr in rows if rr[1] is not None), key=lambda rr: rr[1], default=None)
    for L, r in rows:
        bar = (("+" if r >= 0 else "-") * min(40, int(abs(r) * 400))) if r is not None else ""
        star = "  <== peak" if best and L == best[0] else ""
        print(f"    L={L:+d}s  r={(f'{r:+.4f}' if r is not None else ' n/a')}  {bar}{star}")
    if best:
        msg = (f"BTC LEADS Polymarket by ~{best[0]}s -> a faster feed has something to bite"
               if best[0] > 0 and (best[1] or 0) > 0
               else f"peak at L={best[0]} (<=0): quote already tracks BTC; little feed edge")
        print(f"  -> {msg}\n")

    # (B) Q1: feed-lead value
    print("(B) Q1 -- VALUE OF REAL-TIME  (EV/$1 per fill; 95% CI clustered by window)")
    print("    DELTA=0 = no feed advantage.  'lift' = EV(DELTA) - EV(DELTA=0), paired CI.")
    print(f"    {'DELTA':>6} | {'n':>6} | {'taker(bid) EV [95% CI]':>30} | "
          f"{'maker(mid) EV [95% CI]':>30}")
    agg0_bid = build_agg(0.0, "bid") if 0.0 in deltas else None
    agg0_mid = build_agg(0.0, "mid") if 0.0 in deltas else None
    for d in deltas:
        ab = build_agg(d, "bid"); am = build_agg(d, "mid")
        rb = boot_ev(traded_ws, ab, args.boot, 1001)
        rm = boot_ev(traded_ws, am, args.boot, 2002)
        if not rb:
            print(f"    {d:>6g} |   no fills"); continue
        nb = rb[3]
        sb = f"{rb[0]:+.3f} [{rb[1]:+.3f},{rb[2]:+.3f}]"
        sm = f"{rm[0]:+.3f} [{rm[1]:+.3f},{rm[2]:+.3f}]" if rm else "n/a"
        print(f"    {d:>6g} | {nb:>6} | {sb:>30} | {sm:>30}")
    # explicit lift table vs the control
    if 0.0 in deltas:
        print("\n    feed-speed LIFT vs DELTA=0 (95% CI on the difference; excludes 0 => real):")
        for d in deltas:
            if d == 0.0:
                continue
            db = boot_diff(traded_ws, build_agg(d, "bid"), agg0_bid, args.boot, 3003)
            dm = boot_diff(traded_ws, build_agg(d, "mid"), agg0_mid, args.boot, 4004)
            def fmt(x):
                if not x:
                    return "n/a"
                star = "*" if (x[0] > 0 or x[1] < 0) else " "
                return f"[{x[0]:+.3f},{x[1]:+.3f}]{star}"
            print(f"      +{d:g}s lead:  taker {fmt(db):>20}   maker {fmt(dm):>20}")
    print()

    # (C) Q2: when -- by hour and by vol
    def bucket_table(title, label_fn, buckets):
        print(title)
        print(f"    {'bucket':>16} | {'n':>5} | {'taker(bid) EV [95% CI]':>30} | "
              f"{'maker(mid) EV [95% CI]':>30}")
        for key, ws_sub in buckets:
            ab = build_agg(pick, "bid", subset=ws_sub)
            am = build_agg(pick, "mid", subset=ws_sub)
            rb = boot_ev(list(ws_sub), ab, args.boot, 5005)
            rm = boot_ev(list(ws_sub), am, args.boot, 6006)
            if not rb:
                print(f"    {label_fn(key):>16} |   (too few)"); continue
            sb = f"{rb[0]:+.3f} [{rb[1]:+.3f},{rb[2]:+.3f}]"
            sm = f"{rm[0]:+.3f} [{rm[1]:+.3f},{rm[2]:+.3f}]" if rm else "n/a"
            print(f"    {label_fn(key):>16} | {rb[3]:>5} | {sb:>30} | {sm:>30}")
        print()

    print(f"(C) Q2 -- WHEN TO TRADE  (at DELTA={pick:g}s, the realistic lead)")
    # by 3h UTC bucket
    hb = {}
    for w in traded_ws:
        hb.setdefault(win_meta[w][0] // 3, set()).add(w)
    hour_buckets = sorted(hb.items())
    bucket_table("  by 3-hour UTC window (Israel local = UTC+3):",
                 lambda b: f"{b*3:02d}:00-{b*3+3:02d}:00", hour_buckets)

    # by BTC-vol tercile
    vols = sorted((win_meta[w][1], w) for w in traded_ws)
    if len(vols) >= 6:
        t = len(vols) // 3
        terc = [("low vol", {w for _, w in vols[:t]}),
                ("mid vol", {w for _, w in vols[t:2 * t]}),
                ("high vol", {w for _, w in vols[2 * t:]})]
        lo_hi = (vols[t - 1][0], vols[2 * t][0])
        bucket_table(f"  by BTC realized-vol tercile (per-window 1s-step std; "
                     f"cuts ~{lo_hi[0]:.2f}/{lo_hi[1]:.2f} $):",
                     lambda k: k, terc)

    print("  READ:")
    print("  Q1 -> if taker/maker EV CLIMBS with DELTA and the LIFT CI excludes 0, a faster")
    print("        feed is provably worth it (the * marks significance). The taker(bid)<")
    print("        maker(mid) gap is the spread you'd save by exiting as a MAKER.")
    print("  Q2 -> trade where the CI sits clearly above 0. Expect the edge to concentrate")
    print("        in HIGH-VOL windows (the edge needs BTC to move); hour-of-day is mostly a")
    print("        proxy for that. A vol gate is more robust than an hour gate.")
    print("\n  UPPER BOUND: clairvoyant DELTA + no queue race. Confirm any lift over weeks.")


if __name__ == "__main__":
    main()

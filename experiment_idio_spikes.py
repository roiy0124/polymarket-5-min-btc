"""IDIOSYNCRATIC SPIKE stats (the "lone coin nuked/pumped then snapped back" phenomenon).

Hypothesis (user): lead-lag is ASYMMETRIC -- big coins (BTC/ETH) guide the small ones, not the
reverse -- and smaller market caps carry more idiosyncratic short-term noise / manipulation. So a
SHARP move in ONE coin that NO peer shares is likely noise, and the correlated pack anchors it back
(it reverts, "gap immediately closed"). This is STATS ONLY -- no strategy yet.

For each coin's per-second Binance spot (merged across all DBs), over the shared multi-coin window:
detect spike events at peak time t:
  r_back = price(t)/price(t-W) - 1          # the W-second run to the peak
  |r_back| >= THRESH                         # a real spike (pump if >0, nuke if <0)
  LONE: every peer's same-window move is < PEER_FRAC*|r_back|  (no peer shared it = idiosyncratic)
  REVERTED: within REV_W after the peak, price gives back >= REV_FRAC of the excursion (snaps back)
Events are de-duplicated (one per REV_W window, the most extreme). Reports per coin: big spikes, how
many were LONE, how many were LONE & REVERTED, the pump/nuke split, and a noise level (median |5s move|).

    python experiment_idio_spikes.py --w 5 --thresh 0.0010 --rev-w 10 --rev-frac 0.5 --peer-frac 0.34
"""

import argparse
import bisect
import sqlite3
import statistics

import coins


def load_persec(coin):
    out = {}
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            for ts, px in conn.execute(
                    "SELECT ts, price_binance FROM snapshots WHERE price_binance IS NOT NULL "
                    "ORDER BY ts"):
                out[int(ts)] = px            # last price in that second
        except sqlite3.OperationalError:
            pass
        conn.close()
    return out


class Ser:
    def __init__(self, d):
        self.k = sorted(d); self.d = d
    def at(self, t, tol=3):
        i = bisect.bisect_left(self.k, t)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(self.k) and abs(self.k[j] - t) <= tol:
                if best is None or abs(self.k[j] - t) < abs(best - t):
                    best = self.k[j]
        return self.d[best] if best is not None else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=5, help="spike run-up window (s)")
    ap.add_argument("--thresh", type=float, default=0.0010, help="min |W-sec return| to be a spike")
    ap.add_argument("--rev-w", type=int, default=10, dest="rev_w", help="recovery window after peak (s)")
    ap.add_argument("--rev-frac", type=float, default=0.5, dest="rev_frac",
                    help="min fraction of the excursion given back to count as reverted")
    ap.add_argument("--peer-frac", type=float, default=0.34, dest="peer_frac",
                    help="LONE iff every peer's same-window move < this * |coin move|")
    ap.add_argument("--min-peers", type=int, default=3, dest="min_peers")
    args = ap.parse_args()
    W, REV_W = args.w, args.rev_w
    cl = list(coins.ENABLED)

    print("loading per-second spot (merged all DBs) ...", flush=True)
    ser = {c: Ser(load_persec(c)) for c in cl}

    rows = []
    for X in cl:
        secs = ser[X].k
        if len(secs) < 50:
            rows.append((X, 0, 0, 0, 0, 0, 0.0, 0, None)); continue
        t0, t1 = secs[0], secs[-1]
        # noise level: median |W-sec move| over the series
        moves = []
        for t in secs:
            p0 = ser[X].at(t - W); p1 = ser[X].at(t)
            if p0 and p1 and p0 > 0:
                moves.append(abs(p1 / p0 - 1))
        noise = statistics.median(moves) if moves else 0.0
        # detect spikes
        dets = []          # (t, r_back, reverted, lone)
        n_big = 0
        for t in secs:
            p_pre = ser[X].at(t - W); p_pk = ser[X].at(t)
            if not p_pre or not p_pk or p_pre <= 0:
                continue
            r_back = p_pk / p_pre - 1.0
            if abs(r_back) < args.thresh:
                continue
            n_big += 1
            p_post = ser[X].at(t + REV_W)
            if not p_post:
                continue
            exc = p_pk - p_pre
            recovered = (p_pk - p_post) / exc if exc != 0 else 0.0   # signs cancel for pump/nuke
            reverted = recovered >= args.rev_frac
            peers = []
            for Y in cl:
                if Y == X:
                    continue
                q0 = ser[Y].at(t - W); q1 = ser[Y].at(t)
                if q0 and q1 and q0 > 0:
                    peers.append(abs(q1 / q0 - 1.0))
            lone = (len(peers) >= args.min_peers and max(peers) <= args.peer_frac * abs(r_back))
            dets.append((t, r_back, reverted, lone))
        # NMS: one event per REV_W window, keep max |r_back|
        dets.sort(key=lambda d: -abs(d[1]))
        kept, used = [], []
        for d in dets:
            if all(abs(d[0] - u) > REV_W for u in used):
                kept.append(d); used.append(d[0])
        big = len(kept)
        lone_ev = [d for d in kept if d[3]]
        lone_rev = [d for d in lone_ev if d[2]]
        pumps = sum(1 for d in lone_rev if d[1] > 0)
        nukes = sum(1 for d in lone_rev if d[1] < 0)
        revfrac = (len(lone_rev) / len(lone_ev)) if lone_ev else 0.0
        span_h = (t1 - t0) / 3600.0
        rate = len(lone_rev) / span_h if span_h else 0.0
        rows.append((X, span_h, big, len(lone_ev), len(lone_rev), pumps, nukes, revfrac, rate, noise))

    print(f"\nIDIOSYNCRATIC SPIKE STATS  |  W={W}s spike, |move|>={args.thresh:.4%}, "
          f"revert>={args.rev_frac:.0%} within {REV_W}s, LONE iff peers<{args.peer_frac:.0%}x the move")
    print(f"  (coins roughly large->small mcap: btc, eth, bnb, sol, xrp, doge)\n")
    print(f"  {'coin':>5} {'span_h':>6} {'bigSpikes':>9} {'LONE':>5} {'LONE&revert':>11} "
          f"{'pump':>5} {'nuke':>5} {'rev%ofLone':>10} {'/hr':>5} {'noise(med|5s|)':>14}")
    for (X, span_h, big, lone, lonerev, pumps, nukes, revfrac, rate, noise) in rows:
        if noise is None:
            print(f"  {X:>5}  (no data)"); continue
        print(f"  {X:>5} {span_h:>6.1f} {big:>9} {lone:>5} {lonerev:>11} {pumps:>5} {nukes:>5} "
              f"{100*revfrac:>9.0f}% {rate:>5.1f} {noise:>13.4%}")
    print("\n  READ: if the smaller-cap coins (doge/xrp/sol/bnb) show MORE lone spikes + higher noise,")
    print("  and a high 'rev% of lone' (lone spikes mostly snap back), that supports 'lone small-coin")
    print("  spike = noise the pack anchors back'. This is descriptive only -- tradeability is a later test.")


if __name__ == "__main__":
    main()

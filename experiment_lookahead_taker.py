"""Does a FASTER BTC feed buy an edge? Lookahead-taker upper bound (experiment).

The hypothesis (the user's): Polymarket's quote lags real BTC by ~1-3s. A bot that
sees BTC sooner can TAKE the stale quote before it reprices. This is the structurally
sound "fair-value taker" idea -- the opposite of the passive resting-limit strategies
we already ruled out (those are SHORT the option to informed flow; a taker is LONG it).

We answer it two ways, both honest:

  (A) LEAD-LAG cross-correlation (the structural smoking gun, no trading assumptions):
      corr( BTC mid return over a 1s step ,  Polymarket Up-mid return shifted by lag L ).
      If BTC LEADS Polymarket, the correlation PEAKS at L>0 -- and that peak lag is
      literally how many seconds of "knowing BTC ahead" is worth something. If the peak
      is at L=0 (or there's no structure), Polymarket already reflects BTC -> no feed edge.

  (B) LOOKAHEAD TAKER sim: at each decision time t we get to read BTC at t+DELTA (the
      clairvoyant fast feed). We compute the BTC-implied fair P(Up) from that look-ahead
      price and, if it exceeds the current Polymarket ASK by --edge, we TAKE (pay the ask).
      Two exits, both costed (we cross the spread -- pay ask, receive bid):
        * catch-up  : sell at the BID --exit-lag seconds later (pure lead-lag capture;
                      the HEADLINE -- if Polymarket is efficient, bid~=ask and we lose the
                      spread; only a real lag pays).
        * hold       : hold to 0/1 resolution (mixes in directional foresight -> optimistic).
      We sweep DELTA in {0, 0.5, 1, 2, 3}s. **DELTA=0 is the control** (no feed advantage:
      same-instant fair vs ask). The LIFT from DELTA=0 to DELTA>0 is the value of feed speed.
      If EV is flat in DELTA -> a faster feed is NOT the missing piece. If it climbs with
      DELTA -> a faster BTC source is exactly what's needed, and we've quantified how much.

Reads btc_updown.db + old_dbs/*.db directly (per-DB, windows are disjoint). Stdlib only.
Sub-second BTC from btc_ticks (~50-85 ticks/s); taker prices from 1Hz snapshots.

    python experiment_lookahead_taker.py
    python experiment_lookahead_taker.py --edge 0.03 --exit-lag 2 --stride 5

*** Caveats (read before believing it): clairvoyant DELTA is an UPPER BOUND -- a real feed
has its own latency and you race other arbs for the same stale quote. sigma is from a
Binance proxy, not the Chainlink settlement. Decision points within a window overlap
(we also print a strict one-fill-per-window number). Polymarket CLOB taker fee is ~0 today
but settlement/gas is real; --fee-bps models it. This says whether the edge is THERE to
chase, not that you'll capture all of it. ***
"""

import os
import glob
import math
import bisect
import argparse
import sqlite3

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
    """value sampled at time u (nearest neighbour) from a time-sorted series."""
    i = bisect.bisect_left(ts_arr, u)
    if i <= 0:
        return val_arr[0]
    if i >= len(ts_arr):
        return val_arr[-1]
    return val_arr[i] if (ts_arr[i] - u) < (u - ts_arr[i - 1]) else val_arr[i - 1]


class Pearson:
    """streaming Pearson accumulator."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deltas", default="0,0.5,1,2,3",
                    help="lookahead seconds to sweep (DELTA=0 is the no-advantage control)")
    ap.add_argument("--edge", type=float, default=0.02,
                    help="trade only if fair(look-ahead) - ask >= edge")
    ap.add_argument("--exit-lag", type=float, default=2.0, dest="exit_lag",
                    help="catch-up exit: sell at the bid this many seconds after entry")
    ap.add_argument("--stride", type=float, default=5.0,
                    help="seconds between decision points within a window (decongest overlap)")
    ap.add_argument("--tau-min", type=float, default=15.0, dest="tau_min",
                    help="skip decisions with less time-left than this (ask -> 1 noise)")
    ap.add_argument("--tau-max", type=float, default=270.0, dest="tau_max",
                    help="skip decisions earlier than this (thin causal vol)")
    ap.add_argument("--max-ask", type=float, default=0.95, dest="max_ask")
    ap.add_argument("--fee-bps", type=float, default=0.0, dest="fee_bps",
                    help="round-trip taker fee in bps of stake (Polymarket ~0 today)")
    ap.add_argument("--lag-range", type=int, default=4, dest="lag_range",
                    help="lead-lag cross-corr: +/- this many 1s steps")
    args = ap.parse_args()

    deltas = [float(x) for x in args.deltas.split(",")]
    fee = args.fee_bps / 1e4
    paths = db_paths()
    if not paths:
        print("no DB found"); return

    # lead-lag cross-correlation accumulators, one Pearson per integer lag
    lags = list(range(-args.lag_range, args.lag_range + 1))
    lagacc = {L: Pearson() for L in lags}

    # taker fills: per delta -> list of (hold_roi, catch_roi_or_None, is_first_in_window)
    fills = {d: [] for d in deltas}
    n_windows = 0
    n_dbs = 0

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
            up_mid = [((r[2] + r[3]) / 2.0) if (r[2] is not None and r[3] is not None)
                      else None for r in snaps]
            btc = [r[6] for r in snaps]

            # ---- (A) lead-lag cross-correlation on the 1Hz series ----
            for i in range(1, len(snaps)):
                dbtc = btc[i] - btc[i - 1]
                if dbtc == 0:
                    continue
                for L in lags:
                    j = i + L
                    if 0 < j < len(snaps) and up_mid[j] is not None and up_mid[j - 1] is not None:
                        lagacc[L].add(dbtc, up_mid[j] - up_mid[j - 1])

            # ---- (B) lookahead-taker sim ----
            # causal per-second BTC vol (running) from the snapshot path
            diffs = [btc[k + 1] - btc[k] for k in range(len(btc) - 1)]
            won_first = {d: True for d in deltas}  # track first fill per window per delta
            last_dec = -1e9
            for i in range(8, len(snaps)):
                ts_i, tau = snaps[i][0], snaps[i][1]
                if tau is None or not (args.tau_min <= tau <= args.tau_max):
                    continue
                if ts_i - last_dec < args.stride:
                    continue
                # causal sigma from diffs strictly before i
                d_so_far = diffs[:i]
                if len(d_so_far) < 6:
                    continue
                m = sum(d_so_far) / len(d_so_far)
                var = sum((x - m) ** 2 for x in d_so_far) / (len(d_so_far) - 1)
                sig = math.sqrt(var)
                if sig <= 1e-9:
                    continue
                move_std = sig * math.sqrt(max(1.0, tau))
                up_bid_i, up_ask_i = snaps[i][2], snaps[i][3]
                dn_bid_i, dn_ask_i = snaps[i][4], snaps[i][5]
                last_dec = ts_i
                for d in deltas:
                    S_ahead = nearest(t_ts, t_mid, ts_i + d)
                    fair_up = phi((S_ahead - K) / move_std)
                    # pick the side whose fair edge over its ask is biggest (and >= edge)
                    up_e = fair_up - up_ask_i if up_ask_i and up_ask_i < args.max_ask else -9
                    dn_e = (1.0 - fair_up) - dn_ask_i if dn_ask_i and dn_ask_i < args.max_ask else -9
                    if max(up_e, dn_e) < args.edge:
                        continue
                    if up_e >= dn_e:
                        side, ask, bid_now = "Up", up_ask_i, up_bid_i
                        bid_exit_arr = [s[2] for s in snaps]   # up_bid
                    else:
                        side, ask, bid_now = "Down", dn_ask_i, dn_bid_i
                        bid_exit_arr = [s[4] for s in snaps]   # down_bid
                    if not ask or ask <= 0:
                        continue
                    won = (side == outcome)
                    hold_roi = ((1.0 if won else 0.0) - ask) / ask - fee
                    # catch-up exit: bid at ts_i + exit_lag (need both entry & exit bids)
                    if bid_now is None:
                        catch_roi = None
                    else:
                        bid_exit = nearest(s_ts, bid_exit_arr, ts_i + args.exit_lag)
                        catch_roi = (bid_exit - ask) / ask - fee if bid_exit else None
                    is_first = won_first[d]
                    won_first[d] = False
                    fills[d].append((hold_roi, catch_roi, is_first))
        conn.close()

    # ---------- report ----------
    print("=" * 74)
    print("FASTER-FEED EDGE TEST  (lead-lag + clairvoyant-lookahead taker)")
    print("=" * 74)
    print(f"data: {n_dbs} db(s), {n_windows} windows with strike+ticks+quotes; "
          f"edge>={args.edge:.2f}, exit-lag={args.exit_lag:g}s, stride={args.stride:g}s, "
          f"fee={args.fee_bps:g}bps\n")

    print("(A) LEAD-LAG cross-correlation  corr(BTC 1s return, Up-mid return @ lag L)")
    print("    L>0 peak => BTC LEADS Polymarket by L sec (a faster feed has something to bite)")
    rows = [(L, lagacc[L].r(), lagacc[L].n) for L in lags]
    best = max((rr for rr in rows if rr[1] is not None), key=lambda rr: rr[1], default=None)
    for L, r, n in rows:
        bar = ""
        if r is not None:
            bar = ("+" if r >= 0 else "-") * min(40, int(abs(r) * 400))
        star = "  <== peak" if best and L == best[0] else ""
        print(f"    L={L:+d}s  r={ (f'{r:+.4f}' if r is not None else '  n/a') }  (n={int(n)})  {bar}{star}")
    if best:
        if best[0] > 0 and (best[1] or 0) > 0:
            print(f"  -> BTC appears to LEAD by ~{best[0]}s. A faster feed is plausibly worth it.")
        else:
            print(f"  -> peak at L={best[0]} (<=0): Polymarket already tracks BTC; little feed edge.")
    print()

    print("(B) LOOKAHEAD TAKER  (DELTA=0 is the no-advantage control; lift = value of speed)")
    print(f"  {'DELTA':>6} | {'fills':>6} {'win%':>5} | {'CATCH-UP exit':>22} | "
          f"{'HOLD-to-resln':>22} | {'1/window catch':>16}")
    print(f"  {'(s)':>6} | {'':>6} {'':>5} | {'EV/$1   net($k stake)':>22} | "
          f"{'EV/$1 (optimistic)':>22} | {'n   EV/$1':>16}")
    for d in deltas:
        fl = fills[d]
        n = len(fl)
        if n == 0:
            print(f"  {d:>6g} | {0:>6} {'-':>5} | {'no fills':>22} | {'':>22} | {'':>16}")
            continue
        # ask<1 always, so a positive hold ROI == the chosen side resolved correctly
        won_n = sum(1 for h, _, _ in fl if h > 0)
        catch = [c for _, c, _ in fl if c is not None]
        hold = [h for h, _, _ in fl]
        ev_catch = sum(catch) / len(catch) if catch else float("nan")
        ev_hold = sum(hold) / len(hold)
        # net $ on a $1k notional spread evenly = ev * 1000
        catch1 = [c for _, c, first in fl if first and c is not None]
        ev_c1 = sum(catch1) / len(catch1) if catch1 else float("nan")
        print(f"  {d:>6g} | {n:>6} {won_n / n:>5.0%} | "
              f"{ev_catch:>+8.3f}  {ev_catch*1000:>+8.0f} | "
              f"{ev_hold:>+10.3f}          | {len(catch1):>4} {ev_c1:>+8.3f}")
    print()
    print("  READ: compare DELTA>0 rows to the DELTA=0 control. If CATCH-UP EV/$1 rises with")
    print("  DELTA, a faster BTC feed converts directly into edge (and how much). If it's flat")
    print("  or negative across all DELTA, feed speed is NOT the missing piece -- the quote")
    print("  isn't lagging enough to take. HOLD column is optimistic (uses the foresight to")
    print("  pick the winning side); trust CATCH-UP + the lead-lag peak in (A).")
    print("\n  UPPER BOUND: clairvoyant DELTA assumes zero feed latency and no competition for")
    print("  the stale quote. A real bot captures a FRACTION. Confirm any lift over more data.")


if __name__ == "__main__":
    main()

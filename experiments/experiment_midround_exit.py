"""MID-ROUND EXIT — measure the maker's "mistake" as the best PRICE WE COULD SELL AT during the same round,
not only the hold-to-resolution 0/1 outcome (user directive 2026-06-28).

The point: an entry's value is not only `won - entry` at settlement; it is ALSO the highest later price we could
have realized by SELLING mid-round. Our DBs hold the full intra-round path (up_bid/down_bid over time), so we can
measure the favorite-side BID we could have hit after entry. We compare three accountings on favorite-tail entries:

  HOLD                 : net_ev(entry_ask, won, taker, hold)             -- what stats.assess measures
  CLAIRVOYANT max-bid  : sell as a TAKER at the highest favorite BID reached after entry (pays entry+exit taker
                         fee). This is the UPPER BOUND of any mid-round exit -- perfect-hindsight timing.
  MAKER-REST target    : rest a fee-free SELL at entry_ask + delta; it fills IFF the bid later reaches the target,
                         else hold to resolution. Realizable, but adverse-selected (it fills on the winners you'd
                         have held to 1.0 anyway). Reports fill-rate + win|filled vs win|unfilled.

Structural prior (favorite-tail): a favorite bought near 0.96 has its bid capped near 1.0, so max-bid-minus-entry
is tiny; winners are better HELD to 1.0 than sold at a bid<1, and losers' bids COLLAPSE fast (sigma-lag: 0.96->0.61
by tl=10) so you can't sell them high without predicting the flip (the walled directional game). This experiment
tests whether the data agrees, and is the durable lens for any future entry family (esp. non-favorite/mid entries).

    python experiment_midround_exit.py [--tl 30] [--ask-lo 0.95] [--ask-hi 0.99]
"""
import argparse
import sqlite3

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from analysis import stats as S
from net_ev import net_ev_per_dollar, taker_fee_per_stake


def load(coin, tl, ask_lo, ask_hi, tol=10.0):
    """(ws, fav_ask, won, max_bid_after_entry)."""
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute("SELECT window_start, strike_binance, resolved_outcome FROM windows "
                               "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen or not strike or strike <= 0:
                continue
            seen.add(ws)
            path = con.execute(
                "SELECT time_left, up_ask, down_ask, up_bid, down_bid, price_binance FROM snapshots "
                "WHERE window_start=? AND up_ask IS NOT NULL AND down_ask IS NOT NULL "
                "AND up_bid IS NOT NULL AND down_bid IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY time_left DESC", (ws,)).fetchall()
            if len(path) < 30:
                continue
            # strict newest-before-decision entry snapshot
            before = [r for r in path if r[0] >= tl - 0.5]
            ent = min(before, key=lambda r: r[0] - tl) if before else None
            if not ent or ent[0] - tl > tol:
                continue
            t_l, ua, da, ub, db_, px = ent
            fav_up = px >= strike
            fav_ask = ua if fav_up else da
            if fav_ask < ask_lo or fav_ask >= ask_hi:
                continue
            # favorite-side BID over the post-entry path (time_left strictly after entry)
            post = [(r[3] if fav_up else r[4]) for r in path if r[0] < t_l]
            post = [b for b in post if b is not None and 0 < b < 1]
            if not post:
                continue
            max_bid = max(post)
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fav_ask, won, max_bid))
        con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--ask-lo", type=float, default=0.95, dest="ask_lo")
    ap.add_argument("--ask-hi", type=float, default=0.99, dest="ask_hi")
    args = ap.parse_args()

    rows = []
    for c in coins.ENABLED:
        rows += [(c,) + x for x in load(c, args.tl, args.ask_lo, args.ask_hi)]
    if len(rows) < 50:
        print("  too few rows."); return
    ws = np.array([r[1] for r in rows], float)
    asks = np.array([r[2] for r in rows], float)
    wons = np.array([r[3] for r in rows], float)
    mbid = np.array([r[4] for r in rows], float)

    print(f"MID-ROUND EXIT  favorite-tail ask[{args.ask_lo},{args.ask_hi}) tl~{args.tl:g}  "
          f"n={len(rows)} losers={int((wons==0).sum())}")
    print("=" * 88)
    upside = mbid - asks
    print(f"  max favorite-BID after entry vs entry ASK:  mean upside {upside.mean():+.4f}  "
          f"median {np.median(upside):+.4f}  (cap is 1-ask ~ {1-asks.mean():.3f})")
    print(f"  by outcome:  WINNERS mean upside {upside[wons==1].mean():+.4f}   "
          f"LOSERS mean upside {upside[wons==0].mean():+.4f}")
    print(f"  fraction where max-bid EVER exceeds entry ask by >=1c: {100*np.mean(upside>=0.01):.1f}%")

    # --- HOLD (what stats.assess measures) ---
    hold = np.array([net_ev_per_dollar(a, w, "taker", "hold") for a, w in zip(asks, wons)])
    # --- CLAIRVOYANT taker-exit at max-bid (UPPER BOUND: perfect timing, pays entry+exit taker fee) ---
    clair = (mbid - asks) / asks - taker_fee_per_stake(asks) - taker_fee_per_stake(mbid)
    print(f"\n  HOLD-to-resolution      mean net-EV {hold.mean():+.4f}")
    print(f"  CLAIRVOYANT max-bid exit mean net-EV {clair.mean():+.4f}   "
          f"(upper bound; perfect-hindsight sell at the peak bid, both taker fees)")
    print(f"  => mid-round exit {'BEATS' if clair.mean() > hold.mean() else 'does NOT beat'} hold even with "
          f"perfect timing; {'and clears 0' if clair.mean() > 0 else 'still does NOT clear 0 (net-negative)'}")

    # --- REALIZABLE maker-rest sell at entry+delta (fee-free fill iff bid reaches target, else hold) ---
    print(f"\n  REALIZABLE maker-rest SELL at entry+delta (fills iff max-bid>=target, else hold to resolution):")
    print(f"    {'delta':>6} {'fill%':>6} {'win|fill':>9} {'win|nofill':>11} {'mean net-EV':>12}")
    for delta in (0.01, 0.02, 0.03):
        target = np.minimum(asks + delta, 0.999)
        filled = mbid >= target
        ev = np.where(
            filled,
            (target - asks) / asks,                                   # maker sell: fee-free, realize the target
            [net_ev_per_dollar(a, w, "taker", "hold") for a, w in zip(asks, wons)],  # else hold
        )
        wf = wons[filled].mean() if filled.any() else float("nan")
        wnf = wons[~filled].mean() if (~filled).any() else float("nan")
        print(f"    {delta:>6.2f} {100*filled.mean():>5.1f}% {wf:>9.3f} {wnf:>11.3f} {ev.mean():>+12.4f}")
    print(f"    (adverse selection = win|fill > win|nofill: the rest fills on the winners you'd have held to 1.0)")

    # gate the best realizable variant for context
    print()
    a = S.assess(asks, wons, ws, n_trials=S.N_PROGRAM, label="favorite-tail HOLD (reference)")
    S.print_assess(a)
    print("\n  READ: for the FAVORITE-tail, a bid capped near 1.0 means the clairvoyant peak-sell upside is tiny and")
    print("  the realizable maker-rest is adverse-selected (fills on winners) -> mid-round exit does not rescue a")
    print("  net-negative base. The lens matters MORE for non-favorite / mid-price entries (bigger transient")
    print("  swings) -- apply it there before trusting any future candidate, not just the hold-to-resolution P&L.")


if __name__ == "__main__":
    main()

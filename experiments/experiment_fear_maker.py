"""IDEA #1 (diffusion) — Token-fear FOLLOW as a FEE-FREE MAKER in calm (over-round-tight) windows.

Three confirmed pieces, blended:
  - Token-fear FOLLOW signal is REAL at the mid (Down wins ~+0.052 over its mid when an alt Up-token
    dumps un-proportionately vs peers) but DIED to the taker fee + Down spread.
  - The over-round gate proved maker fills are NON-ADVERSE in calm (tight over-round) windows.
  - A MAKER entry is fee-free + saves the spread (the exact ~4.7pp cost that killed the taker version).

So: on a fear-FOLLOW fire, instead of taking the Down ask, REST a maker BUY on the Down token at the
down_bid; model the fill from real SELL prints hitting the bid; hold to 0/1; no taker fee, + capped rebate.
Split by over-round state to test the tension: a fear-dump is a LOUD moment — is it ever calm enough that
the maker fill is non-adverse? The decisive readout = fill-conditional Down-win-rate vs the fill price.

    python experiment_fear_maker.py
"""
import sqlite3

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from net_ev import maker_rebate_per_stake, net_ev_per_dollar
from analysis import stats as S
from ideas_old.experiment_token_fear import load_sides, scan

TICK = 0.01


def fill_and_context(coin, ws, tau):
    """For a fired fear event, fetch the decision-instant down_bid + over_round + token_down, model the
    maker-buy-Down fill (optimistic front-of-queue: filled if any SELL print hits <= down_bid before the
    window ends), and the resolved Down outcome. Returns dict or None."""
    ets = ws + (300 - tau)
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        row = conn.execute(
            "SELECT token_down, resolved_outcome FROM windows WHERE window_start=?", (ws,)).fetchone()
        if not row or row[1] not in ("Up", "Down"):
            conn.close(); continue
        token_down, outcome = row
        snap = conn.execute(
            "SELECT up_ask, down_ask, down_bid FROM snapshots WHERE window_start=? AND down_bid IS NOT NULL "
            "AND up_ask IS NOT NULL AND down_ask IS NOT NULL ORDER BY ABS(time_left-?) LIMIT 1", (ws, tau)).fetchone()
        if not snap:
            conn.close(); continue
        ua, da, db_bid = snap
        if db_bid <= 0 or db_bid >= 1:
            conn.close(); continue
        filled = conn.execute(
            "SELECT 1 FROM trades WHERE asset_id=? AND side='SELL' AND price<=? AND recv_ts>=? AND recv_ts<=? "
            "LIMIT 1", (token_down, db_bid + TICK / 2, ets, ws + 300)).fetchone() is not None
        conn.close()
        return dict(ws=ws, over_round=ua + da - 1.0, down_bid=db_bid, down_ask=da,
                    filled=filled, won=1 if outcome == "Down" else 0)
    return None


def score(label, asks, wons, wsids, entry):
    if len(asks) < 10:
        print(f"  [{label}] n={len(asks)} too few"); return
    asks = np.asarray(asks, float); wons = np.asarray(wons, float); wsids = np.asarray(wsids)
    if entry == "maker":
        rets = np.array([(w / a - 1.0) + maker_rebate_per_stake(a) for a, w in zip(asks, wons)])
    else:
        rets = np.array([net_ev_per_dollar(a, int(w), "taker", "hold") for a, w in zip(asks, wons)])
    mean, lo, hi, p1, pdef = S.deflated_resid_p(rets, wsids, S.N_PROGRAM)
    k = int(wons.sum()); n = len(wons)
    print(f"  [{label}] n={n} (loss {n-k})  win {100*wons.mean():.1f}%  vs price {asks.mean():.3f}  "
          f"fill-resid {wons.mean()-asks.mean():+.4f}  {entry}-EV {mean:+.4f}  CI[{lo:+.4f},{hi:+.4f}]  defp {pdef:.3f}")


def main():
    cl = list(coins.ENABLED)
    print("loading fear-FOLLOW fires (merged DBs) ...", flush=True)
    data, meta = load_sides(cl)
    fired, _ = scan(data, meta, cl, 0.05, 0.02, 0.05, (0.20, 0.85), follow=True)
    print(f"  {len(fired)} fear-FOLLOW fires")

    rows = []
    for coin, ws, tau, mid, ask, won in fired:
        ctx = fill_and_context(coin, ws, tau)
        if ctx:
            ctx["taker_ask"] = ask
            rows.append(ctx)
    n = len(rows)
    orr = np.array([r["over_round"] for r in rows])
    filled = np.array([r["filled"] for r in rows], bool)
    print(f"\nFEAR-FOLLOW MAKER-Down  n={n}  fill rate {100*filled.mean():.0f}%  "
          f"over_round at fear: median {np.median(orr):+.4f}  (loud or calm?)")
    print("=" * 92)

    # baseline: the DEAD taker version (buy Down at ask, fee)
    score("TAKER Down at ask (the dead version)", [r["taker_ask"] for r in rows],
          [r["won"] for r in rows], [r["ws"] for r in rows], "taker")
    # maker, all fills
    fm = [r for r in rows if r["filled"]]
    score("MAKER Down at bid — ALL fills", [r["down_bid"] for r in fm],
          [r["won"] for r in fm], [r["ws"] for r in fm], "maker")
    # maker, calm (over-round tight) fills
    thr = np.median(orr)
    fmc = [r for r in rows if r["filled"] and r["over_round"] <= thr]
    score(f"MAKER Down at bid — CALM (over_round<= {thr:+.3f})", [r["down_bid"] for r in fmc],
          [r["won"] for r in fmc], [r["ws"] for r in fmc], "maker")
    # maker, loud (over-round wide) fills — the contrast
    fml = [r for r in rows if r["filled"] and r["over_round"] > thr]
    score("MAKER Down at bid — LOUD (over_round wide)", [r["down_bid"] for r in fml],
          [r["won"] for r in fml], [r["ws"] for r in fml], "maker")
    print("\n  READ: maker removes the fee (the thing that killed the taker version). WIN if the fill-conditional")
    print("  Down-win-rate stays >> the fill price (non-adverse) AND maker-EV > 0, esp. in the CALM split.")


if __name__ == "__main__":
    main()

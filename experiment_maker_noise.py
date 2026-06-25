"""MAKER-IN-NOISE — the program's ONE un-mined corner (the only fee-free escape). SETTLED: DEAD.

Every taker strategy is walled by the 0.07*(1-p) fee; the only fee-free income is the MAKER
rebate (~0.35%/$1, capped). The passive maker is adverse-selected (filled when wrong). The
hypothesis: provide liquidity ONLY in mid-price (p~0.35-0.65) LOW-TOXICITY "noise" windows,
where the counterparty is uninformed, so you escape adverse selection and keep the rebate.

Rest a maker BUY at the up_bid in a mid-band window. Model the fill exactly as CLAUDE.md prescribes
(queue position unobservable): queue_ahead from the real book snapshot, then count SELL prints
hitting the bid until our queue clears (analysis.backtest.queue_ahead + the trades table). If
filled, HOLD to 0/1: NO taker fee, + the capped maker rebate. Score through the rigor gate.

CORRECTION (2026-06-25, second-mind reviewed): the prior postmortem reported "0 modeled fills —
the cell is empty." That was a GATE BUG, not an empty cell. The original toxicity gate called
flow_imbalance over [entry-60s, entry], but entry fires at the FIRST mid-band moment (time_left>=60
== window OPEN, median entry tl=300), so the 60s before is the PREVIOUS window when this token
barely traded -> flow_imbalance returns None ~100% (3/3716 had data) -> every candidate was dropped
before the fill model ran. The causal pre-entry FLOW gate is structurally unavailable for an
open-entry maker. Dropping it, the cell POPULATES (~2254 fills) and is decisively NEGATIVE:
win ~30.8% at mean fill 0.487 -> maker-EV/$1 ~ -0.365 even WITH rebate and NO fee. This is
mechanical adverse selection (a resting BUY fills precisely when SELL flow pushes the token toward
0). The fill model is itself OPTIMISTIC (queue_ahead==0 for 99.8% of open-entries -> assumes
front-of-empty-queue instant fill), so -0.365 is an UPPER BOUND; real fills are worse. The only
causal toxicity proxy WITH data (top-5 book depth imbalance) lifts it to ~-0.285 at strong bid
support -- nowhere near the ~0.485 breakeven. VERDICT: DEAD; live fills can only worsen it.

    python experiment_maker_noise.py [--band 0.35,0.65] [--min-depth-imb -1] [--min-left 60]
"""
import argparse
import json

import numpy as np

import coins
from net_ev import net_ev_per_dollar, maker_rebate_per_stake
from analysis import panel, stats as S
from analysis.backtest import queue_ahead

TICK = 0.01


def _book_depth_imb(up_book):
    """Top-5 book depth imbalance (bids-asks)/(bids+asks) from the snapshot JSON. This is the ONLY
    causal toxicity proxy with data at an open-entry maker (pre-entry FLOW is structurally absent:
    the token barely traded 60s before window open). Returns None if unparseable."""
    try:
        b = json.loads(up_book)
        bids = sum(float(l[1]) for l in b.get("bids", [])[:5])
        asks = sum(float(l[1]) for l in b.get("asks", [])[:5])
        tot = bids + asks
        return (bids - asks) / tot if tot > 0 else None
    except Exception:
        return None


def maker_fills(conn, band, min_depth_imb, min_left):
    """Yield one modeled maker-BUY-the-Up-token fill per window: (ws, fill_price, won).

    Gate = the causal top-5 book depth imbalance (>= min_depth_imb), NOT pre-entry flow (which is
    structurally unavailable at window-open entry; see module header). min_depth_imb=-1 disables it
    (size the raw cell)."""
    wins = conn.execute(
        "SELECT window_start, token_up, resolved_outcome FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start").fetchall()
    for ws, token, outcome in wins:
        snap = conn.execute(
            "SELECT ts, time_left, up_bid, up_mid, up_book FROM snapshots WHERE window_start=? "
            "AND up_bid IS NOT NULL AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        entry = None
        for ts, tl, bid, mid, ub in snap:
            if band[0] <= mid <= band[1] and tl >= min_left and bid > 0:
                entry = (ts, bid, ub); break                 # first mid-band moment
        if entry is None:
            continue
        ets, bid, ub = entry
        # causal toxicity proxy: only rest where the book is bid-supported (depth imbalance gate)
        if min_depth_imb > -1.0:
            di = _book_depth_imb(ub)
            if di is None or di < min_depth_imb:
                continue
        # MODEL the maker fill: we're behind queue_ahead shares at our bid; SELL prints hitting
        # the bid clear the queue, then we fill. (queue_ahead==0 at open => OPTIMISTIC instant fill.)
        qa = queue_ahead(conn, token, bid, ets)
        cum = 0.0; filled = False
        for price, sz, side in conn.execute(
                "SELECT price, size, side FROM trades WHERE asset_id=? AND recv_ts>=? "
                "ORDER BY recv_ts", (token, ets)):
            if price is None or sz is None:
                continue
            if side == "SELL" and float(price) <= bid + TICK / 2:
                cum += float(sz)
                if cum >= qa:
                    filled = True; break
        if filled:
            won = 1 if outcome == "Up" else 0
            yield ws, bid, won


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", default="0.35,0.65", help="mid-band where the maker rests")
    ap.add_argument("--min-depth-imb", type=float, default=-1.0, dest="min_depth_imb",
                    help="causal book-depth-imbalance gate: rest only if top-5 (bids-asks)/(bids+asks) "
                         ">= this. -1 disables (size the raw cell); 0.3 = 'strong bid support'.")
    ap.add_argument("--min-left", type=float, default=60.0, dest="min_left")
    ap.add_argument("--n-trials", type=int, default=20)
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))

    asks, wons, wsids = [], [], []
    for c in coins.ENABLED:
        try:
            conn = panel.connect(coin=c)
        except Exception:
            continue
        n = 0
        for ws, fill, won in maker_fills(conn, band, args.min_depth_imb, args.min_left):
            asks.append(fill); wons.append(won); wsids.append(ws); n += 1
        conn.close()
        print(f"  {c}: {n} modeled maker fills")

    n = len(asks)
    print(f"\nMAKER-IN-NOISE  band={band} min_depth_imb={args.min_depth_imb} min_left={args.min_left}  (rest bid, hold 0/1, +rebate no fee)")
    if n < 10:
        print(f"  only {n} fills — INSUFFICIENT (loosen --min-depth-imb to -1 to size the raw cell)."); return
    asks = np.asarray(asks); wons = np.asarray(wons); wsids = np.asarray(wsids)
    # net EV/$1 for a MAKER (no taker fee) + capped rebate, held to 0/1
    rets = np.array([(w / a - 1.0) + maker_rebate_per_stake(a) for a, w in zip(asks, wons)])
    mean, lo, hi, p1, pdef = S.deflated_resid_p(rets, wsids, args.n_trials)
    k = int(wons.sum())
    print(f"  fills n={n} (loss {n-k})  win {100*wons.mean():.1f}%  mean maker-EV/$1 {mean:+.4f}  "
          f"cluster-CI[{lo:+.4f},{hi:+.4f}]")
    print(f"  PRIMARY: deflated cluster-bootstrap p (vs N={args.n_trials}) = {pdef:.3f}  (raw {p1:.3f})")
    survives = bool(np.isfinite(pdef) and pdef < 0.05 and lo > 0 and (n - k) >= S.MIN_LOSS)
    print(f"  => {'SURVIVES' if survives else ('INSUFFICIENT (n_loss<%d)'%S.MIN_LOSS if (n-k)<S.MIN_LOSS else 'FAILS')}")
    print("\n  NOTE: modeled fills (optimistic on queue priority/latency). A marginal positive would need")
    print("  live paper validation; a clear negative kills the cell. Rebate ceiling ~0.35%/$1 caps the upside.")


if __name__ == "__main__":
    main()

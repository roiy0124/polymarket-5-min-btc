"""MAKER-IN-NOISE — the program's ONE un-mined corner (the only fee-free escape).

Every taker strategy is walled by the 0.07*(1-p) fee; the only fee-free income is the MAKER
rebate (~0.35%/$1, capped). The passive maker is adverse-selected (filled when wrong). The
hypothesis: provide liquidity ONLY in mid-price (p~0.35-0.65) LOW-TOXICITY "noise" windows,
where the counterparty is uninformed, so you escape adverse selection and keep the rebate.

Rest a maker BUY at the up_bid in a mid-band window with low pre-entry flow imbalance
(uninformed). Model the fill exactly as CLAUDE.md prescribes (queue position unobservable):
queue_ahead from the real book snapshot, then count SELL prints hitting the bid until our queue
clears (analysis.backtest.queue_ahead + the trades table). If filled, HOLD to 0/1: NO taker fee,
+ the capped maker rebate. Score the filled positions through the corrected rigor gate.

Honest prior (quant panel): it DIES — idea E's algebra (rebate biggest where toxicity worst) +
the -0.31 passive kill blanket the mid-band; a model fill can SIZE/kill the cell but a marginal
positive would need live paper validation. Run it to settle, not to hope.

    python experiment_maker_noise.py [--band 0.35,0.65] [--max-toxicity 0.4] [--min-left 60]
"""
import argparse

import numpy as np

import coins
from net_ev import net_ev_per_dollar, maker_rebate_per_stake
from analysis import panel, stats as S
from analysis.backtest import queue_ahead
from analysis.flow import flow_imbalance

TICK = 0.01


def maker_fills(conn, band, max_tox, min_left, lookback=60.0):
    """Yield one modeled maker-BUY-the-Up-token fill per window: (ws, fill_price, won)."""
    wins = conn.execute(
        "SELECT window_start, token_up, resolved_outcome FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start").fetchall()
    for ws, token, outcome in wins:
        snap = conn.execute(
            "SELECT ts, time_left, up_bid, up_mid FROM snapshots WHERE window_start=? "
            "AND up_bid IS NOT NULL AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        entry = None
        for ts, tl, bid, mid in snap:
            if band[0] <= mid <= band[1] and tl >= min_left and bid > 0:
                entry = (ts, bid); break                     # first mid-band moment
        if entry is None:
            continue
        ets, bid = entry
        # NOISE gate: low pre-entry flow imbalance = uninformed counterparty
        if max_tox is not None:
            imb, _ = flow_imbalance(conn, token, ets - lookback, ets)
            if imb is None or abs(imb) >= max_tox:
                continue
        # MODEL the maker fill: we're behind queue_ahead shares at our bid; SELL prints hitting
        # the bid clear the queue, then we fill.
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
    ap.add_argument("--max-toxicity", type=float, default=0.4, dest="max_tox",
                    help="skip if |pre-entry flow imbalance| >= this (the noise/uninformed gate)")
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
        for ws, fill, won in maker_fills(conn, band, args.max_tox, args.min_left):
            asks.append(fill); wons.append(won); wsids.append(ws); n += 1
        conn.close()
        print(f"  {c}: {n} modeled maker fills")

    n = len(asks)
    print(f"\nMAKER-IN-NOISE  band={band} max_tox={args.max_tox} min_left={args.min_left}  (rest bid, hold 0/1, +rebate no fee)")
    if n < 10:
        print(f"  only {n} fills — INSUFFICIENT to assess (book_events retention ~3d limits this)."); return
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

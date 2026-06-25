"""MAKER-TOXICITY TIME MAP — is the fee-free maker corner dead EVERYWHERE, or only at window-open?

The maker-in-noise kill (-0.365/$1, memory program-walled-verdict) entered at the FIRST mid-band
moment == window OPEN (time_left~300), the structurally WORST point: the token just came into
existence, the book is a thin p~0.5 placeholder, and your resting bid is the first informed taker's
target (pure adverse selection). That proved ONE point on a curve, not the curve.

This maps the fill-conditional economics across time_left BANDS. For each band [lo,hi] we rest a maker
BUY at up_bid on the FIRST mid-band snapshot whose time_left falls in the band, model the fill from the
real book queue + SELL prints (analysis.backtest.queue_ahead, exactly as experiment_maker_noise), hold
to 0/1, credit the capped rebate, charge NO taker fee. The decisive readout per band is the
FILL-CONDITIONAL RESIDUAL = mean(won) - mean(fill_price): a fair (non-toxic) fill has residual ~ 0; the
rebate ceiling is ~0.4%/$1, so a band is a real fee-free corner ONLY if its residual is within ~0.004
of 0. If every band is deeply negative, the maker corner is dead everywhere (not just at open).

    python experiment_maker_timemap.py [--band 0.35,0.65]
"""
import argparse
import numpy as np

import coins
from net_ev import maker_rebate_per_stake
from analysis import panel, stats as S

TICK = 0.01
BANDS = [(300, 240), (240, 180), (180, 120), (120, 60), (60, 1)]


def fills_in_band(conn, lo, hi, band):
    """Yield (ws, fill_price, won) for a maker BUY resting in time_left in (hi,lo], mid in band.

    OPTIMISTIC fill model (front-of-queue): filled if ANY SELL print hits at/below our bid before the
    window ends. The earlier diagnostic showed queue_ahead==0 for ~99.8% of entries, so this matches the
    real model at the open and is an UPPER BOUND elsewhere (real queue => fewer/worse fills) -> a negative
    fill-conditional residual here is a ROBUST kill. Avoids the per-call book_events scan that made the
    exact-queue version intractable under live-collector lock contention."""
    wins = conn.execute(
        "SELECT window_start, token_up, resolved_outcome FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start").fetchall()
    for ws, token, outcome in wins:
        row = conn.execute(
            "SELECT ts, up_bid FROM snapshots WHERE window_start=? AND up_bid IS NOT NULL "
            "AND up_mid IS NOT NULL AND up_mid BETWEEN ? AND ? AND time_left<=? AND time_left>? "
            "AND up_bid>0 ORDER BY time_left DESC LIMIT 1", (ws, band[0], band[1], lo, hi)).fetchone()
        if not row:
            continue
        ets, bid = row
        wend = ws + 300
        hit = conn.execute(
            "SELECT 1 FROM trades WHERE asset_id=? AND side='SELL' AND price<=? AND recv_ts>=? "
            "AND recv_ts<=? LIMIT 1", (token, bid + TICK / 2, ets, wend)).fetchone()
        if hit:
            yield ws, bid, 1 if outcome == "Up" else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", default="0.35,0.65")
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))
    conns = {}
    for c in coins.ENABLED:
        try:
            conns[c] = panel.connect(coin=c)
        except Exception:
            pass

    print(f"MAKER-TOXICITY TIME MAP  band={band}  (rest up_bid, model fill, hold 0/1, +rebate no fee)")
    print(f"  decisive column = fill-conditional residual mean(won)-mean(fill); fee-free corner needs |resid|<~0.004\n")
    print(f"  {'tl band':>12} {'fills':>6} {'loss':>5} {'win%':>6} {'mean fill':>9} {'fill-resid':>10} "
          f"{'maker-EV':>9} {'deflated p':>10}")
    for lo, hi in BANDS:
        asks, wons, wsids = [], [], []
        for c, conn in conns.items():
            for ws, fill, won in fills_in_band(conn, lo, hi, band):
                asks.append(fill); wons.append(won); wsids.append(ws)
        n = len(asks)
        if n < 10:
            print(f"  {f'{hi}-{lo}':>12} {n:>6}  (too few)"); continue
        asks = np.array(asks); wons = np.array(wons); wsids = np.array(wsids)
        rets = np.array([(w / a - 1.0) + maker_rebate_per_stake(a) for a, w in zip(asks, wons)])
        resid = wons.mean() - asks.mean()
        mean, plo, phi, p1, pdef = S.deflated_resid_p(rets, wsids, 30)
        n_loss = int((wons == 0).sum())
        print(f"  {f'{hi}-{lo}':>12} {n:>6} {n_loss:>5} {100*wons.mean():>5.1f}% {asks.mean():>9.3f} "
              f"{resid:>+10.4f} {mean:>+9.4f} {pdef:>10.3f}")
    print("\n  READ: if EVERY band's fill-resid is << -0.004, the maker corner is dead across the whole")
    print("  window (not just at open). A band with fill-resid within ~0.004 of 0 = a real fee-free corner.")


if __name__ == "__main__":
    main()

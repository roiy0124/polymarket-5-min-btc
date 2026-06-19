"""Phase 1 — signal finder.

Finds the most promising limit-order signals from the exit-map data, kept only if
they clear YOUR floors (min win-rate AND min ROI) in ALL THREE lookbacks (last 2h,
6h, 1d). A signal = {side, entry price z, buy-window [t1,t2] (>=30s), sell price T}.

To salvage a line before dropping it, the search may BOTH shrink the buy-window
(down to 30s) AND lower the sell price T (lower T -> more entries reach it -> higher
win-rate, lower ROI). Among everything clearing the floors it picks the sweet spot:
max  worst-case-win-rate(across lookbacks) x ROI.

  shares to buy = X_usd / z   (min bet $1).  ROI = (T - z)/z.

Outputs a ranked table and writes signals.json (Phase 2 consumes it). Read-only.

    python -m analysis.signals --min-win 0.70 --min-roi 0.50 --usd 2

Honest caveat: win-rates come from the mid-price path. Live, your limit BUY at z
fills only as the price trades down to z, and the SELL at T fills only if the price
reaches T -- so live results run BELOW these (adverse selection). Validate, then
paper-trade before risking money.
"""

import os
import json
import time
import bisect
import argparse

from . import panel
from .exit_maps import entry_and_exit, WINDOW, BUY_WIN_MIN_WIDTH, BUY_WIN_STEP

LOOKBACKS = [("2h", 2 * 3600), ("6h", 6 * 3600), ("1d", 24 * 3600)]
OUT_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "signals.json")


def load(conn):
    out = []
    for ws, outcome in conn.execute(
            "SELECT window_start, resolved_outcome FROM windows "
            "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start"):
        rows = conn.execute(
            "SELECT time_left, up_mid, down_mid FROM snapshots WHERE window_start=? "
            "AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        if not rows:
            continue
        up, dn = [], []
        for tl, um, dm in rows:
            x = max(0.0, (WINDOW - tl) / 60.0)
            up.append((x, um))
            if dm is not None:
                dn.append((x, dm))
        out.append({"ws": ws, "outcome": outcome, "up": up, "down": dn})
    return out


def dots_for(windows, side, cent):
    res = []
    for w in windows:
        won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
        eb = entry_and_exit(w[side], cent, won)
        if eb is None:
            continue
        x, y = eb
        res.append((x, y, w["ws"]))
    return res


def find_signal(dots, z, cuts, min_win, min_roi, min_dots):
    """Best (buy-window>=30s, sell T) clearing both floors in all lookbacks."""
    t_floor = z * (1 + min_roi)
    cand_T = sorted({d[1] for d in dots if d[1] >= t_floor - 1e-9})
    if not cand_T:
        return None
    grid = [round(i * BUY_WIN_STEP, 2) for i in range(int(5 / BUY_WIN_STEP) + 1)]
    best = None
    for a in range(len(grid)):
        for b in range(a + 1, len(grid)):
            t1, t2 = grid[a], grid[b]
            if t2 - t1 < BUY_WIN_MIN_WIDTH - 1e-9:
                continue
            in_win = [d for d in dots if t1 <= d[0] <= t2]
            subs = []
            ok = True
            for _, cut in cuts:
                sy = sorted(d[1] for d in in_win if d[2] >= cut)
                if len(sy) < min_dots:
                    ok = False
                    break
                subs.append(sy)
            if not ok:
                continue
            for T in cand_T:
                roi = (T - z) / z
                reaches = []
                good = True
                for sy in subs:
                    r = len(sy) - bisect.bisect_left(sy, T - 1e-9)
                    wr = r / len(sy)
                    if wr < min_win:
                        good = False
                        break
                    reaches.append(wr)
                if not good:
                    continue
                score = min(reaches) * roi
                key = (round(score, 6), round(min(reaches), 4), t2 - t1)
                if best is None or key > best[0]:
                    best = (key, t1, t2, T, reaches, roi)
    if best is None:
        return None
    _, t1, t2, T, reaches, roi = best
    return {"t1": t1, "t2": t2, "sell": round(T, 3), "roi": roi,
            "win_2h": reaches[0], "win_6h": reaches[1], "win_1d": reaches[2],
            "score": min(reaches) * roi, "n_2h": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-win", type=float, default=0.70, dest="min_win")
    ap.add_argument("--min-roi", type=float, default=0.50, dest="min_roi")
    ap.add_argument("--usd", type=float, default=2.0)
    ap.add_argument("--min-dots", type=int, default=5, dest="min_dots")
    args = ap.parse_args()

    now = time.time()
    cuts = [(name, now - secs) for name, secs in LOOKBACKS]
    conn = panel.connect()
    windows = load(conn)
    conn.close()

    print(f"Signal finder  |  floors: win>= {args.min_win:.0%}  ROI>= {args.min_roi:+.0%}"
          f"  |  bet ${args.usd:g}  |  robust across 2h/6h/1d  |  {len(windows)} windows")

    signals = []
    for side in ("up", "down"):
        for cent in range(1, 50):     # entry < 0.50 (need room to sell higher)
            z = cent / 100.0
            d = dots_for(windows, side, cent)
            sig = find_signal(d, z, cuts, args.min_win, args.min_roi, args.min_dots)
            if sig:
                sig.update({"side": side, "entry": z,
                            "shares": round(args.usd / z, 2)})
                signals.append(sig)
    signals.sort(key=lambda s: -s["score"])

    if not signals:
        print("\n  no signals cleared the floors in all three lookbacks.")
        print("  -> lower --min-win / --min-roi, lower --min-dots, or collect more data.")
        return
    print(f"\n  {len(signals)} signal(s):")
    print(f"  {'side':>4} {'entry':>5} {'buy(min)':>9} {'sell':>5} {'shares':>6} "
          f"{'ROI':>6} {'win2h':>6} {'win6h':>6} {'win1d':>6} {'score':>6}")
    for s in signals:
        print(f"  {s['side']:>4} {s['entry']:>5.2f} {s['t1']:>4.2g}-{s['t2']:<4.2g} "
              f"{s['sell']:>5.2f} {s['shares']:>6.2g} {s['roi']:>+6.0%} "
              f"{s['win_2h']:>6.0%} {s['win_6h']:>6.0%} {s['win_1d']:>6.0%} "
              f"{s['score']:>+6.2f}")
    with open(OUT_JSON, "w") as f:
        json.dump({"generated": now, "min_win": args.min_win, "min_roi": args.min_roi,
                   "usd": args.usd, "signals": signals}, f, indent=2)
    print(f"\n  saved -> {OUT_JSON}  (Phase 2 will consume this after you validate)")
    print("  CAVEAT: mid-based win-rates -> optimistic vs live fills (adverse selection).")


if __name__ == "__main__":
    main()

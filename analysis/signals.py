"""Phase 1 — signal finder.

Finds the most promising limit-order signals from the exit-map data, kept only if
they clear YOUR floors (min win-rate AND min ROI) in ALL THREE lookbacks (last 6h,
12h, 24h). A signal = {side, entry price z, buy-window [t1,t2] (>=30s), sell price T}.

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

LOOKBACKS = [("6h", 6 * 3600), ("12h", 12 * 3600), ("24h", 24 * 3600)]
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
            "wins": [round(r, 4) for r in reaches], "score": min(reaches) * roi}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-win", type=float, default=0.70, dest="min_win")
    ap.add_argument("--min-roi", type=float, default=0.50, dest="min_roi")
    ap.add_argument("--usd", type=float, default=2.0)
    ap.add_argument("--min-dots", type=int, default=5, dest="min_dots")
    ap.add_argument("--min-entry", type=float, default=0.10, dest="min_entry",
                    help="skip entry prices below this (drops illiquid penny tokens)")
    args = ap.parse_args()

    now = time.time()
    cuts = [(name, now - secs) for name, secs in LOOKBACKS]
    lbnames = "/".join(n for n, _ in LOOKBACKS)
    conn = panel.connect()
    windows = load(conn)
    conn.close()

    print(f"Signal finder  |  floors: win>= {args.min_win:.0%}  ROI>= {args.min_roi:+.0%}"
          f"  |  bet ${args.usd:g}  |  entry>= {args.min_entry:.2f}  |  robust across "
          f"{lbnames}  |  {len(windows)} windows")

    lo = max(1, int(round(args.min_entry * 100)))
    signals = []
    for side in ("up", "down"):
        for cent in range(lo, 50):     # entry in [min_entry, 0.50)
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
    win_hdr = "".join(f"{('w'+n):>6}" for n, _ in LOOKBACKS)
    print(f"\n  {len(signals)} signal(s):")
    print(f"  {'side':>4} {'entry':>5} {'buy(min)':>9} {'sell':>5} {'shares':>6} "
          f"{'ROI':>6}{win_hdr} {'score':>6}")
    for s in signals:
        wins = "".join(f"{w:>6.0%}" for w in s["wins"])
        print(f"  {s['side']:>4} {s['entry']:>5.2f} {s['t1']:>4.2g}-{s['t2']:<4.2g} "
              f"{s['sell']:>5.2f} {s['shares']:>6.2g} {s['roi']:>+6.0%}{wins} "
              f"{s['score']:>+6.2f}")
    with open(OUT_JSON, "w") as f:
        json.dump({"generated": now, "min_win": args.min_win, "min_roi": args.min_roi,
                   "usd": args.usd, "signals": signals}, f, indent=2)
    print(f"\n  saved -> {OUT_JSON}  (Phase 2 will consume this after you validate)")
    print("  CAVEAT: mid-based win-rates -> optimistic vs live fills (adverse selection).")


if __name__ == "__main__":
    main()

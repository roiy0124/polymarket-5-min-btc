"""Unconditional dip->recover scan — a FIRST look at the mean-reversion idea.

For each window and each outcome side, ask: did the mid dip to <= --dip with at
least --min-left seconds remaining, and later (same window) recover to >= --recover
before the window ended? Reports the recover rate and a naive EV.

    python -m analysis.reversion [--dip 0.25 --recover 0.33 --min-left 240]

BIG CAVEAT (STRATEGY-MEAN-REVERSION.md): this is the UNCONDITIONAL rate measured
on the mid path. The number that actually matters is the rate CONDITIONAL on your
limit order getting FILLED on the way down (adverse selection makes it worse), and
fills must be modeled. Treat this as a screen, not a backtest.
"""

import sys
import argparse

from . import panel


def scan_side(conn, window_start, side, dip, recover, min_left):
    col = "up_mid" if side == "up" else "down_mid"
    snaps = conn.execute(
        f"""SELECT time_left, {col} FROM snapshots
            WHERE window_start=? AND {col} IS NOT NULL
            ORDER BY ts ASC""", (window_start,)).fetchall()
    dipped_at = None
    for i, (tl, mid) in enumerate(snaps):
        if dipped_at is None:
            if mid <= dip and tl >= min_left:
                dipped_at = i
        else:
            if mid >= recover:
                return ("recovered", snaps[dipped_at][1])
    if dipped_at is not None:
        return ("no_recover", snaps[dipped_at][1])
    return (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dip", type=float, default=0.25)
    ap.add_argument("--recover", type=float, default=0.33)
    ap.add_argument("--min-left", type=float, default=240.0, dest="min_left")
    args = ap.parse_args()

    conn = panel.connect()
    windows = conn.execute(
        "SELECT window_start FROM windows ORDER BY window_start").fetchall()
    dips = recovers = 0
    for (ws,) in windows:
        for side in ("up", "down"):
            status, _ = scan_side(conn, ws, side, args.dip, args.recover, args.min_left)
            if status is None:
                continue
            dips += 1
            if status == "recovered":
                recovers += 1
    conn.close()

    print(f"Dip->recover scan: dip<= {args.dip}  recover>= {args.recover}  "
          f"min_left>= {args.min_left:.0f}s")
    print(f"  windows scanned: {len(windows)}   dip episodes: {dips}   recovered: {recovers}")
    if dips == 0:
        print("  no dip episodes yet — need more data or looser thresholds.")
        return
    rate = recovers / dips
    win, loss = args.recover - args.dip, args.dip   # +recover-dip if win, -dip to 0 if lose
    ev = rate * win - (1 - rate) * loss
    be = loss / (win + loss)
    print(f"  UNCONDITIONAL recover rate: {rate:.3f}   (break-even ~{be:.3f})")
    print(f"  naive EV/episode (no fees, no adverse selection): {ev:+.4f}")
    print("\n  CAVEAT: unconditional + mid-based. Real edge needs the rate CONDITIONAL")
    print("  on a fill (adverse selection lowers it) and a fill model. Screen, not backtest.")


if __name__ == "__main__":
    main()

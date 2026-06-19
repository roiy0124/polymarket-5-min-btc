"""Quick look at what the collector has captured. Zero dependencies.

    python peek.py            # summary + last few snapshots
    python peek.py windows    # one row per 5-min market (strike/final/resolution)
"""

import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btc_updown.db")


def fmt(v, nd=4):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def summary(conn):
    nsnap = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    nwin = conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    nres = conn.execute(
        "SELECT COUNT(*) FROM windows WHERE resolved_outcome IS NOT NULL"
    ).fetchone()[0]
    print(f"snapshots: {nsnap}   windows: {nwin}   settled: {nres}")

    # WebSocket event streams (present once ws_collector.py has run)
    try:
        nbook = conn.execute("SELECT COUNT(*) FROM book_events").fetchone()[0]
        ntrade = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        nbtc = conn.execute("SELECT COUNT(*) FROM btc_ticks").fetchone()[0]
        print(f"ws streams -> book_events: {nbook}   trades: {ntrade}   btc_ticks: {nbtc}")
    except sqlite3.OperationalError:
        pass
    print()
    print("last 12 snapshots (live window):")
    print(f"{'utc time':>24} {'t-left':>7} {'up_bid':>7} {'up_ask':>7} {'up_mid':>7} "
          f"{'dn_mid':>7} {'binance':>11} {'pyth':>11}")
    rows = conn.execute(
        """SELECT ts_utc, time_left, up_bid, up_ask, up_mid, down_mid, btc_binance, btc_pyth
           FROM snapshots ORDER BY ts DESC LIMIT 12"""
    ).fetchall()
    for r in reversed(rows):
        print(f"{fmt(r[0]):>24} {fmt(r[1],1):>7} {fmt(r[2]):>7} {fmt(r[3]):>7} {fmt(r[4]):>7} "
              f"{fmt(r[5]):>7} {fmt(r[6],2):>11} {fmt(r[7],2):>11}")


def windows(conn):
    print(f"{'window':>12} {'strike':>11} {'final':>11} {'ours':>5} {'official':>8} {'partial':>7}")
    rows = conn.execute(
        """SELECT window_start, strike_binance, final_binance, our_outcome,
                  resolved_outcome, partial
           FROM windows ORDER BY window_start DESC LIMIT 30"""
    ).fetchall()
    for r in rows:
        print(f"{r[0]:>12} {fmt(r[1],2):>11} {fmt(r[2],2):>11} "
              f"{fmt(r[3]):>5} {fmt(r[4]):>8} {('yes' if r[5] else ''):>7}")


def main():
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.Error as e:
        print(f"cannot open {DB_PATH}: {e}")
        return
    mode = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if mode == "windows":
        windows(conn)
    else:
        summary(conn)
    conn.close()


if __name__ == "__main__":
    main()

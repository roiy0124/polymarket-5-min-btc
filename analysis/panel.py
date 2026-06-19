"""Build a per-window panel (features + outcome) from the collector DB.

One row per resolved 5-min window, with the market's Up mid-price sampled at a
chosen time-left horizon (the "prediction") and the realized outcome (1=Up).
This is the table the calibration study consumes.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "btc_updown.db")


def connect(path=DB_PATH):
    return sqlite3.connect(path, timeout=10)


def build_panel(conn, horizon_s=240.0):
    """Return a list of dict rows for every settled window.

    horizon_s: sample the Up mid-price at the snapshot whose time_left is closest
    to this (e.g. 240 = 1 minute into a 5-min window)."""
    windows = conn.execute(
        """SELECT window_start, resolved_outcome, strike_binance, final_binance
           FROM windows WHERE resolved_outcome IN ('Up','Down')
           ORDER BY window_start""").fetchall()
    rows = []
    for ws, outcome, strike, final in windows:
        snap = conn.execute(
            """SELECT up_mid, down_mid, up_bid, up_ask, time_left
               FROM snapshots
               WHERE window_start=? AND up_mid IS NOT NULL
               ORDER BY ABS(time_left - ?) LIMIT 1""", (ws, horizon_s)).fetchone()
        if not snap:
            continue
        up_mid, down_mid, up_bid, up_ask, tl = snap
        rows.append({
            "window_start": ws,
            "pred_up": up_mid,                      # market-implied P(Up)
            "outcome": 1 if outcome == "Up" else 0,  # realized
            "time_left": tl,
            "spread": (up_ask - up_bid) if (up_ask is not None and up_bid is not None) else None,
            "strike": strike,
            "final": final,
        })
    return rows


def outcome_base_rate(rows):
    if not rows:
        return None
    return sum(r["outcome"] for r in rows) / len(rows)

"""Build a per-window panel (features + outcome) from the collector DB.

One row per resolved 5-min window, with the market's Up mid-price sampled at a
chosen time-left horizon (the "prediction") and the realized outcome (1=Up).
This is the table the calibration study consumes.
"""

import os
import time
import glob
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(HERE, "btc_updown.db")
OLD_DBS_DIR = os.path.join(HERE, "old_dbs")


def _source_dbs():
    """Current DB + any archived DBs in old_dbs/."""
    dbs = [DB_PATH] if os.path.exists(DB_PATH) else []
    dbs += sorted(glob.glob(os.path.join(OLD_DBS_DIR, "*.db")))
    return dbs


def _merged_connection(days):
    """In-memory DB of windows+snapshots from the last `days` days, merged across
    the current DB and every archive in old_dbs/. Stream tables (book_events/trades/
    btc_ticks) are created empty (too big to merge; only price analyses use this)."""
    cutoff = time.time() - float(days) * 86400.0
    sources = _source_dbs()
    mem = sqlite3.connect(":memory:")
    if not sources:
        return mem
    src0 = sqlite3.connect(sources[0])
    creates = src0.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                           "AND sql NOT NULL").fetchall()
    src0.close()
    for (sql,) in creates:
        try:
            mem.execute(sql)
        except sqlite3.Error:
            pass
    mem.execute("CREATE INDEX IF NOT EXISTS ix_m_snap ON snapshots(window_start)")
    # snapshot columns minus autoincrement id (ids collide across DBs)
    snap_cols = ",".join(r[1] for r in mem.execute("PRAGMA table_info(snapshots)")
                         if r[1] != "id")
    n_db = 0
    for src in sources:
        try:
            mem.execute("ATTACH DATABASE ? AS s", (src,))
            mem.execute("INSERT OR IGNORE INTO windows SELECT * FROM s.windows "
                        "WHERE window_start >= ?", (cutoff,))
            mem.execute(f"INSERT INTO snapshots ({snap_cols}) SELECT {snap_cols} "
                        f"FROM s.snapshots WHERE window_start >= ?", (cutoff,))
            mem.commit()                       # end txn so DETACH is allowed
            mem.execute("DETACH DATABASE s")
            n_db += 1
        except sqlite3.Error:
            try:
                mem.commit()
                mem.execute("DETACH DATABASE s")
            except sqlite3.Error:
                pass
    mem.commit()
    nwin = mem.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    print(f"[scope] last {days} days across {n_db} db(s) -> {nwin} windows", flush=True)
    return mem


def connect(path=None):
    """Open the data. Honors env BTC_ANALYSIS_DAYS: if set, return a merged
    last-N-days connection across current + old_dbs/; else the current DB."""
    if path is None:
        days = os.environ.get("BTC_ANALYSIS_DAYS")
        if days:
            try:
                return _merged_connection(days)
            except Exception as e:
                print(f"[scope] merge failed ({e!r}); using current DB", flush=True)
    return sqlite3.connect(path or DB_PATH, timeout=10)


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

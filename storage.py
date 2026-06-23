"""SQLite storage for the BTC up/down collector.

Two tables:
  windows   - one row per 5-minute market (strike, final price, resolution)
  snapshots - the high-frequency time series (odds + prices over time)
"""

import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (
    window_start    INTEGER PRIMARY KEY,   -- unix ts, == slug number
    window_end      INTEGER NOT NULL,
    slug            TEXT,
    condition_id    TEXT,
    token_up        TEXT,
    token_down      TEXT,
    -- strike = BTC price at window start (the "target price")
    strike_binance  REAL,
    strike_pyth     REAL,
    strike_ts       REAL,
    -- final = BTC price at window end
    final_binance   REAL,
    final_pyth      REAL,
    final_ts        REAL,
    resolved_outcome TEXT,   -- official 'Up'/'Down' from Polymarket
    our_outcome      TEXT,   -- our calc: final >= strike ? 'Up' : 'Down'
    partial          INTEGER DEFAULT 0,   -- 1 if we joined mid-window (no true strike)
    created_at       REAL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start  INTEGER NOT NULL,
    ts            REAL NOT NULL,        -- wall-clock capture time (unix epoch, float)
    ts_utc        TEXT NOT NULL,        -- exact global time, ISO-8601 UTC (ms precision)
    time_left     REAL NOT NULL,        -- seconds until window_end
    up_bid        REAL,
    up_ask        REAL,
    up_mid        REAL,
    up_spread     REAL,
    down_bid      REAL,
    down_ask      REAL,
    down_mid      REAL,
    down_spread   REAL,
    up_book       TEXT,                 -- JSON: {"bids":[[p,s]...],"asks":[[p,s]...]}
    down_book     TEXT,
    price_binance   REAL,
    price_pyth      REAL
);

CREATE INDEX IF NOT EXISTS idx_snap_window ON snapshots(window_start);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);

-- ---- WebSocket event-stream tables (written by ws_collector.py) ----

-- Every order-book event from the CLOB market channel: full 'book' snapshots,
-- incremental 'price_change' deltas, and 'tick_size_change' resets. Raw payload
-- is kept verbatim so the book can be reconstructed exactly offline.
CREATE TABLE IF NOT EXISTS book_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recv_ts       REAL NOT NULL,     -- local capture time (unix epoch)
    recv_utc      TEXT NOT NULL,     -- exact global time, ISO-8601 UTC (ms)
    window_start  INTEGER,           -- which 5-min market this asset belongs to
    asset_id      TEXT,              -- outcome token id
    event_type    TEXT,              -- 'book' | 'price_change' | 'tick_size_change'
    src_ts        TEXT,              -- timestamp reported inside the event, if any
    hash          TEXT,              -- book-content hash from the event (integrity)
    payload       TEXT               -- raw JSON event, verbatim
);
CREATE INDEX IF NOT EXISTS idx_book_window ON book_events(window_start);
CREATE INDEX IF NOT EXISTS idx_book_asset ON book_events(asset_id);
CREATE INDEX IF NOT EXISTS idx_book_recv ON book_events(recv_ts);

-- Trade prints (last_trade_price) from the market channel. For a resting-order
-- strategy these tell you what actually filled, at what price/size, and when.
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recv_ts       REAL NOT NULL,
    recv_utc      TEXT NOT NULL,
    window_start  INTEGER,
    asset_id      TEXT,
    price         REAL,
    size          REAL,
    side          TEXT,
    src_ts        TEXT,
    payload       TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_window ON trades(window_start);
CREATE INDEX IF NOT EXISTS idx_trades_recv ON trades(recv_ts);

-- Low-latency BTC price ticks (Binance @bookTicker), event-driven on every
-- top-of-book change -> best proxy for strike/current at the window boundary.
CREATE TABLE IF NOT EXISTS price_ticks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recv_ts       REAL NOT NULL,
    recv_utc      TEXT NOT NULL,
    source        TEXT,              -- 'binance_bookticker'
    bid           REAL,
    ask           REAL,
    mid           REAL,
    update_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_price_recv ON price_ticks(recv_ts);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")   # wait, don't fail, on a write lock
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---- batch writers for the high-frequency WS streams -----------------------
# These do NOT commit; the caller batches many rows and commits periodically.

def insert_book_events(conn, rows):
    """rows: (recv_ts, recv_utc, window_start, asset_id, event_type, src_ts, hash, payload)"""
    conn.executemany(
        """INSERT INTO book_events
               (recv_ts, recv_utc, window_start, asset_id, event_type, src_ts, hash, payload)
           VALUES (?,?,?,?,?,?,?,?)""", rows)


def insert_trades(conn, rows):
    """rows: (recv_ts, recv_utc, window_start, asset_id, price, size, side, src_ts, payload)"""
    conn.executemany(
        """INSERT INTO trades
               (recv_ts, recv_utc, window_start, asset_id, price, size, side, src_ts, payload)
           VALUES (?,?,?,?,?,?,?,?,?)""", rows)


def insert_price_ticks(conn, rows):
    """rows: (recv_ts, recv_utc, source, bid, ask, mid, update_id)"""
    conn.executemany(
        """INSERT INTO price_ticks
               (recv_ts, recv_utc, source, bid, ask, mid, update_id)
           VALUES (?,?,?,?,?,?,?)""", rows)


def prune_ws(path, cutoff_ts):
    """Delete WS-stream rows older than cutoff_ts. Opens its own short-lived
    connection (safe to call from a worker thread). Returns (n_book, n_btc).
    `windows`, `snapshots`, and `trades` are intentionally kept forever."""
    conn = sqlite3.connect(path, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        cur = conn.cursor()
        cur.execute("DELETE FROM book_events WHERE recv_ts < ?", (cutoff_ts,))
        n_book = cur.rowcount
        cur.execute("DELETE FROM price_ticks WHERE recv_ts < ?", (cutoff_ts,))
        n_btc = cur.rowcount
        conn.commit()
        return n_book, n_btc
    finally:
        conn.close()


def upsert_window(conn, m, window_end, created_at):
    conn.execute(
        """INSERT INTO windows (window_start, window_end, slug, condition_id,
                token_up, token_down, created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(window_start) DO UPDATE SET
                slug=excluded.slug, condition_id=excluded.condition_id,
                token_up=excluded.token_up, token_down=excluded.token_down""",
        (m["window_start"], window_end, m.get("slug"), m.get("condition_id"),
         m.get("token_up"), m.get("token_down"), created_at),
    )
    conn.commit()


def set_strike(conn, window_start, binance, pyth, ts):
    conn.execute(
        "UPDATE windows SET strike_binance=?, strike_pyth=?, strike_ts=? WHERE window_start=?",
        (binance, pyth, ts, window_start),
    )
    conn.commit()


def set_final(conn, window_start, binance, pyth, ts):
    our = None
    row = conn.execute(
        "SELECT strike_binance FROM windows WHERE window_start=?", (window_start,)
    ).fetchone()
    if row and row[0] is not None and binance is not None:
        our = "Up" if binance >= row[0] else "Down"
    conn.execute(
        "UPDATE windows SET final_binance=?, final_pyth=?, final_ts=?, our_outcome=? WHERE window_start=?",
        (binance, pyth, ts, our, window_start),
    )
    conn.commit()


def unsettled_windows(conn, before_ts):
    """Window starts for markets that have closed but have no official
    resolution recorded yet — used to backfill settlement after a restart."""
    rows = conn.execute(
        "SELECT window_start FROM windows WHERE resolved_outcome IS NULL AND window_end < ?",
        (before_ts,),
    ).fetchall()
    return [r[0] for r in rows]


def set_resolution(conn, window_start, outcome):
    conn.execute(
        "UPDATE windows SET resolved_outcome=? WHERE window_start=?",
        (outcome, window_start),
    )
    conn.commit()


def mark_partial(conn, window_start):
    conn.execute(
        "UPDATE windows SET partial=1 WHERE window_start=?", (window_start,)
    )
    conn.commit()


def insert_snapshot(conn, window_start, ts, ts_utc, time_left, up, down, binance, pyth):
    conn.execute(
        """INSERT INTO snapshots (window_start, ts, ts_utc, time_left,
               up_bid, up_ask, up_mid, up_spread,
               down_bid, down_ask, down_mid, down_spread,
               up_book, down_book, price_binance, price_pyth)
           VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?)""",
        (window_start, ts, ts_utc, time_left,
         up.get("best_bid"), up.get("best_ask"), up.get("mid"), up.get("spread"),
         down.get("best_bid"), down.get("best_ask"), down.get("mid"), down.get("spread"),
         json.dumps({"bids": up.get("bids"), "asks": up.get("asks")}),
         json.dumps({"bids": down.get("bids"), "asks": down.get("asks")}),
         binance, pyth),
    )
    conn.commit()

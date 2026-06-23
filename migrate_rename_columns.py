"""One-time migration: rename the misleading btc_* DB names to coin-neutral price_*.

  snapshots.btc_binance -> price_binance
  snapshots.btc_pyth    -> price_pyth
  table btc_ticks       -> price_ticks   (legacy index idx_btc_recv dropped; the schema
                                          recreates idx_price_recv on next collector start)

Run with the collectors STOPPED (so the DBs aren't locked). Idempotent — skips anything already
renamed. Covers every data/<coin>/live.db + archives. SQLite RENAME COLUMN/TABLE is a metadata-
only op (instant, even on the 60GB BTC DB).

    python migrate_rename_columns.py --dry-run    # show what would change
    python migrate_rename_columns.py              # do it
"""

import os
import sys
import sqlite3
import argparse

import coins


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _has(conn, kind, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
                             (kind, name)).fetchone())


def migrate(db, dry):
    conn = sqlite3.connect(db)
    changes = []
    try:
        sc = _cols(conn, "snapshots") if _has(conn, "table", "snapshots") else []
        if "btc_binance" in sc and "price_binance" not in sc:
            changes.append("ALTER TABLE snapshots RENAME COLUMN btc_binance TO price_binance")
        if "btc_pyth" in sc and "price_pyth" not in sc:
            changes.append("ALTER TABLE snapshots RENAME COLUMN btc_pyth TO price_pyth")
        if _has(conn, "table", "btc_ticks") and not _has(conn, "table", "price_ticks"):
            changes.append("ALTER TABLE btc_ticks RENAME TO price_ticks")
        if _has(conn, "index", "idx_btc_recv"):
            changes.append("DROP INDEX idx_btc_recv")
        for sql in changes:
            print(("DRY " if dry else "  ") + f"{os.path.relpath(db)}: {sql}")
            if not dry:
                conn.execute(sql)
        if not dry:
            conn.commit()
    finally:
        conn.close()
    return len(changes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dbs = sorted({db for c in coins.COINS for db in coins.all_dbs(c)})
    print(f"{len(dbs)} db(s) to check")
    total = sum(migrate(db, args.dry_run) for db in dbs)
    print(f"\n{'(dry run) ' if args.dry_run else ''}{total} change(s) across {len(dbs)} db(s)")
    if total == 0:
        print("nothing to do (already migrated?)")


if __name__ == "__main__":
    main()

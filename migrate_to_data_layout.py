"""One-time migration: move legacy BTC data into the per-coin data/ layout.

    btc_updown.db (+ -wal/-shm)  ->  data/btc/live.db (+ -wal/-shm)
    old_dbs/*.db                 ->  data/btc/archive/

Run ONCE, with all collectors STOPPED (create the STOP file or stop the supervisor
first) so the SQLite file isn't open. Safe: aborts if data/btc/live.db already
exists so it can't clobber an already-migrated DB.

    python migrate_to_data_layout.py --dry-run   # show what would move
    python migrate_to_data_layout.py             # do it
"""

import os
import sys
import glob
import shutil
import argparse

import coins

HERE = os.path.dirname(os.path.abspath(__file__))
LEGACY_LIVE = os.path.join(HERE, "btc_updown.db")
LEGACY_ARCHIVE = os.path.join(HERE, "old_dbs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    coins.ensure_dirs("btc")
    target_live = os.path.join(coins.coin_dir("btc"), "live.db")

    moves = []
    for suf in ("", "-wal", "-shm"):          # the DB + its WAL/SHM sidecars
        src = LEGACY_LIVE + suf
        if os.path.exists(src):
            moves.append((src, target_live + suf))
    for src in sorted(glob.glob(os.path.join(LEGACY_ARCHIVE, "*.db"))):
        moves.append((src, os.path.join(coins.archive_dir("btc"), os.path.basename(src))))

    if not moves:
        print("nothing to migrate (no legacy btc_updown.db / old_dbs/*.db found).")
        return
    if os.path.exists(target_live) and not dry:
        print(f"ABORT: {target_live} already exists -- migration looks done already.\n"
              f"  (remove it deliberately if you really mean to re-migrate.)")
        sys.exit(1)

    for src, dst in moves:
        rel = lambda p: os.path.relpath(p, HERE)
        print(("DRY " if dry else "") + f"move  {rel(src)}  ->  {rel(dst)}")
        if not dry:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)

    if dry:
        print("\n(dry run -- nothing moved)")
        return
    try:                                       # tidy an emptied old_dbs/
        if os.path.isdir(LEGACY_ARCHIVE) and not os.listdir(LEGACY_ARCHIVE):
            os.rmdir(LEGACY_ARCHIVE)
    except OSError:
        pass
    print("\ndone -- BTC data now lives in data/btc/. Restart the supervisor "
          "(python supervisor.py) to launch all six coins.")


if __name__ == "__main__":
    main()

"""Live PAPER-trading harness — drive the execution engine off the REAL stream.

Places a simulated resting limit BUY on the current live 5-min window's chosen
outcome, with an auto-sell at a target, then feeds the live trade prints (from the
collector's DB) into the PaperBroker so you can watch it queue, fill, and exit in
real time. NOTHING REAL IS TRADED — this is the safe way to validate the engine
and a rule against live data before any live wiring.

    python paper_trade.py --outcome down --price 0.22 --size 30 --exit 0.33

Requires the collectors to be running (so the DB has live book_events + trades).
"""

import os
import sys
import time
import json
import sqlite3
import argparse

import feeds
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from exec_engine.model import Side

import coins
DB_PATH = coins.live_db("btc")
WINDOW_SECONDS = 300


def latest_book(conn, token_id):
    row = conn.execute(
        "SELECT payload FROM book_events WHERE asset_id=? AND event_type='book' "
        "ORDER BY id DESC LIMIT 1", (token_id,)).fetchone()
    if not row:
        return None
    try:
        d = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    return d


def queue_ahead_for_buy(conn, token_id, price, tick=0.01):
    """Resting bid size at our price = the queue we sit behind (RiskAverse)."""
    book = latest_book(conn, token_id)
    if not book:
        return 0.0
    total = 0.0
    for lvl in book.get("bids", []):
        try:
            if abs(float(lvl["price"]) - price) < tick / 2:
                total += float(lvl["size"])
        except (KeyError, ValueError, TypeError):
            pass
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcome", choices=["up", "down"], default="down")
    ap.add_argument("--price", type=float, default=0.22)
    ap.add_argument("--size", type=float, default=30.0)
    ap.add_argument("--exit", type=float, default=0.33, dest="exit_price")
    ap.add_argument("--poll", type=float, default=1.0)
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH} — start the collectors first.")
        return

    now = time.time()
    start = int(now // WINDOW_SECONDS * WINDOW_SECONDS)
    end = start + WINDOW_SECONDS
    try:
        market = feeds.fetch_market(start)
    except Exception as e:
        print(f"could not fetch live market: {e!r}")
        return
    if not market:
        print(f"live market {start} not available yet; try again in a few seconds.")
        return
    token = market["token_up"] if args.outcome == "up" else market["token_down"]
    print(f"live window {start} ({market.get('slug')}); {args.outcome.upper()} token "
          f"{token[:12]}...  resolves in {end-now:.0f}s")

    conn = sqlite3.connect(DB_PATH, timeout=5)
    cfg = SafetyConfig()                     # paper, conservative
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg)

    qa = queue_ahead_for_buy(conn, token, args.price)
    print(f"queue ahead at {args.price}: {qa:.0f} shares (RiskAverse — fills only after this clears)")
    mgr.place_entry(token, price=args.price, size=args.size, exit_price=args.exit_price,
                    window_start=start, queue_ahead=qa)

    last_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM trades").fetchone()[0]
    print("watching live trades... (Ctrl-C to stop)\n")
    try:
        while True:
            rows = conn.execute(
                "SELECT id, price, size, side FROM trades WHERE asset_id=? AND id>? "
                "ORDER BY id", (token, last_id)).fetchall()
            for rid, price, size, side in rows:
                last_id = rid
                if price is None or size is None:
                    continue
                broker.on_trade(token, float(price), float(size), side)
            if time.time() > end + 5:
                print("\nwindow ended.")
                break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        print("final:", broker.summary())
        conn.close()


if __name__ == "__main__":
    main()

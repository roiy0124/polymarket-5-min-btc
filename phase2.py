"""Phase 2 — paper executor (live forward-test of validated signals).

Reads signals.json and, every 5-minute window, trades each signal whose predicted
EV clears your floor: at the signal's buy-window it rests a SIMULATED BUY at the
entry price (with an auto-sell at the target attached), cancels it if unfilled by
the window's end, and settles any held position to 1.0/0.0 at resolution. Fills are
simulated by the PaperBroker against the REAL trade stream the collectors record,
using the conservative RiskAverse queue model. NOTHING REAL IS TRADED.

    python phase2.py --min-ev 0.5

This is the honest, out-of-sample test of the Phase-1 signals: it measures the real
(adverse-selection-adjusted) fill rate and PnL so we can compare paper-vs-predicted
BEFORE any live wiring. Requires the collectors running (DB has live trades+books).
Ctrl-C to stop. Every settled leg is appended to paper_trades.csv.
"""

import os
import csv
import sys
import json
import time
import sqlite3
import argparse

import feeds
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from exec_engine.strategy_runner import StrategyRunner, WINDOW

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "btc_updown.db")
SIGNALS = os.path.join(HERE, "signals.json")
LEDGER = os.path.join(HERE, "paper_trades.csv")
FIELDS = ["window_start", "side", "entry_z", "buy_filled", "fill_px", "sell_T",
          "sell_filled", "exit_or_settle_px", "realized_pnl", "ev_predicted",
          "won", "shares", "bought", "sold"]


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def get_market(conn, ws):
    """Tokens for a window: from the DB first (collector already wrote them),
    falling back to a live fetch if this window isn't in the DB yet."""
    row = conn.execute("SELECT token_up, token_down, slug FROM windows "
                       "WHERE window_start=?", (ws,)).fetchone()
    if row and row[0] and row[1]:
        return {"token_up": row[0], "token_down": row[1], "slug": row[2]}
    try:
        m = feeds.fetch_market(ws)
        return m or None
    except Exception as e:
        log(f"  could not fetch market {ws}: {e!r}")
        return None


def book_queue(conn, token, price, side, tick=0.01):
    """Resting size at `price` on the side we'd sit behind (RiskAverse queue):
    bids for our BUY, asks for our SELL. Reads the latest 'book' event."""
    row = conn.execute("SELECT payload FROM book_events WHERE asset_id=? "
                       "AND event_type='book' ORDER BY id DESC LIMIT 1", (token,)).fetchone()
    if not row:
        return 0.0
    try:
        d = json.loads(row[0])
    except (ValueError, TypeError):
        return 0.0
    levels = d.get("bids" if side == "BUY" else "asks", []) or []
    total = 0.0
    for lvl in levels:
        try:
            p, sz = float(lvl["price"]), float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            try:
                p, sz = float(lvl[0]), float(lvl[1])      # tolerate [p, s] form
            except (IndexError, TypeError, ValueError):
                continue
        if abs(p - price) < tick / 2:
            total += sz
    return total


def append_ledger(rows):
    new = not os.path.exists(LEDGER) or os.path.getsize(LEDGER) == 0
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ev", type=float, default=0.5, dest="min_ev",
                    help="only trade signals with predicted EV/$1 above this")
    ap.add_argument("--signals", default=SIGNALS)
    ap.add_argument("--poll", type=float, default=1.0)
    args = ap.parse_args()

    if not os.path.exists(args.signals):
        print(f"no signals file at {args.signals} — run the Phase-1 finder first "
              f"(menu 7 / python -m analysis.signals).")
        return
    with open(args.signals) as f:
        data = json.load(f)
    signals = data.get("signals", [])
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH} — start the collectors first.")
        return

    # Paper SafetyConfig: relax the $5 live minimum so real ~$1-2 bets trade; the
    # full live caps stay reserved for the LiveBroker path.
    cfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg, logger=log)
    runner = StrategyRunner(mgr, broker, signals, args.min_ev,
                            queue_fn=lambda t, p, s: book_queue(conn, t, p, s), log=log)

    eligible = len(runner.signals)
    print("=" * 70)
    print(f"Phase 2 PAPER executor | {eligible}/{len(signals)} signals with ev > {args.min_ev:+.2f}")
    print(f"  ledger -> {LEDGER}   (NOTHING REAL IS TRADED — Ctrl-C to stop)")
    print("=" * 70)
    if not eligible:
        print("  no signal clears the EV floor — lower --min-ev or regenerate signals.json.")
        return

    cur_window = None
    last_id = {}                 # token -> last trades.id fed
    tot_pnl = 0.0
    n_settled = n_filled = 0
    try:
        while True:
            now = time.time()
            w = int(now // WINDOW * WINDOW)
            if w != cur_window:
                market = get_market(conn, w)
                if market:
                    for leg in runner.start_window(w, market):
                        last_id.setdefault(leg.token, 0)
                else:
                    log(f"[window {w}] no market yet — skipping this round")
                cur_window = w

            # feed new trade prints into the paper broker for every active token
            for token in runner.active_tokens():
                lid = last_id.get(token, 0)
                rows = conn.execute(
                    "SELECT id, price, size, side FROM trades WHERE asset_id=? AND id>? "
                    "ORDER BY id", (token, lid)).fetchall()
                for rid, price, size, side in rows:
                    last_id[token] = rid
                    if price is not None and size is not None and side:
                        broker.on_trade(token, float(price), float(size), side)

            runner.on_tick(now)

            # settle any closed window whose official resolution has landed
            for ws in [x for x in list(runner.windows) if x < cur_window]:
                row = conn.execute("SELECT resolved_outcome FROM windows WHERE window_start=?",
                                   (ws,)).fetchone()
                outcome = row[0] if row else None
                if outcome in ("Up", "Down"):
                    rows = runner.settle_window(ws, outcome)
                    if rows:
                        append_ledger(rows)
                        for r in rows:
                            tot_pnl += r["realized_pnl"]
                            n_settled += 1
                            n_filled += r["buy_filled"]
                        log(f"[settled {ws} {outcome}] {len(rows)} leg(s) | "
                            f"cum: {n_settled} legs, {n_filled} filled, pnl {tot_pnl:+.2f}")
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        fill_rate = (n_filled / n_settled * 100) if n_settled else 0.0
        print(f"\nPAPER session: {n_settled} legs settled, {n_filled} filled "
              f"({fill_rate:.0f}% fill), cumulative pnl {tot_pnl:+.3f}")
        print(f"full ledger: {LEDGER}")
        conn.close()


if __name__ == "__main__":
    main()

"""Signal-decay experiment (PAPER, standalone -- intentionally NOT in the menu).

Hypothesis under test: the overnight run showed the edge was strong for ~1h after
signal generation, then decayed. This script keeps signals FRESH by re-running the
Phase-1 finder every REFRESH_MIN minutes and re-arming with the new set, trading
only signals with predicted EV >= MIN_EV. Everything is simulated by PaperBroker --
NOTHING REAL IS TRADED.

Each refresh writes a NEW generation timestamp, so every leg is stamped with the
sig_gen that was active when its window was armed. Analyze with:

    python -m analysis.paper_ledger --ledger experiment_trades.csv

The --by-epoch view then shows one block per 30-min generation: if freshly-armed
signals are consistently profitable in their first ~30min across many epochs, the
short-lived edge is real; if hour-1 profitability is itself inconsistent, it's
overfitting to recent data.

    python experiment_refresh.py                 # defaults: EV>=0.3, refresh 30min
    python experiment_refresh.py --min-ev 0.3 --refresh-min 30

Requires the collectors running (live trades + books + window resolutions in the DB).
Ctrl-C to stop. Appends experiment_trades.csv.
"""

import os
import csv
import sys
import json
import time
import sqlite3
import argparse
import subprocess

from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from exec_engine.strategy_runner import StrategyRunner, WINDOW
from phase2 import get_market, book_queue, FIELDS as BASE_FIELDS

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "btc_updown.db")
SIGNALS = os.path.join(HERE, "signals.json")
LEDGER = os.path.join(HERE, "experiment_trades.csv")   # separate from paper_trades.csv
FIELDS = BASE_FIELDS if "sig_gen" in BASE_FIELDS else BASE_FIELDS + ["sig_gen"]


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def refresh_signals(scope_days):
    """Re-run the Phase-1 finder (reusing prior floors from signals.json) over the
    given data scope and return (signals, generated_ts). The scope is REQUIRED: the
    live DB may be freshly reset, so the finder must merge old_dbs/ via
    BTC_ANALYSIS_DAYS to have enough resolved windows -- without it, it loads 0
    windows and silently keeps the stale signals.json."""
    meta = {}
    if os.path.exists(SIGNALS):
        try:
            with open(SIGNALS) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    cmd = [sys.executable, "-m", "analysis.signals",
           "--min-win", str(meta.get("min_win", 0.70)),
           "--min-roi", str(meta.get("min_roi", 0.30)),
           "--usd", str(meta.get("usd", 2)),
           "--min-entry", str(meta.get("min_entry", 0.10)),
           "--min-ev", str(meta.get("min_ev", 0.10)),
           "--min-dots", str(meta.get("min_dots", 8)),
           "--min-frac", str(meta.get("min_frac", 0.20))]
    env = dict(os.environ)
    env["BTC_ANALYSIS_DAYS"] = str(scope_days)
    subprocess.run(cmd, cwd=HERE, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(SIGNALS) as f:
        data = json.load(f)
    return data.get("signals", []), data.get("generated")


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
    ap.add_argument("--min-ev", type=float, default=0.3, dest="min_ev",
                    help="only trade signals with predicted EV/$1 above this")
    ap.add_argument("--refresh-min", type=float, default=30.0, dest="refresh_min",
                    help="re-run the finder every N minutes")
    ap.add_argument("--scope-days", type=float, default=1.0, dest="scope_days",
                    help="data scope for the finder (merges old_dbs/); needs >=1 for "
                         "the 24h robustness lookback")
    ap.add_argument("--poll", type=float, default=1.0)
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH} -- start the collectors first.")
        return

    cfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)   # paper caps (like phase2)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg, logger=log)

    log(f"initial signal refresh (EV>={args.min_ev}, every {args.refresh_min:g}min, "
        f"scope {args.scope_days:g}d)...")
    signals, sig_gen = refresh_signals(args.scope_days)
    runner = StrategyRunner(mgr, broker, signals, args.min_ev,
                            queue_fn=lambda t, p, s: book_queue(conn, t, p, s), log=log)
    log(f"armed set: {len(runner.signals)}/{len(signals)} signals clear EV>{args.min_ev:+.2f} "
        f"(gen {sig_gen})")

    print("=" * 70)
    print(f"DECAY EXPERIMENT (PAPER) | EV>={args.min_ev} | refresh {args.refresh_min:g}min "
          f"| ledger -> {os.path.basename(LEDGER)}")
    print("  NOTHING REAL IS TRADED -- Ctrl-C to stop")
    print("=" * 70)

    cur_window = None
    last_id = {}
    last_refresh = time.time()
    window_gen = {}            # window_start -> sig_gen active when it was armed
    tot_pnl = 0.0
    n_settled = n_filled = 0
    try:
        while True:
            now = time.time()

            # periodic refresh: re-run the finder, re-arm future windows with the
            # new set. In-flight windows keep the signals they were armed with.
            if now - last_refresh >= args.refresh_min * 60:
                signals, sig_gen = refresh_signals(args.scope_days)
                runner.signals = [s for s in signals if s.get("ev", 0.0) > args.min_ev]
                last_refresh = now
                log(f"REFRESH -> {len(runner.signals)} signals clear EV>{args.min_ev:+.2f} "
                    f"(gen {sig_gen})")

            w = int(now // WINDOW * WINDOW)
            if w != cur_window:
                market = get_market(conn, w)
                if market:
                    for leg in runner.start_window(w, market):
                        last_id.setdefault(leg.token, 0)
                    window_gen[w] = sig_gen        # stamp this window's generation
                else:
                    log(f"[window {w}] no market yet -- skipping")
                cur_window = w

            # feed new trade prints into the paper broker for active tokens
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

            # settle closed windows with an official resolution
            for ws in [x for x in list(runner.windows) if x < cur_window]:
                row = conn.execute("SELECT resolved_outcome FROM windows WHERE window_start=?",
                                   (ws,)).fetchone()
                outcome = row[0] if row else None
                if outcome in ("Up", "Down"):
                    rows = runner.settle_window(ws, outcome)
                    if rows:
                        gen = window_gen.pop(ws, sig_gen)
                        for r in rows:
                            r["sig_gen"] = gen
                            tot_pnl += r["realized_pnl"]
                            n_settled += 1
                            n_filled += r["buy_filled"]
                        append_ledger(rows)
                        log(f"[settled {ws} {outcome}] {len(rows)} leg(s) | "
                            f"cum: {n_settled} legs, {n_filled} filled, pnl {tot_pnl:+.2f}")
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        fill_rate = (n_filled / n_settled * 100) if n_settled else 0.0
        print(f"\nEXPERIMENT: {n_settled} legs settled, {n_filled} filled "
              f"({fill_rate:.0f}% fill), cumulative pnl {tot_pnl:+.3f}")
        print(f"analyze: python -m analysis.paper_ledger --ledger {os.path.basename(LEDGER)}")
        conn.close()


if __name__ == "__main__":
    main()

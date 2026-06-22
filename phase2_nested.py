"""Phase 2 (nested) -- PAPER executor for the nested gap->time strategy.

Forward-test of the strategy we converged on:
  * fixed lookback combo 24/16/8h (the robustness anchor),
  * every 30 min, RE-FIT the per-(side,entry) signals on all data so far: find the
    gap BUY-zone (best_conditional), filter dots to it, fit the time sell-line
    (best_sell_window) on the filtered subset, keep it only if EV>0, it clears the
    dynamic too-thin guard, and the line holds EV>0 across all three lookbacks,
  * trade live windows with PaperBroker (realistic queue fills), but only PLACE a
    leg when the LIVE BTC gap (btc - strike) is inside that signal's zone.

NOTHING REAL IS TRADED. This is a forward test -- the nested+24/16/8 edge is only a
marginal, unconfirmed ~+0.02 EV/$1 in backtest (gross of fees); running it in paper
is how we validate it as more data accumulates. Appends paper_nested_trades.csv.

    python phase2_nested.py            # needs the collectors running

Ctrl-C to stop.
"""

import os
import csv
import math
import time
import sqlite3

from phase2 import get_market, book_queue, FIELDS
from experiment_combined import load_full
from experiment_walkforward import open_merged
from analysis.exit_maps import best_conditional, best_sell_window, entry_and_exit, entry_margin
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from exec_engine.strategy_runner import StrategyRunner, WINDOW

import coins
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = coins.live_db("btc")
LEDGER = os.path.join(HERE, "paper_nested_trades.csv")
COMBO = (8, 16, 24)
ENTRY_LO, ENTRY_HI = 5, 75
USD = 2.0
FILT_FRAC = 0.10
REFRESH = 1800.0


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def _eval_line(xy, z, t1, t2, T):
    sub = [y for x, y in xy if t1 <= x <= t2]
    if len(sub) < 5:
        return None
    reach = sum(1 for y in sub if y >= T - 1e-9) / len(sub)
    return reach * (T - z) / z - (1.0 - reach)


def generate_nested_signals(now):
    """Re-fit nested signals on all data closed before `now`. Returns list of dicts
    {side, entry, sell, t1, t2, shares, zones, ev}."""
    conn, _ = open_merged()
    windows = load_full(conn)
    conn.close()
    longest = max(COMBO)
    sigs = []
    for side in ("up", "down"):
        for c in range(ENTRY_LO, ENTRY_HI + 1):
            z = c / 100.0
            dots = []
            for w in windows:
                if w["ws"] + WINDOW > now:
                    continue
                won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
                eb = entry_and_exit(w[side], c, won)
                if eb is None:
                    continue
                dots.append((w["ws"], eb[0], eb[1], entry_margin(w[side], c)))
            if len(dots) < 24:
                continue
            mdots = [(g, y, "x") for (ws, x, y, g) in dots if g is not None]
            bc = best_conditional(mdots, z)
            if not bc:
                continue
            zones = bc[2]

            def fsub(L):
                cut = now - L * 3600
                return [(x, y) for (ws, x, y, g) in dots
                        if ws >= cut and g is not None and any(a <= g <= b for a, b in zones)]

            # dynamic guard scaled to the LONGEST-lookback dots (NOT all history, which
            # would grow without bound and reject every line as data accumulates)
            n_long = sum(1 for (ws, x, y, g) in dots if ws >= now - longest * 3600)
            floor = math.ceil(FILT_FRAC * n_long)
            bw = best_sell_window(fsub(longest), z)
            if not (bw and bw[5] > 0 and bw[2] > z and bw[6] >= floor):
                continue
            if not all((_eval_line(fsub(L), z, bw[0], bw[1], bw[2]) or -9) > 0 for L in COMBO):
                continue
            sigs.append({"side": side, "entry": z, "sell": bw[2], "t1": bw[0], "t2": bw[1],
                         "shares": round(USD / z, 2), "zones": zones, "ev": round(bw[5], 4)})
    return sigs


def append_ledger(rows):
    new = not os.path.exists(LEDGER) or os.path.getsize(LEDGER) == 0
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH} -- start the collectors first.")
        return
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)   # paper caps
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg, logger=log)

    def place_gate(leg):
        """Place only if the live BTC gap for this window is inside the signal's zone."""
        zones = leg.sig.get("zones") or []
        row = conn.execute("SELECT strike_binance FROM windows WHERE window_start=?",
                           (leg.ws,)).fetchone()
        if not row or row[0] is None:
            return False
        btc = conn.execute("SELECT btc_binance FROM snapshots WHERE window_start=? AND "
                           "btc_binance IS NOT NULL ORDER BY ts DESC LIMIT 1",
                           (leg.ws,)).fetchone()
        if not btc or btc[0] is None:
            return False
        gap = btc[0] - row[0]
        return any(a <= gap <= b for a, b in zones)

    runner = StrategyRunner(mgr, broker, [], min_ev=-1e9,
                            queue_fn=lambda t, p, s: book_queue(conn, t, p, s),
                            log=log, place_gate=place_gate)

    print("=" * 70)
    print(f"Phase 2 NESTED paper executor | combo {COMBO} | entries {ENTRY_LO}-{ENTRY_HI}c "
          f"| refit 30min")
    print(f"  ledger -> {LEDGER}   (NOTHING REAL IS TRADED -- Ctrl-C to stop)")
    print("  forward-test of a MARGINAL/unconfirmed edge (~+0.02 backtest, gross of fees)")
    print("=" * 70)

    log("initial signal fit...")
    sig_gen = time.time()
    runner.signals = generate_nested_signals(sig_gen)
    log(f"fitted {len(runner.signals)} nested signals")

    cur_window = None
    last_id = {}
    last_refresh = sig_gen
    tot_pnl = 0.0
    n_settled = n_filled = 0
    try:
        while True:
            now = time.time()
            if now - last_refresh >= REFRESH:
                sig_gen = now
                runner.signals = generate_nested_signals(sig_gen)
                last_refresh = now
                log(f"REFIT -> {len(runner.signals)} nested signals (gen {sig_gen:.0f})")
            w = int(now // WINDOW * WINDOW)
            if w != cur_window:
                market = get_market(conn, w)
                if market:
                    for leg in runner.start_window(w, market):
                        last_id.setdefault(leg.token, 0)
                else:
                    log(f"[window {w}] no market yet -- skipping")
                cur_window = w
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
            for ws in [x for x in list(runner.windows) if x < cur_window]:
                row = conn.execute("SELECT resolved_outcome FROM windows WHERE window_start=?",
                                   (ws,)).fetchone()
                outcome = row[0] if row else None
                if outcome in ("Up", "Down"):
                    rows = runner.settle_window(ws, outcome)
                    if rows:
                        for r in rows:
                            r["sig_gen"] = sig_gen
                            tot_pnl += r["realized_pnl"]
                            n_settled += 1
                            n_filled += r["buy_filled"]
                        append_ledger(rows)
                        log(f"[settled {ws} {outcome}] {len(rows)} leg(s) | cum: {n_settled} "
                            f"legs, {n_filled} filled, pnl {tot_pnl:+.2f}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        fr = (n_filled / n_settled * 100) if n_settled else 0.0
        print(f"\nNESTED PAPER: {n_settled} legs settled, {n_filled} filled ({fr:.0f}% fill), "
              f"cumulative pnl {tot_pnl:+.3f}")
        print(f"analyze: python -m analysis.paper_ledger --ledger {os.path.basename(LEDGER)}")
        conn.close()


if __name__ == "__main__":
    main()

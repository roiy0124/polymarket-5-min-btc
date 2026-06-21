"""Phase 3 -- LIVE executor (REAL money on Polymarket).  *** UNTESTED ***

This is the live sibling of phase2.py. It reuses the EXACT same spine -- the same
signals.json, StrategyRunner state machine, OrderManager auto-sell, and settlement
-- and changes only the three things that must differ from paper (see EXECUTION.md
and the live-trading reference):

  1. broker      : LiveBroker(cfg, creds) + SafetyConfig(live=True)  (real CLOB orders)
  2. fill source : the AUTHENTICATED user channel (UserStream), gated on CONFIRMED
                   -- NOT the public trade stream, and NOT MATCHED (a MATCHED trade
                   can still FAIL and would leave us short if we sold against it).
  3. safety      : file kill-switch, structured per-event log, periodic reconcile.

SAFETY MODEL -- this file cannot spend money by accident:
  * Default mode is --connectivity: read-only (auth + list orders/trades/balances).
    It places NO orders. Run this FIRST once your EOA is funded.
  * Real trading requires BOTH --arm AND the env var LIVE_RUNNER_CONFIRM=I_UNDERSTAND.
    Without both it refuses and exits.
  * Even armed, every order still passes SafetyConfig.validate (price/tick/notional)
    and the account caps (max position, daily loss, max open orders).

  python live_runner.py --connectivity          # read-only; do this first
  python live_runner.py --arm --min-ev 0.5      # REAL orders (needs LIVE_RUNNER_CONFIRM)

Credentials are read from environment (or a local, git-ignored .env):
  POLY_PRIVATE_KEY   the EOA private key (0x...). DEDICATED wallet only.
  POLY_FUNDER        usually the SAME EOA address (defaults to the key's address).

DO NOT flip this on for real running until the edge clears the validation bar
(see memory paper-edge-not-yet-validated). Plumbing first, money later.
"""

import os
import csv
import sys
import json
import time
import queue
import sqlite3
import argparse
import threading

import feeds
from exec_engine.config import SafetyConfig
from exec_engine.broker import LiveBroker
from exec_engine.order_manager import OrderManager
from exec_engine.strategy_runner import StrategyRunner, WINDOW
from exec_engine.model import OrderStatus

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "btc_updown.db")
SIGNALS = os.path.join(HERE, "signals.json")
LEDGER = os.path.join(HERE, "live_trades.csv")       # separate from paper_trades.csv
EVENTLOG = os.path.join(HERE, "live_runner.log")     # structured JSON, one event/line
KILL_FILE = os.path.join(HERE, "KILL")               # touch this to halt instantly
RECONCILE_SEC = 60.0
FIELDS = ["window_start", "side", "entry_z", "buy_filled", "fill_px", "sell_T",
          "sell_filled", "exit_or_settle_px", "realized_pnl", "ev_predicted",
          "won", "shares", "bought", "sold", "sig_gen"]


# --- structured logging ------------------------------------------------------

def log_event(event, **fields):
    """One JSON object per line to EVENTLOG, plus a human line to stdout."""
    rec = {"ts": time.time(), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "event": event, **fields}
    try:
        with open(EVENTLOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"{time.strftime('%H:%M:%S')} [{event}] {extra}", flush=True)


# --- credentials -------------------------------------------------------------

def load_env_file(path=os.path.join(HERE, ".env")):
    """Minimal .env loader (stdlib only). KEY=VALUE per line; # comments ignored.
    Does not overwrite already-set environment variables."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_credentials():
    pk = os.environ.get("POLY_PRIVATE_KEY")
    if not pk:
        return None
    funder = os.environ.get("POLY_FUNDER") or None  # proxy/deposit addr for type 1/2
    sigtype = int(os.environ.get("POLY_SIGNATURE_TYPE", "0"))  # 0 EOA | 1 PROXY | 2 SAFE
    return {"private_key": pk, "funder": funder, "signature_type": sigtype,
            "neg_risk": False}


# --- read-only connectivity check (places NO orders) -------------------------

def connectivity_check(creds):
    """Authenticate and read account state without placing anything. This is the
    convergence point: run it once the EOA is funded + allowances set."""
    log_event("connectivity_start")
    try:
        from py_clob_client.client import ClobClient
    except ImportError:
        print("py-clob-client not installed. pip install -r requirements-exec.txt")
        return False
    try:
        client = ClobClient("https://clob.polymarket.com", key=creds["private_key"],
                            chain_id=137, signature_type=creds["signature_type"],
                            funder=creds["funder"])
        client.set_api_creds(client.create_or_derive_api_creds())
        addr = getattr(client, "get_address", lambda: "?")()
        log_event("auth_ok", signer_address=addr, funder=creds["funder"],
                  signature_type=creds["signature_type"])
    except Exception as e:
        log_event("auth_FAILED", error=repr(e))
        return False

    # Each probe is best-effort -- the exact method/return shape varies by SDK
    # version, so we never let one failure abort the others (EXECUTION.md: these
    # are the "still verify" items -- balances/allowances/fees).
    for name, fn in [
        ("open_orders", lambda: _safe(client, "get_orders")),
        ("recent_trades", lambda: _safe(client, "get_trades")),
        ("usdc_balance_allowance", lambda: _balance_allowance(client, creds["signature_type"])),
    ]:
        try:
            log_event(name, result=fn())
        except Exception as e:
            log_event(name + "_err", error=repr(e))
    log_event("connectivity_done",
              note="if usdc_allowance shows 0, set USDC+CTF approvals before trading")
    return True


def _safe(client, method):
    fn = getattr(client, method, None)
    if fn is None:
        return f"<no {method} on this SDK>"
    try:
        from py_clob_client.clob_types import OpenOrderParams
        return fn(OpenOrderParams()) if method == "get_orders" else fn()
    except TypeError:
        return fn()


def _balance_allowance(client, sigtype=0):
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        # signature_type matters: for a proxy (1/2) the balance lives at the proxy
        # address, not the signer -- omitting it reads 0 on a funded proxy account.
        p = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sigtype)
        return client.get_balance_allowance(p)
    except Exception as e:
        return f"<unavailable: {e!r}>"


# --- live fill routing: user-stream CONFIRMED -> OrderManager auto-sell -------

class FillRouter:
    """Translates authenticated user-channel 'trade' events into fills on our local
    Order objects, then drives the SAME OrderManager auto-sell path used in paper.

    *** UNTESTED *** the user-channel field names ('asset_id'/'status'/order-id keys)
    are confirmed-on-paper from the research but not yet against a live socket. We
    match defensively: by broker_order_id if the event carries one, else by
    (token, side, ~price) against our open orders. Only CONFIRMED fills act.
    """

    def __init__(self, broker, lock, log=log_event):
        self.broker = broker
        self.lock = lock
        self.log = log
        self.seen = set()   # (order_id, matched_amount) dedupe

    def on_fill(self, asset_id, price, size, side, status, raw):
        if status != "CONFIRMED":
            self.log("userfill_ignored", status=status, asset_id=asset_id, size=size)
            return
        with self.lock:
            order = self._match(asset_id, side, price, raw)
            if order is None:
                self.log("userfill_UNMATCHED", asset_id=asset_id, side=side,
                         price=price, size=size, raw_keys=list(raw.keys()))
                return
            key = (order.intent.client_id, raw.get("id") or raw.get("order_id"), size)
            if key in self.seen:
                return
            self.seen.add(key)
            qty = min(size or 0.0, order.remaining)
            if qty <= 1e-9:
                return
            order.filled_size += qty
            order.avg_price = price or order.intent.price
            order.status = (OrderStatus.FILLED if order.remaining <= 1e-9
                            else OrderStatus.PARTIALLY_FILLED)
            order.touch()
            self.log("userfill_CONFIRMED", tag=order.intent.tag,
                     client_id=order.intent.client_id, qty=qty, price=price)
            # reuse the proven auto-sell: this fires OrderManager._on_fill
            self.broker._emit_fill(order, qty, price or order.intent.price)

    def _match(self, asset_id, side, price, raw):
        oid = raw.get("order_id") or raw.get("id") or raw.get("taker_order_id")
        if oid:
            for o in self.broker.orders.values():
                if o.broker_order_id == oid:
                    return o
        for o in self.broker.orders.values():
            if o.is_terminal or o.intent.token_id != asset_id:
                continue
            if side and o.intent.side.value != side:
                continue
            if price is None or abs(o.intent.price - price) < 0.01:
                return o
        return None


def start_user_stream(creds, condition_ids, on_fill):
    """Run UserStream in a background thread (its own asyncio loop)."""
    import asyncio
    from py_clob_client.client import ClobClient
    from exec_engine.user_stream import UserStream

    client = ClobClient("https://clob.polymarket.com", key=creds["private_key"],
                        chain_id=137, signature_type=creds["signature_type"],
                        funder=creds["funder"])
    api = client.create_or_derive_api_creds()
    api_key = getattr(api, "api_key", None) or getattr(api, "apiKey", None)
    secret = getattr(api, "api_secret", None) or getattr(api, "secret", None)
    passphrase = getattr(api, "api_passphrase", None) or getattr(api, "passphrase", None)
    stream = UserStream(api_key, secret, passphrase, condition_ids, on_fill=on_fill)

    def _run():
        asyncio.new_event_loop().run_until_complete(stream.run())

    t = threading.Thread(target=_run, name="user-stream", daemon=True)
    t.start()
    return stream


# --- ledger ------------------------------------------------------------------

def append_ledger(rows):
    new = not os.path.exists(LEDGER) or os.path.getsize(LEDGER) == 0
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def get_market(conn, ws):
    row = conn.execute("SELECT token_up, token_down, slug FROM windows "
                       "WHERE window_start=?", (ws,)).fetchone()
    if row and row[0] and row[1]:
        return {"token_up": row[0], "token_down": row[1], "slug": row[2]}
    try:
        return feeds.fetch_market(ws) or None
    except Exception as e:
        log_event("market_fetch_err", ws=ws, error=repr(e))
        return None


# --- the live loop -----------------------------------------------------------

def refresh_signals(signals_path):
    """Re-run the Phase-1 finder before trading so the bot always uses the freshest
    signals (same policy as the paper executor / menu). Reuses the prior floors and
    data scope recorded in signals.json; falls back to defaults if absent."""
    import subprocess
    meta = {}
    if os.path.exists(signals_path):
        try:
            with open(signals_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    cmd = [sys.executable, "-m", "analysis.signals",
           "--min-win", str(meta.get("min_win", 0.70)),
           "--min-roi", str(meta.get("min_roi", 0.50)),
           "--usd", str(meta.get("usd", 2)),
           "--min-entry", str(meta.get("min_entry", 0.10)),
           "--min-ev", str(meta.get("min_ev", 0.0)),
           "--min-dots", str(meta.get("min_dots", 8)),
           "--min-frac", str(meta.get("min_frac", 0.20))]
    env = dict(os.environ)
    if meta.get("scope_days"):
        env["BTC_ANALYSIS_DAYS"] = str(meta["scope_days"])
    log_event("refresh_signals", scope_days=meta.get("scope_days") or "current")
    subprocess.run(cmd, cwd=HERE, env=env)


def run_live(args, creds):
    if args.refresh:
        refresh_signals(args.signals)
    with open(args.signals) as f:
        data = json.load(f)
    signals = data.get("signals", [])
    sig_gen = data.get("generated")
    if not signals:
        print("signals.json has no signals. Run the finder first.")
        return

    # conservative caps -- start tiny. max_order_usd at the $5 minimum on day one.
    cfg = SafetyConfig(live=True, min_order_usd=5.0, max_order_usd=args.max_order_usd,
                       max_position_usd=args.max_position_usd,
                       daily_loss_limit_usd=args.daily_loss_usd)
    broker = LiveBroker(cfg, credentials=creds)
    lock = threading.RLock()
    mgr = OrderManager(broker, cfg, logger=lambda m: log_event("om", msg=m))
    runner = StrategyRunner(mgr, broker, signals, args.min_ev,
                            queue_fn=lambda t, p, s: 0.0,  # live: queue unknown; no sim
                            log=lambda m: log_event("runner", msg=m))
    if not runner.signals:
        print("no signal clears the EV floor; raise data or lower --min-ev.")
        return

    router = FillRouter(broker, lock)
    conn = sqlite3.connect(DB_PATH, timeout=10)

    log_event("LIVE_START", signals=len(runner.signals), min_ev=args.min_ev,
              max_order_usd=cfg.max_order_usd, max_position_usd=cfg.max_position_usd,
              daily_loss_usd=cfg.daily_loss_limit_usd, sig_gen=sig_gen)
    print("\n*** LIVE MODE ARMED -- REAL ORDERS WILL BE PLACED ***")
    print(f"    caps: order<=${cfg.max_order_usd}  position<=${cfg.max_position_usd}  "
          f"daily-loss<=${cfg.daily_loss_limit_usd}")
    print(f"    kill switch: create the file {KILL_FILE} to halt instantly.\n")

    cur_window = None
    subscribed = set()
    stream = None
    last_reconcile = 0.0
    tot_pnl = 0.0
    try:
        while True:
            # 0) kill switch -- checked at the top of every loop
            if os.path.exists(KILL_FILE):
                log_event("KILL_SWITCH", action="cancel_all_and_halt")
                with lock:
                    cfg.kill_switch = True
                    mgr.cancel_all_entries()
                break

            now = time.time()
            w = int(now // WINDOW * WINDOW)
            if w != cur_window:
                market = get_market(conn, w)
                if market:
                    with lock:
                        runner.start_window(w, market)
                    # (re)subscribe the user stream to this window's tokens
                    toks = [market["token_up"], market["token_down"]]
                    if stream is None:
                        stream = start_user_stream(creds, toks, router.on_fill)
                        subscribed.update(toks)
                        log_event("user_stream_started", tokens=toks)
                    # NOTE: live re-subscription per window is a TODO -- UserStream
                    # currently subscribes once at connect. See KNOWN GAPS below.
                else:
                    log_event("no_market", ws=w)
                cur_window = w

            with lock:
                runner.on_tick(now)
                # settle any closed window that has an official resolution
                for ws in [x for x in list(runner.windows) if x < cur_window]:
                    row = conn.execute("SELECT resolved_outcome FROM windows "
                                       "WHERE window_start=?", (ws,)).fetchone()
                    outcome = row[0] if row else None
                    if outcome in ("Up", "Down"):
                        rows = runner.settle_window(ws, outcome)
                        for r in rows:
                            r["sig_gen"] = sig_gen
                            tot_pnl += r["realized_pnl"]
                        if rows:
                            append_ledger(rows)
                            log_event("settled", ws=ws, outcome=outcome,
                                      legs=len(rows), cum_pnl=round(tot_pnl, 3))

            # periodic reconciliation: broker is truth (UNTESTED -- see GAPS)
            if now - last_reconcile > RECONCILE_SEC:
                _reconcile(broker, lock)
                last_reconcile = now

            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nstopping -- cancelling open entries.")
        with lock:
            mgr.cancel_all_entries()
    finally:
        log_event("LIVE_STOP", cum_pnl=round(tot_pnl, 3))
        conn.close()


def _reconcile(broker, lock):
    """Pull broker truth and compare to local open orders. On any drift, log loudly.
    *** UNTESTED *** -- intentionally does NOT auto-correct; the rule is halt-and-
    inspect. Full position-drift handling is a KNOWN GAP."""
    try:
        client = broker._ensure_client()
        from py_clob_client.clob_types import OpenOrderParams
        remote = client.get_orders(OpenOrderParams())
    except Exception as e:
        log_event("reconcile_err", error=repr(e))
        return
    with lock:
        local_ids = {o.broker_order_id for o in broker.open_orders() if o.broker_order_id}
    remote_ids = {(r.get("id") or r.get("orderID")) for r in (remote or [])} if isinstance(remote, list) else set()
    only_remote = remote_ids - local_ids
    only_local = local_ids - remote_ids
    if only_remote or only_local:
        log_event("RECONCILE_DRIFT", only_remote=list(only_remote),
                  only_local=list(only_local), action="inspect_manually")
    else:
        log_event("reconcile_ok", open_orders=len(local_ids))


# --- entrypoint --------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="LIVE Polymarket executor (real money).")
    ap.add_argument("--connectivity", action="store_true",
                    help="read-only: authenticate and list orders/trades/balances; NO orders")
    ap.add_argument("--arm", action="store_true",
                    help="actually place REAL orders (also needs LIVE_RUNNER_CONFIRM=I_UNDERSTAND)")
    ap.add_argument("--min-ev", type=float, default=0.5, dest="min_ev")
    ap.add_argument("--signals", default=SIGNALS)
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--refresh", action=argparse.BooleanOptionalAction, default=True,
                    help="re-run the signal finder before trading (--no-refresh to skip)")
    ap.add_argument("--max-order-usd", type=float, default=5.0, dest="max_order_usd")
    ap.add_argument("--max-position-usd", type=float, default=20.0, dest="max_position_usd")
    ap.add_argument("--daily-loss-usd", type=float, default=20.0, dest="daily_loss_usd")
    args = ap.parse_args()

    load_env_file()
    creds = load_credentials()
    if creds is None:
        print("No credentials. Set POLY_PRIVATE_KEY (and POLY_FUNDER) in env or a "
              "local .env file. See live_runner.py docstring.")
        return

    if args.connectivity and not args.arm:
        connectivity_check(creds)
        return

    if not args.arm:
        print("Refusing to run. Use --connectivity for the read-only check, or --arm "
              "to place REAL orders.")
        return

    if os.environ.get("LIVE_RUNNER_CONFIRM") != "I_UNDERSTAND":
        print("--arm requires the env var LIVE_RUNNER_CONFIRM=I_UNDERSTAND to place "
              "real orders. Refusing.")
        return

    run_live(args, creds)


if __name__ == "__main__":
    main()

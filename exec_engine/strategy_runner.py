"""Phase 2 strategy runner — broker-agnostic orchestrator.

Drives validated signals (from signals.json) through the execution engine, one
5-minute window at a time. Per signal, per window:

  WAITING ──(elapsed >= t1*60)──▶ place resting BUY @ z (auto-sell @ T attached)
                                       │
                    ┌──────────────────┼───────────────────┐
              (unfilled by t2)                       (fills by t2)
                    ▼                                       ▼
        cancel BUY -> NOFILL                       HOLDING (exit rests to round end)
                                                            │
                                          ┌─────────────────┴───────────────┐
                                    (SELL fills)                    (unsold at resolution)
                                          ▼                                  ▼
                                  realize @ T                  SETTLE -> 1.0 (won) / 0.0 (lost)

`elapsed` is seconds into the window (now - window_start); t1/t2 are the signal's
buy-window in MINUTES, so t1*60 / t2*60 convert them to seconds.

Broker-agnostic on purpose: PaperBroker now (forward-test), LiveBroker later (the
only change is the broker + gating the auto-sell on the CONFIRMED user-WS status).
This module never touches the network or money — fills come from whatever the
broker simulates/reports.
"""

from .model import OrderStatus

WINDOW = 300.0
TICK = 0.01
EPS = 1e-9


def to_tick(p):
    """Round a price to the 0.01 tick grid a real limit order must sit on."""
    return round(round(p / TICK) * TICK, 2)


class Leg:
    """One signal instance within one window."""
    __slots__ = ("sig", "token", "ws", "state", "entry")

    def __init__(self, signal, token_id, window_start):
        self.sig = signal
        self.token = token_id
        self.ws = window_start
        self.state = "WAITING"   # WAITING PLACED HOLDING NOFILL MISSED SETTLED
        self.entry = None        # the entry Order once placed


class StrategyRunner:
    def __init__(self, manager, broker, signals, min_ev, queue_fn=None, log=None):
        self.mgr = manager
        self.broker = broker
        self.min_ev = min_ev
        # only trade signals whose predicted EV clears the floor (the user's choice)
        self.signals = [s for s in signals if s.get("ev", 0.0) > min_ev]
        self.queue_fn = queue_fn or (lambda token, price, side: 0.0)
        self.log = log or (lambda m: print(m, flush=True))
        self.windows = {}        # window_start -> list[Leg]

    def active_tokens(self):
        return {leg.token for legs in self.windows.values() for leg in legs}

    def start_window(self, window_start, market):
        legs = []
        for s in self.signals:
            token = market.get("token_up") if s["side"] == "up" else market.get("token_down")
            if token:
                legs.append(Leg(s, token, window_start))
        self.windows[window_start] = legs
        self.log(f"[window {window_start}] armed {len(legs)} signal leg(s) (ev > {self.min_ev:+.2f})")
        return legs

    def on_tick(self, now):
        for ws, legs in self.windows.items():
            elapsed = now - ws
            for leg in legs:
                self._advance(leg, elapsed)

    # --- state machine -------------------------------------------------------
    def _advance(self, leg, elapsed):
        s = leg.sig
        if leg.state == "WAITING":
            if elapsed > s["t2"] * 60:
                leg.state = "MISSED"            # joined after the buy window — skip
            elif elapsed >= s["t1"] * 60:
                self._place(leg)
        elif leg.state == "PLACED":
            entry = leg.entry
            if entry is None or entry.status == OrderStatus.REJECTED:
                leg.state = "NOFILL"
                return
            if elapsed > s["t2"] * 60:
                # buy window closed: cancel whatever is still unfilled
                if not entry.is_terminal:
                    self.mgr.cancel(entry.intent.client_id)
                leg.state = "HOLDING" if entry.filled_size > EPS else "NOFILL"
            elif entry.status == OrderStatus.FILLED:
                leg.state = "HOLDING"           # fully filled early; exit already resting

    def _place(self, leg):
        s = leg.sig
        z, T = to_tick(s["entry"]), to_tick(s["sell"])
        qa = self.queue_fn(leg.token, z, "BUY")
        eqa = self.queue_fn(leg.token, T, "SELL")
        order = self.mgr.place_entry(leg.token, price=z, size=s["shares"], exit_price=T,
                                     window_start=leg.ws, queue_ahead=qa, exit_queue_ahead=eqa)
        leg.entry = order
        leg.state = "PLACED"
        self.log(f"  PLACE {s['side']:>4} {s['shares']:g}@{z:.2f} -> sell {T:.2f}  "
                 f"(ev{s['ev']:+.2f}, q{qa:.0f}) {order.status.value}")

    # --- settlement ----------------------------------------------------------
    def settle_window(self, window_start, outcome):
        """Resolve every placed leg of a closed window; return ledger rows and
        prune the legs' orders from the broker (keeps on_trade fast over a long run)."""
        legs = self.windows.pop(window_start, [])
        rows = []
        for leg in legs:
            row = self._settle_leg(leg, outcome)
            if row:
                rows.append(row)
            if leg.entry is not None:               # prune entry + its exits
                ids = {leg.entry.intent.client_id}
                ids |= {o.intent.client_id for o in self.broker.orders.values()
                        if o.intent.parent_id == leg.entry.intent.client_id}
                for cid in ids:
                    self.broker.orders.pop(cid, None)
        return rows

    def _settle_leg(self, leg, outcome):
        s = leg.sig
        if leg.entry is None:                       # MISSED / never placed — no record
            return None
        won = (outcome == "Up") if s["side"] == "up" else (outcome == "Down")
        settle_px = 1.0 if won else 0.0
        z, T = to_tick(s["entry"]), to_tick(s["sell"])
        bought = leg.entry.filled_size
        sold = sum(o.filled_size for o in self.broker.orders.values()
                   if o.intent.parent_id == leg.entry.intent.client_id)
        remainder = max(0.0, bought - sold)
        pnl = sold * T + remainder * settle_px - bought * z
        buy_filled = bought > EPS
        sell_filled = buy_filled and remainder <= EPS
        leg.state = "SETTLED"
        if buy_filled:
            self.log(f"  SETTLE {s['side']:>4} {z:.2f}: bought {bought:g}, sold {sold:g}@{T:.2f}, "
                     f"settle {remainder:g}@{settle_px:.0f} ({'WON' if won else 'LOST'}) "
                     f"pnl {pnl:+.3f}")
        return {
            "window_start": leg.ws, "side": s["side"], "entry_z": f"{z:.2f}",
            "buy_filled": int(buy_filled), "fill_px": (f"{z:.2f}" if buy_filled else ""),
            "sell_T": f"{T:.2f}", "sell_filled": int(sell_filled),
            "exit_or_settle_px": (f"{T:.2f}" if sell_filled else
                                  (f"{settle_px:.2f}" if buy_filled else "")),
            "realized_pnl": round(pnl, 4), "ev_predicted": round(s["ev"], 4),
            "won": int(won), "shares": s["shares"],
        }

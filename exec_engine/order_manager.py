"""Order manager — the lifecycle brain.

Places entry limit BUYs, and when one fills (fully or partially) automatically
places a matching limit SELL to exit at the target price. Broker-agnostic: works
with PaperBroker now and LiveBroker later. Handles partial fills by hedging each
fill increment.
"""

from .model import Side, OrderIntent, Order


class OrderManager:
    def __init__(self, broker, config, logger=None):
        self.broker = broker
        self.config = config
        self.log = logger or (lambda msg: print(f"[OM] {msg}", flush=True))
        self.exit_plans: dict[str, dict] = {}   # entry client_id -> plan
        self.hedged: dict[str, float] = {}       # entry client_id -> qty exited
        broker.on_fill = self._on_fill
        broker.on_status = self._on_status

    # --- public API ----------------------------------------------------------
    def place_entry(self, token_id, price, size, exit_price,
                    window_start=None, queue_ahead=0.0, exit_queue_ahead=0.0,
                    tif="GTC") -> Order:
        """Place a resting limit BUY with an attached auto-sell at exit_price."""
        intent = OrderIntent(side=Side.BUY, token_id=token_id, price=price,
                             size=size, tif=tif, tag="entry", window_start=window_start)
        self.exit_plans[intent.client_id] = {
            "exit_price": exit_price,
            "token_id": token_id,
            "window_start": window_start,
            "exit_queue_ahead": exit_queue_ahead,
        }
        order = self.broker.place(intent, queue_ahead=queue_ahead)
        self.log(f"ENTRY {order.status.value} {size}@{price} -> exit {exit_price} "
                 f"({order.note})".rstrip())
        return order

    def place_limit(self, side, token_id, price, size, tag="", queue_ahead=0.0,
                    tif="GTC") -> Order:
        """Place a standalone limit order (no auto-exit)."""
        intent = OrderIntent(side=side, token_id=token_id, price=price, size=size,
                             tif=tif, tag=tag)
        return self.broker.place(intent, queue_ahead=queue_ahead)

    def cancel(self, client_id) -> bool:
        ok = self.broker.cancel(client_id)
        self.log(f"CANCEL {client_id} -> {'ok' if ok else 'noop'}")
        return ok

    def cancel_all_entries(self):
        for o in self.broker.open_orders():
            if o.intent.tag == "entry":
                self.cancel(o.intent.client_id)

    # --- callbacks -----------------------------------------------------------
    def _on_status(self, order: Order):
        pass  # hook for logging/metrics

    def _on_fill(self, order: Order, fill_qty: float, fill_price: float):
        self.log(f"FILL {order.intent.side.value} {fill_qty}@{fill_price} "
                 f"[{order.intent.tag}] status={order.status.value}")
        if order.intent.tag != "entry":
            return
        plan = self.exit_plans.get(order.intent.client_id)
        if not plan:
            return
        # hedge the newly-filled (un-exited) quantity with a SELL at the target
        already = self.hedged.get(order.intent.client_id, 0.0)
        unhedged = order.filled_size - already
        if unhedged <= 1e-9:
            return
        self.hedged[order.intent.client_id] = order.filled_size
        exit_intent = OrderIntent(
            side=Side.SELL, token_id=plan["token_id"], price=plan["exit_price"],
            size=unhedged, tag="exit", window_start=plan["window_start"],
            parent_id=order.intent.client_id)
        exit_order = self.broker.place(exit_intent,
                                       queue_ahead=plan.get("exit_queue_ahead", 0.0))
        self.log(f"AUTO-SELL {unhedged}@{plan['exit_price']} "
                 f"-> {exit_order.status.value} ({exit_order.note})".rstrip())

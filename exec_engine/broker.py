"""Brokers: the thing that actually places/cancels orders.

Broker      - abstract interface
PaperBroker - simulates resting-limit-order fills against the real trade stream
              using the conservative RiskAverse queue model (you fill only after
              cumulative trade volume clears the size that was ahead of you).
              This is also the fill engine the backtester will reuse.
LiveBroker  - real Polymarket CLOB orders. STUB until the execution research lands;
              refuses to operate unless SafetyConfig(live=True) + credentials.

The fill callback signature is: on_fill(order, fill_qty, fill_price).
"""

from abc import ABC, abstractmethod

from .model import Side, OrderStatus, OrderIntent, Order


class Broker(ABC):
    def __init__(self, config):
        self.config = config
        self.orders: dict[str, Order] = {}
        self.on_fill = None      # callback(order, fill_qty, fill_price)
        self.on_status = None    # callback(order)

    @abstractmethod
    def place(self, intent: OrderIntent, **kw) -> Order: ...

    @abstractmethod
    def cancel(self, client_id: str) -> bool: ...

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if not o.is_terminal]

    def _emit_status(self, order: Order):
        order.touch()
        if self.on_status:
            self.on_status(order)

    def _emit_fill(self, order: Order, qty: float, price: float):
        if self.on_fill:
            self.on_fill(order, qty, price)


class PaperBroker(Broker):
    """Simulated broker. Feed it the live trade prints via on_trade(); it fills
    resting orders with the RiskAverse queue model and tracks cash/position/PnL."""

    def __init__(self, config):
        super().__init__(config)
        self.cash = 0.0                       # signed cash flow (negative = spent)
        self.position: dict[str, float] = {}  # token_id -> shares
        self.cost: dict[str, float] = {}      # token_id -> total cost basis
        self.realized_pnl = 0.0

    # --- order entry ---------------------------------------------------------
    def place(self, intent: OrderIntent, queue_ahead: float = 0.0) -> Order:
        ok, reason = self.config.validate(intent)
        order = Order(intent=intent)
        if not ok:
            order.status = OrderStatus.REJECTED
            order.note = reason
            self.orders[intent.client_id] = order
            self._emit_status(order)
            return order
        if len(self.open_orders()) >= self.config.max_open_orders:
            order.status = OrderStatus.REJECTED
            order.note = "max_open_orders"
            self.orders[intent.client_id] = order
            self._emit_status(order)
            return order
        order.status = OrderStatus.OPEN
        order.broker_order_id = f"paper-{intent.client_id}"
        order.queue_remaining = max(0.0, queue_ahead)
        self.orders[intent.client_id] = order
        self._emit_status(order)
        return order

    def cancel(self, client_id: str) -> bool:
        order = self.orders.get(client_id)
        if order is None or order.is_terminal:
            return False
        order.status = OrderStatus.CANCELED
        self._emit_status(order)
        return True

    # --- market data drives fills -------------------------------------------
    def on_trade(self, token_id: str, price: float, size: float, taker_side: str, ts=None):
        """Apply one trade print to all resting orders on this token.

        A resting BUY @p is eligible to be consumed/filled by taker SELL volume
        at price <= p; a resting SELL @p by taker BUY volume at price >= p.
        Volume first clears queue_remaining (orders ahead of us), then fills us.
        """
        eps = self.config.tick / 2.0
        for order in list(self.orders.values()):
            if order.is_terminal or order.intent.token_id != token_id:
                continue
            p = order.intent.price
            if order.intent.side == Side.BUY:
                eligible = (taker_side == Side.SELL.value) and (price <= p + eps)
            else:
                eligible = (taker_side == Side.BUY.value) and (price >= p - eps)
            if not eligible:
                continue
            vol = float(size)
            # 1) clear the queue ahead of us
            consumed = min(vol, order.queue_remaining)
            order.queue_remaining -= consumed
            vol -= consumed
            # 2) fill us with whatever volume remains
            if vol > 0 and order.queue_remaining <= 1e-9:
                fill = min(vol, order.remaining)
                if fill > 0:
                    self._apply_fill(order, fill, p)

    def _apply_fill(self, order: Order, qty: float, price: float):
        order.filled_size += qty
        order.avg_price = order.intent.price   # passive fill at our limit price
        order.status = (OrderStatus.FILLED if order.remaining <= 1e-9
                        else OrderStatus.PARTIALLY_FILLED)
        tok = order.intent.token_id
        if order.intent.side == Side.BUY:
            self.cash -= qty * price
            self.position[tok] = self.position.get(tok, 0.0) + qty
            self.cost[tok] = self.cost.get(tok, 0.0) + qty * price
        else:  # SELL
            pos = self.position.get(tok, 0.0)
            avg_cost = (self.cost.get(tok, 0.0) / pos) if pos > 1e-9 else price
            self.realized_pnl += qty * (price - avg_cost)
            self.cash += qty * price
            self.position[tok] = pos - qty
            self.cost[tok] = self.cost.get(tok, 0.0) - qty * avg_cost
        order.touch()
        self._emit_fill(order, qty, price)

    def summary(self) -> dict:
        return {
            "cash": round(self.cash, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "position": {k: round(v, 4) for k, v in self.position.items() if abs(v) > 1e-9},
            "open_orders": len(self.open_orders()),
        }


class LiveBroker(Broker):
    """Real Polymarket CLOB broker. Intentionally a STUB until the execution
    research lands. It will NOT operate unless config.live is True and
    credentials are supplied, and even then the concrete order calls are filled
    in only after the API recipe is verified (see EXECUTION.md / task #3)."""

    def __init__(self, config, credentials=None):
        super().__init__(config)
        if not config.live:
            raise RuntimeError(
                "LiveBroker requires SafetyConfig(live=True). Refusing to run in a "
                "config that isn't explicitly live. Use PaperBroker for simulation.")
        if not credentials:
            raise RuntimeError("LiveBroker requires credentials (private key + API creds).")
        self.credentials = credentials
        # py-clob-client is imported lazily so the package works without it.
        self._client = None

    def _ensure_client(self):
        raise NotImplementedError(
            "LiveBroker is not wired yet — pending verified Polymarket execution "
            "recipe (research task w4edctlys). See EXECUTION.md.")

    def place(self, intent: OrderIntent, **kw) -> Order:
        self._ensure_client()

    def cancel(self, client_id: str) -> bool:
        self._ensure_client()

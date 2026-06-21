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
    """Real Polymarket CLOB broker, wired per the verified execution recipe
    (see EXECUTION.md). Places GTC resting limits / FOK marketable orders and
    cancels them via py-clob-client.

    SAFETY: refuses to operate unless SafetyConfig(live=True) AND credentials are
    supplied. Supports all three Polymarket wallet types via signature_type:
      0 = EOA (self-custody; funder = the signer's own address)
      1 = POLY_PROXY (Polymarket email/Google login; funder = proxy/deposit address)
      2 = POLY_GNOSIS_SAFE (browser-wallet proxy; funder = proxy address)
    For 1/2 the signer key is the Magic/owner key (exported from Polymarket) and the
    funder is the PROXY address that holds the USDC. UNTESTED without real keys:
    paper-trade first, ensure USDC+CTF allowances are set, and watch the first live
    fills by hand. Fill detection / auto-sell is driven by user_stream on CONFIRMED.

    credentials = {
        "private_key": "0x...",        # the L1 signer key (EOA or exported proxy key)
        "funder": "0x...",             # EOA addr (type 0) or proxy/deposit addr (1/2)
        "signature_type": 0,            # 0 EOA | 1 POLY_PROXY | 2 POLY_GNOSIS_SAFE
        "host": "https://clob.polymarket.com",   # optional
        "api_creds": {...},             # optional; derived if omitted
        "neg_risk": False,              # set True only for neg-risk markets
    }
    """

    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137

    def __init__(self, config, credentials=None):
        super().__init__(config)
        if not config.live:
            raise RuntimeError(
                "LiveBroker requires SafetyConfig(live=True). Use PaperBroker for simulation.")
        if not credentials or not credentials.get("private_key"):
            raise RuntimeError("LiveBroker requires credentials with a 'private_key'.")
        sigtype = credentials.get("signature_type", 0)
        if sigtype not in (0, 1, 2):
            raise RuntimeError(
                f"signature_type={sigtype} invalid. Use 0 (EOA / self-custody), "
                f"1 (POLY_PROXY = Polymarket email/Google login), or 2 "
                f"(POLY_GNOSIS_SAFE = browser-wallet proxy). For 1 and 2 the "
                f"'funder' must be your Polymarket proxy/deposit address (where the "
                f"USDC sits), NOT the signer's address.")
        self.signature_type = sigtype
        self.credentials = credentials
        self.neg_risk = bool(credentials.get("neg_risk", False))
        self._client = None
        self._order_ids: dict[str, str] = {}   # client_id -> broker order id
        print("[LiveBroker] LIVE mode armed. Real orders will be placed. "
              "Ensure USDC+CTF allowances are set and start tiny.", flush=True)

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from py_clob_client.client import ClobClient
        except ImportError as e:
            raise RuntimeError("pip install py-clob-client (see requirements-exec.txt)") from e
        c = self.credentials
        client = ClobClient(c.get("host", self.HOST), key=c["private_key"],
                            chain_id=self.CHAIN_ID, signature_type=self.signature_type,
                            funder=c.get("funder"))
        creds = c.get("api_creds") or client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        self._client = client
        return client

    def _round_tick(self, price: float) -> float:
        return round(round(price / self.config.tick) * self.config.tick, 4)

    def place(self, intent: OrderIntent, **kw) -> Order:
        ok, reason = self.config.validate(intent)
        order = Order(intent=intent)
        if not ok:
            order.status = OrderStatus.REJECTED
            order.note = reason
            self.orders[intent.client_id] = order
            return order
        client = self._ensure_client()
        from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
        from py_clob_client.order_builder.constants import BUY, SELL
        args = OrderArgs(token_id=intent.token_id, price=self._round_tick(intent.price),
                         size=intent.size, side=(BUY if intent.side == Side.BUY else SELL))
        otype = {"GTC": OrderType.GTC, "FOK": OrderType.FOK,
                 "FAK": OrderType.FAK, "GTD": OrderType.GTD}.get(intent.tif, OrderType.GTC)
        options = PartialCreateOrderOptions(neg_risk=self.neg_risk)
        signed = client.create_order(args, options)
        resp = client.post_order(signed, otype)
        oid = (resp or {}).get("orderID") or (resp or {}).get("orderId")
        if not oid or (resp or {}).get("success") is False:
            order.status = OrderStatus.REJECTED
            order.note = str(resp)
        else:
            order.status = OrderStatus.OPEN
            order.broker_order_id = oid
            self._order_ids[intent.client_id] = oid
        self.orders[intent.client_id] = order
        self._emit_status(order)
        return order

    def cancel(self, client_id: str) -> bool:
        oid = self._order_ids.get(client_id)
        if not oid:
            return False
        client = self._ensure_client()
        resp = client.cancel(oid) or {}
        ok = oid in (resp.get("canceled") or [])
        order = self.orders.get(client_id)
        if ok and order and not order.is_terminal:
            order.status = OrderStatus.CANCELED
            self._emit_status(order)
        return ok

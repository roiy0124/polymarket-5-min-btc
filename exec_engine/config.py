"""Safety configuration and order validation.

These limits are the guardrails that keep an automated bot from doing something
catastrophic. Defaults are deliberately conservative and PAPER-only.
"""

from dataclasses import dataclass


@dataclass
class SafetyConfig:
    # --- the master switch ---------------------------------------------------
    live: bool = False               # MUST be explicitly True for real orders
    kill_switch: bool = False        # if True, reject every new order

    # --- per-order limits ----------------------------------------------------
    min_price: float = 0.01
    max_price: float = 0.99
    tick: float = 0.01
    min_order_usd: float = 5.0       # Polymarket minimum order size
    max_order_usd: float = 50.0      # cap notional per order

    # --- account-level limits ------------------------------------------------
    max_open_orders: int = 20
    max_position_usd: float = 200.0  # cap absolute position per token
    daily_loss_limit_usd: float = 50.0

    def on_tick(self, price: float) -> bool:
        return abs(price / self.tick - round(price / self.tick)) < 1e-6

    def validate(self, intent) -> tuple[bool, str]:
        """Return (ok, reason). Reason is '' when ok."""
        if self.kill_switch:
            return False, "kill_switch active"
        p, sz = intent.price, intent.size
        if not (self.min_price <= p <= self.max_price):
            return False, f"price {p} outside [{self.min_price},{self.max_price}]"
        if not self.on_tick(p):
            return False, f"price {p} not on {self.tick} tick grid"
        if sz <= 0:
            return False, f"size {sz} must be positive"
        notional = sz * p
        if notional < self.min_order_usd - 1e-9:
            return False, f"notional ${notional:.2f} < min ${self.min_order_usd}"
        if notional > self.max_order_usd + 1e-9:
            return False, f"notional ${notional:.2f} > max ${self.max_order_usd}"
        return True, ""

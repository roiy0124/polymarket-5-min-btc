"""Execution engine for the BTC up/down strategy.

SAFETY MODEL: everything defaults to PAPER (simulated) trading. Real orders are
only ever sent by LiveBroker, which requires explicit credentials AND
SafetyConfig(live=True). Nothing here places a real order on its own.

Components:
  model.py         - Side/OrderStatus enums, OrderIntent, Order dataclasses
  config.py        - SafetyConfig: limits, tick/min-size rules, kill switch
  broker.py        - Broker ABC; PaperBroker (RiskAverse queue fills); LiveBroker stub
  order_manager.py - order lifecycle + auto-place-sell-on-fill
  user_stream.py   - (added next) Polymarket user-channel fill/order listener
"""

__all__ = ["model", "config", "broker", "order_manager"]

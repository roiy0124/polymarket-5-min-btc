"""Scripted self-test of the paper execution engine — no creds, no network, no DB.

Verifies: entry limit BUY rests behind a queue, fills only after the queue clears,
auto-places a SELL on each fill increment (partial-fill aware), the SELL fills,
and the realized PnL matches the round-trip. Run:  python -m exec_engine.selftest
"""

from .config import SafetyConfig
from .broker import PaperBroker
from .order_manager import OrderManager
from .model import OrderStatus, Side

TOKEN = "TKN"


def run():
    cfg = SafetyConfig()           # paper, $5 min / $50 max notional
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg)

    # rest a BUY 100 @0.22 with 50 shares ahead in the queue; exit target 0.33
    entry = mgr.place_entry(TOKEN, price=0.22, size=100, exit_price=0.33,
                            queue_ahead=50, exit_queue_ahead=0)
    assert entry.status == OrderStatus.OPEN, entry.note

    # taker SELL 30 @0.22 -> only clears part of the 50-share queue, no fill yet
    broker.on_trade(TOKEN, 0.22, 30, Side.SELL.value)
    assert entry.filled_size == 0, entry.filled_size

    # taker SELL 40 @0.22 -> clears remaining 20 of queue, fills 20 -> partial
    broker.on_trade(TOKEN, 0.22, 40, Side.SELL.value)
    assert abs(entry.filled_size - 20) < 1e-9, entry.filled_size
    assert entry.status == OrderStatus.PARTIALLY_FILLED

    # taker SELL 200 @0.22 -> fills remaining 80 -> entry FILLED
    broker.on_trade(TOKEN, 0.22, 200, Side.SELL.value)
    assert abs(entry.filled_size - 100) < 1e-9, entry.filled_size
    assert entry.status == OrderStatus.FILLED

    # the auto-sell should now rest for the full 100 @0.33
    exits = [o for o in broker.orders.values() if o.intent.tag == "exit"]
    total_exit = sum(o.intent.size for o in exits)
    assert abs(total_exit - 100) < 1e-9, total_exit

    # taker BUY 60 @0.33 then 100 @0.34 -> fills the exit completely
    broker.on_trade(TOKEN, 0.33, 60, Side.BUY.value)
    broker.on_trade(TOKEN, 0.34, 100, Side.BUY.value)
    exit_filled = sum(o.filled_size for o in exits)
    assert abs(exit_filled - 100) < 1e-9, exit_filled

    # round-trip PnL: bought 100 @0.22, sold 100 @0.33 => +11.00 (paper, no fees)
    s = broker.summary()
    assert abs(s["realized_pnl"] - 11.0) < 1e-6, s
    assert not s["position"], s  # flat

    print("paper execution engine self-test: PASS")
    print("  summary:", s)

    # validation guardrails
    bad = mgr.place_limit(Side.BUY, TOKEN, price=0.22, size=1, tag="t")  # $0.22 < $5 min
    assert bad.status == OrderStatus.REJECTED and "min" in bad.note, bad.note
    off = mgr.place_limit(Side.BUY, TOKEN, price=0.225, size=100, tag="t")  # off-tick
    assert off.status == OrderStatus.REJECTED and "tick" in off.note, off.note
    print("  guardrails (min-size, tick): PASS")


if __name__ == "__main__":
    run()

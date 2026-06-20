"""Scripted self-test of the Phase-2 strategy runner — no creds/network/DB.

Verifies the per-signal state machine and settlement accounting end-to-end:
  A) a signal whose BUY fills then SELL fills  -> realized at the target
  B) a signal whose BUY fills but never sells  -> settles to 1.0 (won) / 0.0 (lost)
  C) a signal whose BUY never fills by t2       -> cancelled, no position

Run:  python -m exec_engine.phase2_selftest
"""

from .config import SafetyConfig
from .broker import PaperBroker
from .order_manager import OrderManager
from .strategy_runner import StrategyRunner
from .model import Side

MARKET = {"token_up": "UP", "token_down": "DN", "slug": "test"}


def _sig(side, entry, sell, t1, t2, shares, ev):
    return {"side": side, "entry": entry, "sell": sell, "t1": t1, "t2": t2,
            "shares": shares, "ev": ev}


def run():
    cfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg, logger=lambda m: None)

    # A: down @0.25 sell 0.50, buy-window 0..1min, 8 shares
    # B: up   @0.40 sell 0.90, buy-window 0..1min, 5 shares (sell won't fill -> settles)
    # C: down @0.10 sell 0.50, buy-window 0..0.5min, 10 shares (never fills -> cancel)
    sigs = [_sig("down", 0.25, 0.50, 0.0, 1.0, 8, 1.0),
            _sig("up", 0.40, 0.90, 0.0, 1.0, 5, 1.0),
            _sig("down", 0.10, 0.50, 0.0, 0.5, 10, 1.0)]
    runner = StrategyRunner(mgr, broker, sigs, min_ev=0.5, log=lambda m: None)
    ws = 0
    runner.start_window(ws, MARKET)
    assert len(runner.windows[ws]) == 3

    # t=0s: all three place their resting BUYs (t1=0 for all)
    runner.on_tick(0)
    assert all(leg.state == "PLACED" for leg in runner.windows[ws]), \
        [leg.state for leg in runner.windows[ws]]

    # Fill A's and B's BUYs via taker SELL volume at their prices (no queue ahead).
    broker.on_trade("DN", 0.25, 100, Side.SELL.value)   # fills A (down @0.25)
    broker.on_trade("UP", 0.40, 100, Side.SELL.value)   # fills B (up   @0.40)
    # C (down @0.10) gets no trades at its price -> stays unfilled.

    # Let A's SELL fill via taker BUY volume at 0.50; B's SELL never fills.
    broker.on_trade("DN", 0.50, 100, Side.BUY.value)    # fills A's auto-sell @0.50

    # t=40s (0.67min): past C's t2 (0.5min) but within A/B (1min).
    runner.on_tick(40)
    legs = {(l.sig["side"], l.sig["entry"]): l for l in runner.windows[ws]}
    assert legs[("down", 0.10)].state == "NOFILL", legs[("down", 0.10)].state

    # t=70s (1.17min): past A/B t2 -> they become HOLDING (filled).
    runner.on_tick(70)
    assert legs[("down", 0.25)].state == "HOLDING"
    assert legs[("up", 0.40)].state == "HOLDING"

    # Settle the window: official outcome Down (so 'down' legs win, 'up' legs lose).
    rows = runner.settle_window(ws, "Down")
    by = {(r["side"], r["entry_z"]): r for r in rows}

    # A: bought 8@0.25, sold 8@0.50 -> pnl = 8*0.50 - 8*0.25 = +2.00
    a = by[("down", "0.25")]
    assert a["buy_filled"] == 1 and a["sell_filled"] == 1, a
    assert abs(a["realized_pnl"] - 2.0) < 1e-6, a

    # B: bought 5@0.40, never sold, outcome Down -> 'up' lost -> settles @0.0
    #    pnl = 0 (settle) - 5*0.40 = -2.00
    b = by[("up", "0.40")]
    assert b["buy_filled"] == 1 and b["sell_filled"] == 0, b
    assert b["won"] == 0 and abs(b["realized_pnl"] + 2.0) < 1e-6, b

    # C: never filled -> recorded as a no-fill, zero pnl
    c = by[("down", "0.10")]
    assert c["buy_filled"] == 0 and abs(c["realized_pnl"]) < 1e-9, c

    # broker orders for the window were pruned on settle
    assert not broker.orders, broker.orders

    print("phase-2 strategy-runner self-test: PASS")
    print(f"  A (filled+sold) pnl={a['realized_pnl']:+.2f}  "
          f"B (held->settled-loss) pnl={b['realized_pnl']:+.2f}  "
          f"C (no-fill) pnl={c['realized_pnl']:+.2f}")


if __name__ == "__main__":
    run()

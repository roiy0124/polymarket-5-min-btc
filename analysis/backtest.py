"""Backtest harness — replay the mean-reversion rule over all collected windows.

Reuses the SAME RiskAverse fill engine as live paper trading (exec_engine), so the
backtest and the bot agree on how fills happen. For each settled window and each
outcome side, it:
  1. finds the first dip to <= entry with time_left >= min_left,
  2. rests a paper limit BUY there (queue-ahead from the real book at that instant),
  3. replays the window's real trade prints through the broker,
  4. auto-sells at the target; any position left at the close settles at the
     official outcome (1 if that side won, else 0).
Aggregates fill rate, exit rate, win rate, and total/avg PnL.

    python -m analysis.backtest [--entry 0.22 --exit 0.33 --min-left 240 --notional 10]

This is the seed of the A/B harness: a fair-value strategy plugs into the same
loop later. HONEST-USE CAVEATS (DATA-ANALYSIS-TOOLKIT.md + STRATEGY-MEAN-REVERSION):
results on a few hours of data are NOT significant; the RiskAverse sim is optimistic
on adverse selection; count every parameter combo you try (multiple testing).
"""

import json
import argparse

from . import panel
from .flow import flow_imbalance
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from exec_engine.model import Side


def queue_ahead(conn, token, price, before_ts, tick=0.01):
    row = conn.execute(
        "SELECT payload FROM book_events WHERE asset_id=? AND event_type='book' "
        "AND recv_ts<=? ORDER BY id DESC LIMIT 1", (token, before_ts)).fetchone()
    if not row:
        return 0.0
    try:
        book = json.loads(row[0])
    except (ValueError, TypeError):
        return 0.0
    total = 0.0
    for lvl in book.get("bids", []):
        try:
            if abs(float(lvl["price"]) - price) < tick / 2:
                total += float(lvl["size"])
        except (KeyError, ValueError, TypeError):
            pass
    return total


def run_side(conn, ws, side, token, outcome, entry, exit_p, min_left, notional, cfg,
             max_toxicity=None, lookback=60.0):
    col = "up_mid" if side == "up" else "down_mid"
    snaps = conn.execute(
        f"SELECT ts, time_left, {col} FROM snapshots WHERE window_start=? AND {col} "
        f"IS NOT NULL ORDER BY ts", (ws,)).fetchall()
    entry_ts = None
    for ts, tl, mid in snaps:
        if mid <= entry and tl >= min_left:
            entry_ts = ts
            break
    if entry_ts is None:
        return None   # no opportunity this window/side

    # toxic-flow filter: skip dips driven by one-sided (likely informed) flow
    if max_toxicity is not None:
        imb, vol = flow_imbalance(conn, token, entry_ts - lookback, entry_ts)
        if imb is None or abs(imb) >= max_toxicity:
            return None   # no/too-toxic flow -> don't provide liquidity here

    size = round(notional / entry, 2)
    broker = PaperBroker(cfg)
    mgr = OrderManager(broker, cfg, logger=lambda m: None)
    qa = queue_ahead(conn, token, entry, entry_ts)
    order = mgr.place_entry(token, price=entry, size=size, exit_price=exit_p,
                            window_start=ws, queue_ahead=qa)
    if order.status.value == "REJECTED":
        return None

    for price, sz, tside in conn.execute(
            "SELECT price, size, side FROM trades WHERE asset_id=? AND recv_ts>=? "
            "ORDER BY recv_ts", (token, entry_ts)):
        if price is None or sz is None:
            continue
        broker.on_trade(token, float(price), float(sz), tside)

    # settle any unsold position at the official outcome
    won = (side == "up" and outcome == "Up") or (side == "down" and outcome == "Down")
    payout = 1.0 if won else 0.0
    pos = broker.position.get(token, 0.0)
    cost_leftover = broker.cost.get(token, 0.0)
    settle_pnl = pos * payout - cost_leftover
    pnl = broker.realized_pnl + settle_pnl

    return {
        "filled": order.filled_size > 1e-9,
        "fill_frac": order.filled_size / size if size else 0.0,
        "exited": pos <= 1e-9 and order.filled_size > 1e-9,
        "pnl": pnl,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=float, default=0.22)
    ap.add_argument("--exit", type=float, default=0.33, dest="exit_p")
    ap.add_argument("--min-left", type=float, default=240.0, dest="min_left")
    ap.add_argument("--notional", type=float, default=10.0)
    ap.add_argument("--side", choices=["up", "down", "both"], default="both")
    ap.add_argument("--max-toxicity", type=float, default=None, dest="max_toxicity",
                    help="skip entries where |pre-entry flow imbalance| >= this (0..1)")
    ap.add_argument("--lookback", type=float, default=60.0)
    args = ap.parse_args()

    cfg = SafetyConfig(max_order_usd=max(50.0, args.notional + 1))
    conn = panel.connect()
    windows = conn.execute(
        "SELECT window_start, token_up, token_down, resolved_outcome FROM windows "
        "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start").fetchall()
    sides = ["up", "down"] if args.side == "both" else [args.side]

    opp = filled = exited = wins = 0
    total_pnl = 0.0
    pnls = []
    for ws, tok_up, tok_down, outcome in windows:
        for side in sides:
            token = tok_up if side == "up" else tok_down
            r = run_side(conn, ws, side, token, outcome, args.entry, args.exit_p,
                         args.min_left, args.notional, cfg,
                         max_toxicity=args.max_toxicity, lookback=args.lookback)
            if r is None:
                continue
            opp += 1
            if r["filled"]:
                filled += 1
            if r["exited"]:
                exited += 1
            if r["pnl"] > 0:
                wins += 1
            total_pnl += r["pnl"]
            pnls.append(r["pnl"])
    conn.close()

    print(f"Mean-reversion backtest  entry<= {args.entry}  exit {args.exit_p}  "
          f"min_left>= {args.min_left:.0f}s  notional ${args.notional:.0f}  side={args.side}")
    print(f"  settled windows: {len(windows)}   opportunities: {opp}")
    if opp == 0:
        print("  no opportunities yet — need more data or looser thresholds.")
        return
    avg = total_pnl / opp
    print(f"  filled: {filled} ({filled/opp:.0%})   fully-exited: {exited}   "
          f"profitable: {wins} ({wins/opp:.0%})")
    print(f"  total PnL: ${total_pnl:+.2f}   avg PnL/opportunity: ${avg:+.4f}")
    if pnls:
        pnls_sorted = sorted(pnls)
        worst = pnls_sorted[0]
        print(f"  worst single: ${worst:+.2f}   (negative skew -- see sizing in toolkit)")
    print("\n  CAVEATS: small-sample + RiskAverse fills optimistic on adverse selection;")
    print("  not significant until many windows + walk-forward + trial-count control.")


if __name__ == "__main__":
    main()

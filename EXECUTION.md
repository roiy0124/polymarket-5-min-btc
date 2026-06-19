# Execution Engine — Design & Safety

The `exec_engine` package + `paper_trade.py` implement limit-order execution for
the strategy: rest a limit BUY, cancel on demand, and auto-place a limit SELL when
it fills. **Everything defaults to PAPER (simulated).** Real orders require an
explicit opt-in described below — nothing here can spend money on its own.

## Safety model (read first)

1. **Paper by default.** `SafetyConfig.live` is `False`. `PaperBroker` simulates
   fills against the real trade stream and touches no money.
2. **Live is double-gated.** `LiveBroker` raises unless `SafetyConfig(live=True)`
   **and** credentials are supplied. The concrete order calls stay disabled until
   the verified Polymarket recipe is wired in (below).
3. **Per-order guardrails** (`SafetyConfig.validate`): price in [0.01, 0.99] and on
   the 0.01 tick grid; notional within `[min_order_usd=$5, max_order_usd=$50]`.
4. **Account guardrails**: `max_open_orders`, `max_position_usd`,
   `daily_loss_limit_usd`, and a `kill_switch` that rejects all new orders.
5. **Auto-sell is bounded** — it only ever hedges filled quantity, never more.

## Architecture

| Module | Role |
|--------|------|
| `exec_engine/model.py` | `Side`, `OrderStatus`, `OrderIntent`, `Order` |
| `exec_engine/config.py` | `SafetyConfig` — limits + `validate()` |
| `exec_engine/broker.py` | `Broker` ABC; `PaperBroker` (RiskAverse fills + PnL); `LiveBroker` (gated stub) |
| `exec_engine/order_manager.py` | lifecycle + **auto-place-sell-on-fill** (partial-aware) |
| `exec_engine/user_stream.py` | live user-channel WS listener (fills/orders), gated by creds |
| `exec_engine/selftest.py` | scripted end-to-end paper test (run it: `python -m exec_engine.selftest`) |
| `paper_trade.py` | live PAPER harness — drives the engine off the real trade stream |

## Fill model (paper) — and why it's conservative

`PaperBroker` uses the **RiskAverse queue model** (from the data-reliability
research): a resting BUY @p fills only **after cumulative taker-SELL volume at
price ≤ p clears the size that was ahead of it** in the queue (and symmetrically
for SELLs). Queue-ahead is taken from the live book depth at placement. This is
the *pessimistic* bound and is also the backtester's fill engine.

> **Adverse-selection caveat** (STRATEGY-MEAN-REVERSION.md): real resting fills
> cluster precisely when price moves against you, costing ≈ half a tick of hidden
> drift. The paper sim's fills are optimistic vs reality on that axis — do not
> treat paper PnL as a guarantee. The live `user_stream` reports *actual* fills.

## Paper trading (safe, runnable now)

```sh
# requires the collectors running (live book_events + trades in the DB)
python -m exec_engine.selftest                 # offline logic test (PASS)
python paper_trade.py --outcome down --price 0.22 --size 30 --exit 0.33
```
`paper_trade.py` discovers the current live 5-min window, rests a simulated BUY on
the chosen outcome with queue-ahead from the live book, auto-sells at the target,
and prints fills + PnL as real trades print through.

## Order lifecycle

`PENDING_NEW → OPEN → PARTIALLY_FILLED → FILLED` (or `CANCELED` / `REJECTED`).
On each fill increment of an `entry` order, `OrderManager` places a `SELL` for the
newly-filled quantity at the exit price (so partial fills are hedged immediately).

## Going live — checklist (DO NOT skip)

> Status: **LIVE PATH NOT YET WIRED.** Pending the verified execution recipe from
> the deep-research pass (task w4edctlys). The steps below are the known shape;
> exact functions/params land in the "Live API recipe" section once confirmed.

1. **Fund** a Polymarket account (USDC on Polygon).
2. **One-time allowances**: approve USDC + CTF (ERC-1155) to the Exchange /
   neg-risk contracts — orders silently fail without these.
3. **Credentials**: private key (L1) → derive L2 API creds (apiKey/secret/passphrase).
4. **Paper-trade the exact rule first** for long enough to trust it.
5. Start with `max_order_usd` at the $5 minimum and tiny size.
6. Enable `SafetyConfig(live=True)` + pass credentials to `LiveBroker`.
7. Run the `user_stream` listener for authoritative fill detection; reconcile
   intended vs actual every loop; keep the `kill_switch` reachable.
8. Watch the first live fills by hand before letting it run unattended.

## Live API recipe (to be completed from research)

*(This section will be filled with the exact `py-clob-client` calls — client
setup, `create_or_derive_api_creds`, `OrderArgs` / `create_order` / `post_order`
for GTC limit + marketable limit, `cancel*`, allowances, the real fee schedule,
and rate limits — once the execution research is verified. Until then `LiveBroker`
deliberately refuses to operate.)*

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

> Status: **LIVE PATH WIRED per the verified recipe (below), but UNTESTED without
> real keys.** `LiveBroker` places/cancels via py-clob-client; it stays disabled
> until you pass `SafetyConfig(live=True)` + EOA credentials. Do the allowance/fee
> verification first.

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

## Live API recipe (verified — 24/25 claims 3-vote confirmed)

> `LiveBroker` (exec_engine/broker.py) implements this. It still refuses to run
> unless `SafetyConfig(live=True)` + credentials, and enforces `signature_type=0`.
> **UNTESTED without real keys — paper-trade first.**

### ⚠️ The single biggest gotcha
**Website / email-funded accounts use a proxy wallet = `signature_type=3`
(POLY_1271).** The SDK binds the API key to your EOA, so POLY_1271 orders fail
**HTTP 400 "order signer address has to be the address of the API KEY"** (open
issues #70/#64/#71/#75/#77). **Only a plain EOA (`signature_type=0`, `funder`=that
EOA's address) is verified to work.** ⇒ Fund a dedicated EOA directly, don't trade
from the website proxy wallet via the SDK.

### Auth
```python
from py_clob_client.client import ClobClient
client = ClobClient("https://clob.polymarket.com", key=PRIVATE_KEY,
                    chain_id=137, signature_type=0, funder=EOA_ADDRESS)
client.set_api_creds(client.create_or_derive_api_creds())   # L2 apiKey/secret/passphrase
```
L1 = EIP-712 private-key (signs creds + orders); L2 = HMAC on api creds.
(The manual REST `/auth/api-key` + `POLY_NONCE` path was **refuted** — use
`create_or_derive_api_creds()`.)

### Place orders
```python
from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL
args = OrderArgs(token_id=TOKEN, price=0.22, size=45, side=BUY)
signed = client.create_order(args, PartialCreateOrderOptions(neg_risk=False))
resp = client.post_order(signed, OrderType.GTC)   # resp['orderID']
```
- **Resting limit BUY → `OrderType.GTC`**; **instant/marketable exit → `FOK`/`FAK`**
  (cross the spread). `GTD` = with expiration.
- Round price to the market tick (0.01 here). Min order **$5**.
- **Precision is side/tick-specific** — excess decimals are rejected (FOK stricter
  than GTC). Stick to the tick grid and integer-ish sizes.
- neg-risk markets need `PartialCreateOrderOptions(neg_risk=True)` (our BTC up/down
  markets are `negRisk=false`).

### Cancel + reconcile
```python
client.cancel(order_id)            # -> {"canceled":[...], "not_canceled":{...}}
client.cancel_orders([...]) / client.cancel_all() / client.cancel_market_orders()
client.get_orders(OpenOrderParams())   # reconcile intended vs actual
client.get_trades()
```
All cancels need L2 auth. Confirm the id appears in `canceled`.

### Fill listener + auto-sell timing
User channel `wss://ws-subscriptions-clob.polymarket.com/ws/user`,
`{"auth":{apiKey,secret,passphrase}, "type":"user", "markets":[CONDITION_IDS]}`.
- `trade` events carry `matched_amount`; `order` events carry `size_matched` and a
  `type` of PLACEMENT / UPDATE / CANCELLATION.
- Lifecycle **MATCHED → MINED → CONFIRMED** (branch RETRYING / FAILED); only
  **CONFIRMED** and **FAILED** are terminal.
- **Gate the auto-SELL on `CONFIRMED`**, not MATCHED — a MATCHED trade can still
  FAIL, and selling against a fill that later fails leaves you short.
  (`exec_engine/user_stream.py` parses these; for live, wire its `on_fill` →
  filter `status=="CONFIRMED"` → `OrderManager` places the exit.)

### Still verify before going live (NOT covered by surviving claims)
- **Allowances**: one-time USDC + CTF (ERC-1155) approvals to the Exchange /
  neg-risk contracts. **Orders silently fail without them.** Set + check first.
- **Fees**: confirm the real maker/taker fee on these markets (Gamma shows
  `makerBaseFee`/`takerBaseFee=1000`, `rewardsMinSize`/`rewardsMaxSpread`) — the
  unit/effective rate matters a lot to an ~11¢ margin.
- **Rate limits, nonce, server clock-sync, idempotency** — confirm before unattended.

### SDK note
`py-clob-client` is archived (still works for the EOA path). Successor is
`py-sdk` (PyPI `polymarket-client` 0.1.0b8) but its README lacks mechanics —
stay on `py-clob-client` until the new SDK documents these calls.

Sources: github.com/Polymarket/py-clob-client · docs.polymarket.com (CLOB
auth / orders / cancel / user-channel) · py-clob-client issues #121/#70/#147 ·
nautilustrader Polymarket integration.

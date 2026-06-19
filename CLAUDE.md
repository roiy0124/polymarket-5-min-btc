# CLAUDE.md — BTC Up/Down 5-Minute Collector

Context for future Claude Code sessions working in this repo.

## What this project is

A **standalone data collector** for Polymarket's "Bitcoin Up or Down (5-minute)"
markets. It is a sibling of the user's main `polymarket project` (whale tracker)
but a separate repo with its own purpose.

**Current mission: DATA GATHERING ONLY — it does not trade.** The goal is to
capture a clean, high-frequency time series so the user can later mine it for a
statistically profitable limit-order strategy (place limit buys at the right
moment in the 5-min window, exit with limit sells shortly after). Do not add
trading/execution code unless the user explicitly asks for that phase.

Dependencies: `collector.py` and `peek.py` are **pure standard library** (keep
them that way). `ws_collector.py` (the real-time layer, added after a deep-research
pass) needs **`websockets`** — the one approved dependency, because stdlib has no
WebSocket client and WS is materially more reliable/complete than REST polling for
this use case. Do not add further pip packages without asking. (Analysis tooling
using pandas is fine as a *separate* opt-in script.)

## Architecture: HYBRID (WebSocket primary + REST fallback)

A deep-research pass (see memory `btc-updown-data-reliability`) established that
reliable capture for a resting-limit-order strategy needs BOTH:

- **`ws_collector.py`** — the high-fidelity feed. Subscribes to the Polymarket
  CLOB **market channel** (`wss://ws-subscriptions-clob.polymarket.com/ws/market`,
  public, no auth) and records EVERY order-book event (`book` snapshots,
  `price_change` deltas, `last_trade_price` trade prints, `tick_size_change`)
  plus Binance `@bookTicker` BTC ticks. This captures sub-second order flow and
  fills that 1/s REST polling fundamentally misses.
- **`collector.py`** — kept as the REDUNDANT FALLBACK. The market WS has a
  documented "silent freeze" mode (stays PING-healthy but sends no data for
  hours); REST keeps working during it. `collector.py` also owns the
  per-window strike / final / official-resolution bookkeeping.

Run BOTH together. `ws_collector.py` has its own 120s data-inactivity watchdog
that force-reconnects. Both write to the same `btc_updown.db`.

Key constraint to design around: **queue position is NOT observable** — the
public feed gives aggregate size per price level, not per-order ordering. Fill
probability must be MODELED (depth at price + trade volume printing through it),
not measured exactly.

## How the market / auto-switch works (the key insight)

- Each market is a 5-minute window. The **slug IS the window-start Unix
  timestamp**: `btc-updown-5m-1781833800` started at `1781833800`.
- So the live window is always `floor(now/300)*300` and the slug is derivable —
  **no scraping, no search, no manual redirect.** When the clock crosses a
  boundary the collector recomputes the slug, fetches the new market's token IDs,
  and starts capturing it; it also settles the window that just closed.
- This auto-switch was the user's explicit requirement ("every 5 min redirect to
  the next live market"). It is already handled in `collector.py` — don't
  reinvent it.

## Resolution source caveat (important for strategy validity)

Markets settle on the **Chainlink BTC/USD data stream**
(https://data.chain.link/streams/btc-usd), which is auth-gated. We log **Binance
spot** and **Pyth** as proxies. They track Chainlink within a few dollars, but
the basis near the window boundary can flip an outcome. Before trusting any
edge, compare each proxy against the official `resolved_outcome`. A Chainlink
adapter is a clean future drop-in in `feeds.py`.

## Architecture

| File | Role |
|------|------|
| `feeds.py` | Data sources: Gamma (market metadata + official resolution), CLOB (`/book` per outcome token = the odds), Binance, Pyth. All stdlib HTTP. |
| `storage.py` | SQLite schema + writers. Tables: `windows`, `snapshots` (REST) + `book_events`, `trades`, `btc_ticks` (WS). |
| `collector.py` | REST loop + fallback: discover live window → snapshot → capture strike/final → settle closed windows. Tunables are constants at the top. |
| `ws_collector.py` | Async WebSocket layer: market-channel events + Binance bookTicker → buffered batch writes. Watchdog reconnect. Needs `websockets`. |
| `peek.py` | Read-only inspection (`python peek.py`, `python peek.py windows`). |

### Data model (`btc_updown.db`, SQLite — gitignored)

- **`windows`** — one row per 5-min market: `window_start` (PK, == slug ts),
  `token_up`/`token_down`, `strike_binance`/`strike_pyth` (price at start),
  `final_binance`/`final_pyth` (price at end), `our_outcome` (final ≥ strike),
  `resolved_outcome` (official), `partial` (1 = joined mid-window, strike not exact).
- **`snapshots`** — the time series: `ts` (unix epoch) + `ts_utc` (exact global
  time, ISO-8601 UTC, ms), `time_left`, `up_*`/`down_*` odds (bid/ask/mid/spread),
  `up_book`/`down_book` (JSON top-10 depth), `btc_binance`, `btc_pyth`.
- Join on `window_start`.

Outcome token order: `outcomes` is `["Up","Down"]`, so `clobTokenIds[0]` = Up,
`[1]` = Down.

### WS stream tables

- **`book_events`** — every market-channel order-book event. Columns: `recv_ts`,
  `recv_utc`, `window_start`, `asset_id`, `event_type` (`book`/`price_change`/
  `tick_size_change`), `src_ts`, `hash`, `payload` (raw JSON verbatim).
- **`trades`** — `last_trade_price` prints: `price`, `size`, `side` (BUY/SELL),
  `asset_id`, `window_start`, raw `payload`.
- **`btc_ticks`** — Binance `@bookTicker`: `bid`, `ask`, `mid`, `update_id`.

## Run / verify

Run BOTH collectors (separate processes, same DB):
```sh
pip install -r requirements.txt   # installs websockets (for ws_collector only)
python collector.py               # REST fallback + windows/strike/resolution
python ws_collector.py            # WebSocket high-fidelity stream
python peek.py                    # summary incl. ws stream counts
python peek.py windows            # one row per 5-min market
```

NOTE: the WS feed is high-volume (order of ~10s of GB/day of `book_events` raw
deltas in an active market). If a retention/compaction policy exists, respect it;
if not and disk is a concern, that's the first thing to add (keep `trades` +
window summaries long-term, prune/compress raw `price_change` payloads after N days).

A short `timeout`/Ctrl-C run is enough to smoke-test; if a run crosses a
:00/:05/... boundary you'll see the auto-switch (a new `windows` row + odds reset).

## Conventions

- Match the existing stdlib-only, no-framework style.
- Each data source must fail independently — one feed being down should never
  drop the whole snapshot (see `fetch_tick` swallowing per-source exceptions).
- Tunables (poll cadence, tail behavior, DB path) live as constants at the top of
  `collector.py`. Prefer adjusting those over hard-coding.

## Likely next phases (when the user asks)

1. Let it collect for a while, then build an **analysis** script/notebook:
   load to pandas, label each window, study odds-vs-time and strike-vs-price
   dynamics, look for the limit-order edge.
2. Add a **Chainlink** price adapter to `feeds.py` to match resolution exactly.
3. Only after an edge is validated: a separate execution/trading layer.

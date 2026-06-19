# BTC Up/Down 5-Minute Collector

Captures a clean, high-frequency time series for Polymarket's **Bitcoin Up or Down
(5-minute)** markets, so the data can later be mined for a statistically profitable
limit-order strategy.

Right now this project **only gathers data** — it does not trade.

## What it captures

For the *currently live* 5-minute market, every ~1 second (faster in the final 20s):

| Field | Meaning |
|-------|---------|
| `time_left` | seconds until the window resolves |
| Up / Down odds | best bid, best ask, mid, spread + top-10 order-book depth per outcome |
| target price (`strike`) | BTC price at the **start** of the window |
| current price | BTC price right now (Binance + Pyth) |
| resolution | official `Up`/`Down` once the window settles |

## How "next market" auto-switching works

No scraping or redirect logic. The market slug **is** the window-start Unix
timestamp (e.g. `btc-updown-5m-1781833800` started at `1781833800` =
2026-06-18 21:50 ET), and each window is exactly 300 seconds. So the live window
is always `floor(now/300)*300`. When the 5-minute clock rolls over, the collector:

1. recomputes the new window, builds the new slug, fetches the new market's token IDs,
2. starts capturing it immediately,
3. settles the window that just closed (records final price + official Up/Down).

This runs forever with no manual step.

## Run

**Use the supervisor — it is the single entry point and keeps everything alive
until you stop it.** Do NOT run `collector.py` by hand in a terminal: a foreground
process dies when the terminal closes (that looks like "it auto-stops"). The
supervisor runs detached, restarts any child that exits, and survives terminal
closes.

```sh
pip install -r requirements.txt   # websockets (needed by ws_collector only)

python supervisor.py       # starts + supervises collector + ws_collector + viewer
```
Stop everything: create an empty file named `STOP` in this folder, or Stop-Process
the supervisor PID. To launch detached on Windows so it survives the terminal:
`Start-Process python -ArgumentList "supervisor.py" -WindowStyle Hidden`.

Watch / inspect (read-only, run anytime):
```sh
python peek.py             # CLI summary (incl. ws stream counts)
python peek.py windows     # one row per 5-min market (strike / final / resolution)
# live dashboard: open http://127.0.0.1:8765 in a browser
```

The individual processes (`collector.py`, `ws_collector.py`, `viewer.py`) can be
run standalone for debugging, but for normal use let the supervisor own them.

`collector.py` and `peek.py` are pure standard library; `ws_collector.py` needs
`websockets`. The WS feed is high-volume (~tens of GB/day in an active market) —
see the data-retention note below.

### Why both?

The Polymarket market WebSocket has a documented "silent freeze" failure mode
(stays connected and PING-healthy but stops sending data for hours), during which
the REST endpoints keep working. So the REST poller is the redundant safety net,
not redundant work. The WebSocket captures every sub-second order placement,
cancel, and fill — which 1/second REST polling fundamentally cannot.

## Data model (`btc_updown.db`, SQLite)

- **`windows`** — one row per 5-minute market: `strike_binance/pyth`,
  `final_binance/pyth`, `our_outcome` (final ≥ strike), `resolved_outcome`
  (official), `partial` (1 if we joined mid-window so the strike isn't exact).
- **`snapshots`** — the time series: `ts` (unix epoch) + `ts_utc` (exact global
  time, ISO-8601 UTC, ms precision), `time_left`, `up_*`/`down_*` odds,
  `up_book`/`down_book` (JSON depth), `btc_binance`, `btc_pyth`.

Join them on `window_start`.

## Important caveat: resolution source

These markets settle on the **Chainlink BTC/USD data stream**
(<https://data.chain.link/streams/btc-usd>), which is auth-gated. We log
**Binance spot** and **Pyth** as proxies — they track Chainlink within a few
dollars, but the basis matters near the window boundary. Before trusting a
strategy, measure each proxy against `resolved_outcome` to see which best
predicts the official result. A Chainlink adapter can drop into `feeds.py` later.

## Files

- `feeds.py` — data sources (Gamma, CLOB, Binance, Pyth)
- `storage.py` — SQLite schema + writers (REST tables + WS stream tables)
- `collector.py` — REST loop + fallback (windows/strike/final/resolution)
- `ws_collector.py` — real-time WebSocket capture (book events, trades, BTC ticks)
- `peek.py` — inspect captured data (CLI)
- `viewer.py` — live browser dashboard (zero-dep, stdlib http.server)
- `requirements.txt` — `websockets` (for `ws_collector.py`)
- `ANALYSIS.md` — methodology blueprint for the analysis layer
- `STRATEGY-MEAN-REVERSION.md` — assessment of the buy-the-dip/reversion idea

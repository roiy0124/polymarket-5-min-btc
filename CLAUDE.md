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

Run BOTH together, **per coin** (see Multi-coin below). `ws_collector.py` has its own
data-inactivity watchdog that force-reconnects. Each coin's pair writes to that coin's
own `data/<coin>/live.db`. You normally don't launch these by hand — `supervisor.py`
spawns a `collector.py` + `ws_collector.py` pair for every enabled coin.

Key constraint to design around: **queue position is NOT observable** — the
public feed gives aggregate size per price level, not per-order ordering. Fill
probability must be MODELED (depth at price + trade volume printing through it),
not measured exactly.

## Multi-coin layout (BTC + ETH/SOL/XRP/DOGE/BNB)

The collector is **multi-coin**. All six markets share the slug pattern
`{coin}-updown-5m-{window_start}` and the identical schema, so each coin gets its OWN
database — `data/<coin>/live.db` (+ `data/<coin>/archive/`) — and the high-frequency
writers never contend on a single SQLite file. A coin is a **folder**, not a column,
so the per-window queries (keyed on `window_start`) are unchanged.

- **`coins.py`** is the registry + path authority: per coin it holds the slug prefix,
  the Binance symbol, and the Pyth feed id, and resolves `live_db(coin)` /
  `archive_dir(coin)` / `all_dbs(coin)`. `ENABLED` is the list the supervisor launches.
  `default_coin()` reads env **`ANALYSIS_COIN`** (default `btc`). A legacy fallback
  still resolves BTC to the old root `btc_updown.db` + `old_dbs/` if the one-time
  `migrate_to_data_layout.py` hasn't been run.
- **Collectors take `--coin`** (default btc): `python collector.py --coin eth`. The
  `--coin` selects the slug, Binance symbol, Pyth id, and `data/<coin>/` DB path.
- **Analysis/inspection is coin-selectable** with ONE switch, env **`ANALYSIS_COIN`**,
  honored by every `panel.connect()`-based tool (fairvalue, fair_vs_market, calibration,
  exit_maps, signals, flow, backtest, reversion, data_quality, combo_ev), PLUS explicit
  `--coin` on `peek.py`, `chart_capture.py`, `analysis/exit_maps.py`, and the live
  experiments. Outputs are per-coin: `exit_maps/<coin>/...`, `round_charts/<coin>/`.
- **`analyze_all.py`** runs the suite (exit maps + round-chart backfill) for many coins
  at once, each into its own folder, then builds the cross-coin gathered montages.
- **Two graph views:** PER-COIN (`exit_maps/<coin>/`, `round_charts/<coin>/` — one coin, many
  entry prices/rounds) and CROSS-COIN (`gathered/exit_maps/<side>/entry_NNc.png`,
  `gathered/round_charts/<round>.png` — the SAME graph with all coins side by side, via
  `make_gathered.py`; auto-built by menu 5/6 after the per-coin loop). All graphs use coin-correct
  labels + per-coin colors; price axes scale to each coin. (`exit_maps/`, `round_charts/`,
  `gathered/` are all gitignored.)
- **Full-history scan + hi-res (2026-06-24):** both `chart_capture` (round charts) and
  `analysis/exit_maps` SCAN a coin's whole dataset — **live DB + archives, merged** (`coins.all_dbs`)
  — so an archived coin like BTC maps its full history, not just its small post-reset `live.db`
  (BTC: 90→~1014 round charts; 120→~1117 exit-map windows). Without this BTC fell out of the
  cross-coin gathered montages. Charts render **hi-res** (round 170 dpi, exit 140 dpi); `make_gathered`
  tiles them at 200 dpi with source-preserving tiles (~1120px/tile vs the old ~324px mesh) so cross-coin
  detail is crisp on zoom (`make_gathered --dpi N` trades crispness vs file size). `BTC_ANALYSIS_DAYS`
  still narrows the exit-map window if set.

```sh
ANALYSIS_COIN=eth python -m analysis.fairvalue   # any panel analysis, scoped to ETH
python peek.py --coin sol                         # inspect SOL's DB
python -m analysis.exit_maps --coin xrp           # -> exit_maps/xrp/
python analyze_all.py                             # all six, organized per coin
```

Deferred (still BTC-only by design — they resolve via `coins.live_db("btc")`): the
closed passive-strategy experiments (`experiment_walkforward/combined/config_tod/
lookback_sweep`) and the gated/legacy execution (`phase2`, `phase2_nested`,
`paper_trade`, `live_runner`).

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

Each market settles on the **Chainlink <COIN>/USD data stream** (auth-gated). We log,
**per coin**, its **Binance spot** (primary proxy — drives strike/final/`our_outcome`)
and its **Pyth** feed: `feeds.fetch_binance(symbol)` / `feeds.fetch_pyth(pyth_id)`, both
resolved per-coin via `coins.py`. They track Chainlink within a few dollars, but the
basis near the boundary can flip an outcome. Before trusting any edge, compare each proxy
against the official `resolved_outcome`. (Note: `fetch_pyth` was once hardcoded to BTC —
it is now per-coin, so alt `price_pyth` columns finally hold the right asset.) A Chainlink
adapter is a clean future drop-in.

## Architecture

| File | Role |
|------|------|
| `coins.py` | **Coin registry + path authority.** Per-coin slug prefix / Binance symbol / Pyth id; `live_db`/`archive_dir`/`all_dbs`/`ensure_dirs`; `ENABLED`; `default_coin()` (env `ANALYSIS_COIN`). Legacy BTC fallback. |
| `feeds.py` | Data sources: Gamma (metadata + resolution), CLOB (`/book` = odds), Binance, Pyth. `slug_for/fetch_market(ws, coin)`, `fetch_binance(symbol)`, `fetch_pyth(pyth_id)`. Stdlib HTTP. |
| `storage.py` | SQLite schema + writers (coin-agnostic; opens whatever path it's given). Tables: `windows`, `snapshots` (REST) + `book_events`, `trades`, `price_ticks` (WS). `prune_ws` retention. |
| `collector.py` | REST loop + fallback, **`--coin`**: discover live window → snapshot → strike/final → settle. Writes `data/<coin>/live.db`. |
| `ws_collector.py` | Async WebSocket layer, **`--coin`**: market-channel events + Binance bookTicker → buffered writes; watchdog reconnect; per-coin `RETAIN_DAYS` prune. Needs `websockets`. |
| `supervisor.py` | Launches + auto-restarts a collector pair **per `coins.ENABLED`** (windowless on Windows) + viewer + chart_capture. Stop via Ctrl-C or a `STOP` file. |
| `migrate_to_data_layout.py` | One-time move of legacy `btc_updown.db`/`old_dbs/` → `data/btc/`. |
| `migrate_rename_columns.py` | One-time `ALTER` (done): renamed `btc_binance`/`btc_pyth`→`price_binance`/`price_pyth`, table `btc_ticks`→`price_ticks` across all DBs. |
| `peek.py` | Read-only CLI inspection, **`--coin`** (`python peek.py --coin eth [windows]`). |
| `viewer.py` | Live browser dashboard (stdlib http.server, default `:8765`). Honors `ANALYSIS_COIN`. Read-only. |
| `chart_capture.py` | Per-round price charts, **`--coin`** → `round_charts/<coin>/`. Coin-correct titles/labels + per-coin line color; price axis scales to the coin (low-priced coins not flat). Supervisor child (live) / `--once` (backfill). **Backfill merges live + archives (`coins.all_dbs`)** so an archived coin charts its full history; renders **hi-res (170 dpi)**. |
| `analyze_all.py` | Run exit maps + round charts for many coins at once (per coin) **+ the cross-coin gathered montages** at the end. |
| `make_gathered.py` | **Cross-coin montages**: tiles the SAME graph across all coins side by side → `gathered/exit_maps/<up\|down\|*_margin>/entry_NNc.png` and `gathered/round_charts/<round>.png`. Auto-run by menu 5/6 + analyze_all; menu `m` rebuilds. **HI-RES (2026-06-23):** source charts render at 140–170 dpi and the montage at 200 dpi with source-preserving tiles (~1120px/tile vs the old ~324px mesh) so you can ZOOM into cross-coin detail; `--dpi N` trades crispness vs file size. |
| `analysis/spot_data.py` | **Persistent FREE spot-history store** (NOT Polymarket): Binance public 1s klines, all 6 coins back to 2021-01, in `data/spot/<SYMBOL>/` (gitignored .zip + fast .npz cache). `load_range(sym,start)`; CLI `python -m analysis.spot_data --coins all --start 2021-01`. This is the **deep Stage-1 data** (years, vs our ~weeks of token quotes) — see memory `spot-history-two-stage-validation`. |
| `analysis/spot_leadlag.py` | **Stage-1 signal-existence harness** (spot-only, no Polymarket): does BTC's causal trailing-Hs move predict an alt's 5-min UP outcome; rolling sign-stability + dual-label + `--alts all` cross-coin. Outputs `spot_leadlag/`. Confirms/kills a signal's EXISTENCE deep; does NOT test EV (that's Stage-2, needs live quotes). |

### Data model (per coin: `data/<coin>/live.db`, SQLite — gitignored; one DB per coin, identical schema)

- **`windows`** — one row per 5-min market: `window_start` (PK, == slug ts),
  `token_up`/`token_down`, `strike_binance`/`strike_pyth` (price at start),
  `final_binance`/`final_pyth` (price at end), `our_outcome` (final ≥ strike),
  `resolved_outcome` (official), `partial` (1 = joined mid-window, strike not exact).
- **`snapshots`** — the time series: `ts` (unix epoch) + `ts_utc` (exact global
  time, ISO-8601 UTC, ms), `time_left`, `up_*`/`down_*` odds (bid/ask/mid/spread),
  `up_book`/`down_book` (JSON top-10 depth), `price_binance`, `price_pyth`.
- Join on `window_start`.

Outcome token order: `outcomes` is `["Up","Down"]`, so `clobTokenIds[0]` = Up,
`[1]` = Down.

### WS stream tables

- **`book_events`** — every market-channel order-book event. Columns: `recv_ts`,
  `recv_utc`, `window_start`, `asset_id`, `event_type` (`book`/`price_change`/
  `tick_size_change`), `src_ts`, `hash`, `payload` (raw JSON verbatim).
- **`trades`** — `last_trade_price` prints: `price`, `size`, `side` (BUY/SELL),
  `asset_id`, `window_start`, raw `payload`.
- **`price_ticks`** — Binance `@bookTicker`: `bid`, `ask`, `mid`, `update_id`.

## Run / verify

Normally just run the supervisor — it launches a collector pair per enabled coin
(windowless) plus the viewer + chart_capture, and restarts any that die:
```sh
pip install -r requirements.txt   # installs websockets (for ws_collector only)
python supervisor.py              # ALL enabled coins; stop via Ctrl-C or a STOP file
# ...or a single coin by hand:
python collector.py --coin eth
python ws_collector.py --coin eth
python peek.py --coin eth          # summary incl. ws stream counts
python peek.py --coin eth windows  # one row per 5-min market
```

NOTE: the WS feed is high-volume (~10s of GB/day of `book_events` per active coin, so
~6× across all six). Retention EXISTS: `ws_collector`'s `pruner` calls
`storage.prune_ws` to drop `book_events`/`price_ticks` older than `RETAIN_DAYS` (default 3)
per coin; `windows`/`snapshots`/`trades` are kept long-term. Watch free space — lower
`RETAIN_DAYS` or trim `coins.ENABLED` if disk gets tight.

A short `timeout`/Ctrl-C run is enough to smoke-test; if a run crosses a
:00/:05/... boundary you'll see the auto-switch (a new `windows` row + odds reset).

## Conventions

- Match the existing stdlib-only, no-framework style.
- Each data source must fail independently — one feed being down should never
  drop the whole snapshot (see `fetch_tick` swallowing per-source exceptions).
- Tunables (poll cadence, tail behavior, DB path) live as constants at the top of
  `collector.py`. Prefer adjusting those over hard-coding.

## Research state (read before proposing strategy work)

The full strategy-research log is in **`EXPERIMENTS.md`** (+ agent memory). Short version,
on BTC: **no profitable retail edge found.** Passive resting-limit variants die to adverse
selection. The fair-value **TAKER** has a real ~1s lead over the quote, but the bid-ask
spread caps it at ~breakeven and Polymarket's confirmed dynamic **taker fee**
(`crypto_fees_v2`, ~3.5%+/stake on the 5-min market) sinks it net-negative. The market is
**efficient on knowledge** (price Brier ~0.12; recent trend predicts the outcome but the
price already prices it). All measured with window-clustered bootstrap CIs.

Current direction: **cross-asset / SMT across the six coins** — do sleepier alts lag, or
lead each other, enough to clear the fee? That is *why* the multi-coin collection exists.
`live_runner.py` stays **gated** and must NOT be armed until an edge clears validation.

**UPDATE 2026-06-23 (full idea audit + combination program — see `STRATEGY-FAVORITE-TAIL.md`):**
Best strategy = **favorite-tail taker, hold-to-resolution** (`experiment_favorite_tail.py`) — causal,
real-time-implementable, but **BREAKEVEN** (pooled +0.005/$1, CI incl 0). Every idea was tested both
standalone AND as a *component/gate* on it; all dead except ONE live thread: the **BTC-opposing
risk-filter** (`experiment_b_component.py`) — skip an alt favorite-tail entry when BTC's last ~15s move
opposes the favorite. First genuinely directional signal (permutation p=0.002, all-coin/LOCO) but NOT
deployable yet (its Wilson pass hangs on a 1-loss subset over ~25h). **PRE-REGISTERED** (memory
`b-riskfilter-preregistered`); re-test with **`validate_b_riskfilter.py`** (params LOCKED; `--all` =
in-sample dry-run) after ~2–4 weeks more data. `net_ev.py` = the fee-aware EV helper. No new collection
needed — just keep the running supervisor (don't start a 2nd = dup rows). **Proven-dead experiments are
archived in `dead_ends/`** (see its README); the dead executors (`phase2*.py`, `paper_trade.py`) stay in
root for `menu.py`, with `phase2_nested.py` bridging to the archived shared libs.

**UPDATE 2026-06-24 (TWO-STAGE validation + deep spot history — see `winning_strategies/` + memory
`spot-history-two-stage-validation`):** The cross-asset SMT signal is split into **Stage 1 = does it EXIST/is it
STABLE** (testable on deep free spot, years back) vs **Stage 2 = does it BEAT THE QUOTE+FEE** (only testable on
our live token data — the 5-min product launched 2026-02-12, so price history is hard-capped; spot can't recover
the ask). Built `analysis/spot_data.py` (free Binance 1s store, all 6 coins to 2021-01 in `data/spot/`, 23GB
gitignored) + `analysis/spot_leadlag.py`. **Stage-1 RESULT: PASS, emphatically** — BTC's causal 15s move predicts
every alt's 5-min UP with r≈+0.11–0.13, **100% sign-stable across the full 5.5 years (every regime, 575k
windows/coin) AND across 35 (coin×framing) robustness cells**; sign is POSITIVE (co-move, not the academic
seesaw's hourly-negative). Kills the non-stationarity worry. **BUT this is signal-existence = the UPPER BOUND, NOT
EV**: the alt quote prices most of it (alt-own move, the strongest predictor, is mechanical/already in the ask),
so Stage-2 (does BTC's lead add value *beyond* the priced favorite) still needs live data = exactly the
pre-registered **B risk-filter** (`validate_b_riskfilter.py`, LOCKED). New **`winning_strategies/`** folder = the
honest tiered roster (Tier 1 deployable-winner = empty; Tier 2 = favorite-tail proven-causal-breakeven; Tier 3 =
B risk-filter + spot lead-lag, pre-registered). `live_runner` stays GATED.

Future drop-ins (when asked): a **Chainlink** price adapter in `feeds.py` to match
resolution exactly; verified alt-specific tooling.

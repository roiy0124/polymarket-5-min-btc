# Changelog

A high-level history of what's been built. Newest first. (Per-commit detail is in
`git log`; the deep-research findings behind decisions are in the `*.md` docs.)

## Execution — Phase 1 signal finder (`analysis/signals.py`)
- Finds limit-order signals from the exit-map data that clear user floors (min
  win-rate AND min ROI) in ALL THREE lookbacks (**6h / 12h / 24h**). Salvages a line
  by shrinking the buy-window (≥30s) and/or lowering the sell price `T`; ranks by
  the sweet spot (worst-case-win × ROI). `--min-entry` drops illiquid penny tokens.
  Sizes `shares = X_usd / z`. Outputs a ranked table + `signals.json`. Read-only;
  manual validation gates Phase 2 (the executor — not built yet).

## Operator & data management
- **`menu.py`** — interactive operator menu wrapping everything (inspect, generate
  maps/charts, run analyses, **Phase-1 signal finder**, paper-trade, start/stop
  collectors). Single entry point.
  *(Named `menu.py`, not `operator.py` — that would shadow the stdlib `operator`.)*
- **Create new database** (menu 16) — archives the current DB into `old_dbs/` and
  starts a fresh one; collectors auto-restart.
- **Analysis scope** — every analysis asks `current DB` vs `last X days`; the
  latter merges the current DB + every archive in `old_dbs/` (env `BTC_ANALYSIS_DAYS`).

## Exit maps (`analysis/exit_maps.py`) — evolved iteratively
- Per-entry-price scatter (x = entry time, y = exit value) for up/down tokens.
- **Uniform 1¢ binning** (floor, not `round()` — fixed an even/odd-cent artifact).
- **Settlement-aware exit value**: a real bounce shows its height; no sellable
  bounce → 0 (complete loss) / 1 (held win). The 0-floor shows the true downside.
- **0.4s execution-latency delay** before the exit search (no reacting to ticks you
  couldn't have).
- **Sweet-spot sell-target overlay**: highlights the (entry-time window ≥30s, single
  sell price T) that maximizes **win-rate × ROI**; the purple line is the sell price
  (dots above = win, below = loss), shown in the right margin, labeled with
  win% / ROI / EV.

## Per-round charts (`chart_capture.py`, `round_charts/`)
- One chart per resolved round from the DB: Up/Down token lines + **BTC price and
  target/strike on a second axis** + Polymarket official price dots (live overlay).
- Runs as a supervised service; backfills on startup.

## Reliability
- **`supervisor.py`** — keeps collector + ws_collector + viewer + chart_capture
  alive (auto-restart, backoff), unbuffered child logs; the real "run until
  interrupted" guarantee.
- Crash-proof collector loop; **WS freeze fix** (20s watchdog + 60s proactive
  reconnect → eliminated the documented market-channel silent-freeze).
- **`analysis/data_quality.py`** — liveness / coverage / gap / WS-freeze audit.

## Analysis toolkit (`analysis/`)
- `calibration_test`, `fair_vs_market`, `fairvalue`, `reversion`, `combo_ev`,
  `flow`, `backtest`, `panel`. Rigor baked in: one-obs-per-window, Wilson CIs,
  bootstrap, multiple-testing awareness, out-of-sample (see `DATA-ANALYSIS-TOOLKIT.md`).

## Execution engine (`exec_engine/`, `paper_trade.py`) — paper-safe
- Limit orders, cancel, auto-sell-on-fill, RiskAverse paper fills, user-channel
  listener. `LiveBroker` wired per verified recipe but gated (live + EOA creds);
  see `EXECUTION.md`.

## Data collection (hybrid)
- `collector.py` (REST 1/s, deterministic market discovery, strike/final/resolution)
  + `ws_collector.py` (CLOB market channel: book/price_change/trades + Binance
  bookTicker; auto-retention). SQLite (WAL).

## Reference docs
`README.md`, `ANALYSIS.md`, `ANALYSIS-STRATEGY.md`, `DATA-ANALYSIS-TOOLKIT.md`,
`STRATEGY-MEAN-REVERSION.md`, `EXECUTION.md`, `NIGHT-LOG.md`, `round_charts/README.md`.

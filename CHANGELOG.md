# Changelog

A high-level history of what's been built. Newest first. (Per-commit detail is in
`git log`; the deep-research findings behind decisions are in the `*.md` docs.)

## Execution — Phase 2 paper executor (`phase2.py`, `exec_engine/strategy_runner.py`)
- **Live forward-test of the Phase-1 signals — paper-only, nothing real is traded.**
  Reads `signals.json` and, every 5-min window, trades each signal whose predicted
  EV clears your floor (`--min-ev`): at the signal's buy-window (`elapsed >= t1·60`)
  it rests a simulated BUY at the entry price with an auto-sell at the target; cancels
  if unfilled by `t2`; settles any held position to 1.0/0.0 at resolution. Fills are
  simulated by the `PaperBroker` (RiskAverse queue model) against the REAL recorded
  trade stream — the honest, adverse-selection-adjusted, out-of-sample test before any
  live wiring. Menu option **12**. Appends a per-leg ledger to `paper_trades.csv`
  (window, fill y/n, exit/settle px, realized PnL, predicted EV) for paper-vs-predicted
  comparison. Relaxed paper caps so real ~$1-2 bets trade (live `$5` floor reserved for
  `LiveBroker`). `strategy_runner.py` is broker-agnostic — live = swap the broker +
  gate the auto-sell on the CONFIRMED user-WS status. Verified by `exec_engine.phase2_selftest`.
- **Bot startup (menu 12)** checks signal freshness before trading: if `signals.json`
  is **≤ 20 min** old it shows the signals (`--show`, no recompute) and you pick the EV
  floor; if **> 20 min** old (or missing) it **re-evaluates on fresh live data** first —
  reusing the prior floors automatically — and only then asks for the EV floor. Finder
  now stores `min_entry` in `signals.json` so re-eval reproduces faithfully.
- **Bot startup now asks the data scope** (like exit maps): when it (re)generates
  signals it offers `[1] current fresh DB` or `[2] last X hours` (merging `old_dbs/`),
  so you can build signals from more history than the live DB holds — useful after a DB
  reset. `ask_scope(unit="hours")` converts to fractional `BTC_ANALYSIS_DAYS`. (The live
  paper-execution loop still runs on the current DB — scope only governs the signal
  source. Pick ≥ 24h so the 6h/12h/24h lookbacks all have data.)
- **Paper ledger summary (`analysis/paper_ledger.py`, menu 13)** — the scoreboard for
  the forward-test. Per signal and overall: attempts, fill%, win%, total PnL, and three
  EVs — `EVpred` (Phase-1 prediction), `EVfill` (realized per $1 on filled legs, the
  apples-to-apples check), and `EVatt` (realized per $1 across all attempts, folding in
  fill rate). Prints the **adverse-selection gap** (`EVfill − EVpred`). Flags signals
  with < 10 attempts as noisy. Ledger gains exact `bought`/`sold` columns so realized EV
  is computed from actual filled quantities, not assumed full fills.

## Round reviews (`analysis/round_review.py`, `round_reviews/`, menu 14)
- Per-round charts of what the **paper executor** actually did: the traded token's price
  path with **green** entry-fill dots, the **purple** expected-sell target up the y-axis,
  and the **orange** best price reachable after entry until round end. Title shows resolved
  outcome, paper PnL, and **targets reached N/M**. When entries ride the price the wrong way
  and 0/M targets are reached, it's adverse selection made visible (the limit only fills when
  the move is against you). Reads `paper_trades.csv` + the DB price path; one PNG per round.

## Execution — Phase 1 signal finder (`analysis/signals.py`)
- Finds limit-order signals from the exit-map data that clear user floors (min
  win-rate AND min ROI) in ALL THREE lookbacks (**6h / 12h / 24h**). Salvages a line
  by shrinking the buy-window (≥30s) and/or lowering the sell price `T`. `--min-entry`
  drops illiquid penny tokens. Sizes `shares = X_usd / z`. Outputs a ranked table +
  `signals.json`. Read-only; manual validation gates Phase 2 (the executor — not built).
- **Ranks by true expected value**, not just upside: `EV = win·ROI − (1−win)` (a miss
  loses the whole stake, since a dot under the sell line settles toward 0), using the
  worst-case win-rate across lookbacks. This rewards **consistency** — a 60%/+30% line
  is EV −0.22 (a money-loser) and is dropped. `--min-ev` floor (default 0 = must be
  profitable). The selection now also optimizes EV, so it prefers a slightly lower
  sell with a higher, steadier win-rate over a high-ROI/low-win line.
- **Input ergonomics**: runs interactively (`python -m analysis.signals`) — prompts
  for win/ROI/USD if not passed. Win-rate accepts `0.67` or `67` (anything >1 read as
  a percent, fixing the `67 → 6700%` footgun).

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

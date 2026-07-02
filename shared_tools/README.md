# Shared Tools Catalog — BTC Up/Down Collector

*The INDEX of reusable, strategy-agnostic primitives. (Compiled 2026-06-24 by a repo-wide scan.)*
Sibling of `winning_strategies/` (the strategy roster): that folder is *what we bet*; this is *what we build with*.

## What a "shared tool" is

A **shared tool** is a strategy-*agnostic* primitive — a function or class any experiment, analysis pass, or
future strategy should **import rather than rebuild**: data loaders, fee/EV accounting, statistical tests, the
fair-value and cross-asset models, price-at-time lookups. The bias is reuse: if a piece of logic is correct
once, every new strategy starts from it instead of re-deriving (and re-bugging) it.

**Rule:** existing tools **stay where they live** — moving them would break the dozens of `import` sites across
`collector.py`, `ws_collector.py`, the `experiment_*.py` files, and `analysis/`. This catalog is the **INDEX**,
not a new home. The promotions in §2 are the *only* sanctioned consolidations, and even those should re-export
so old import paths keep working.

## 1. Existing shared primitives (real import paths)

### Data & paths
| Tool | Import / entrypoint | What it does | Reuse it for |
|---|---|---|---|
| Coin registry + paths | `import coins` → `coins.COINS`, `coins.ENABLED`, `coins.live_db(coin)`, `coins.archive_dir(coin)`, `coins.all_dbs(coin)`, `coins.binance_symbol(coin)` | Multi-coin registry (slug / Binance symbol / Pyth id / color) + per-coin DB-path authority incl. legacy BTC fallback. | Anything that iterates coins or opens a coin's DBs. |
| Data sources | `import feeds` → `feeds.slug_for`, `fetch_market(ws, coin)`, `fetch_book`, `fetch_binance(symbol)`, `fetch_pyth(pyth_id)`, `fetch_price_history` | Stdlib HTTP to Gamma (metadata/resolution), CLOB (`/book` odds+depth), Binance spot, Pyth. Each source fails independently. | Collectors, `chart_capture`, any live pricer/executor. |
| SQLite schema + writers | `import storage` → `SCHEMA`, `connect`, `insert_snapshot/book_events/trades/price_ticks`, `upsert_window`, `set_strike/set_final/set_resolution`, `prune_ws` | Coin-agnostic schema + WAL init + batch writers + retention prune. | Any collector; all readers depend on the schema. |
| Panel loader (merged multi-DB) | `from analysis import panel` → `panel.connect(path=None, coin=None)`, `build_panel(conn, horizon_s=240.0)`, `outcome_base_rate(rows)` | Merged read-only view across a coin's live DB + archives (honors `BTC_ANALYSIS_DAYS`); one row per settled window. | Per-window analyses: fairvalue, calibration, signals, backtest, combo_ev. |
| Deep spot history (1s klines) | `from analysis import spot_data` → `load_range(symbol, start_ym)`, `COINS`, `SYM2COIN` | Free Binance public 1s klines (2021-01→), monthly-zip fetch + npz cache, resumable. | `cross_asset_factor`, `spot_leadlag`, reversion, deep-history vol / label-robustness. |

### Pricing / fair value
| Tool | Import / entrypoint | What it does | Reuse it for |
|---|---|---|---|
| Bachelier fair value | `from analysis.fairvalue import fair_up, phi` → `fair_up(conn, ws, horizon_s)` | Causal per-window fair P(Up)=Φ((S−K)/(σ√T)), σ from the window's own Binance path up to the horizon (no look-ahead). | Score-based filters, mispricing checks, any model needing a fair probability. |

### Cross-asset / factor
| Tool | Import / entrypoint | What it does | Reuse it for |
|---|---|---|---|
| Two-factor proportionality | `from analysis.cross_asset_factor import factor_fit, pca_dominance, load_minute_returns` | OLS `r_alt ~ r_btc + r_eth`: betas, R², idio vol, residuals; PCA dominant-coin detector; memory-safe aligned multi-coin returns. | Proportionality baselines, dominance/regime studies, SMT prerequisites. |
| **Adaptive (EWMA) beta + z detector** | `from analysis.cross_asset_factor import adaptive_betas, adaptive_z_all, AdaptiveFactorModel` | Causal time-varying betas (t−1 betas score t) + un-proportionate-move z-score; `AdaptiveFactorModel(alts, hl).update(r)` is the **live, incremental** version (one bar → z per coin; backtest == live, verified). | Fear/divergence gating, any real-time cross-asset signal, proportionality-residual scoring. **Works on any returns matrix incl. token prices (stock-vs-stock).** |

### Evaluation & stats
| Tool | Import / entrypoint | What it does | Reuse it for |
|---|---|---|---|
| Wilson lower bound (authoritative) | `from net_ev import wilson_lb` → `wilson_lb(k, n, z=1.96)` | One-sided Wilson LB of a win-rate; honest where bootstrap CIs degenerate (0-loss subsets). | Consistency ranking, validation, any high-win-rate subset. |
| Brier score | `from analysis.fairvalue import brier` | MSE of probability predictions. | Model-vs-market scoring. |
| Binomial tests + FDR | `from analysis.calibration_test import wilson, binom_test_two_sided, bh_significant, bootstrap_ci` | Two-sided Wilson CI, exact binomial p, Benjamini-Hochberg FDR, generic resample CI. | Per-bin calibration, multi-test correction, CIs on lists. |
| Correlation / directional stats | `from analysis.spot_leadlag import signed_r, hit_edge, fisher_ci, ar1_halflife, boot_ci, PriceAt, build_rows, rolling` | signed-r, hit-edge, Fisher CI, AR1 half-life, bootstrap; `PriceAt` (vectorized backfill lookup), `build_rows` (causal window grid), `rolling` (regime stats). | Lead-lag measurement, persistence/decay, rolling/walk-forward, causal price-at-time on numpy arrays. |
| Signal-ranking helpers | `from analysis.exit_maps import wilson_lb, power_min_n, map_admit_threshold` | One-sided Wilson LB at ranking z, min-n power gate, density-aware admission floor. | Line ranking; anti-cherry-pick sample-size gates. *(its `wilson_lb` is a z=1.0 dup of `net_ev.wilson_lb` — see §2.2)* |
| Flow / toxicity | `from analysis.flow import flow_imbalance, find_dip` | Signed trade-imbalance (informed-flow proxy); first dip→recover scan. | Toxicity filters, dip/recover detection. |
| Data-quality audit | `from analysis.data_quality import gap_stats` | SQL-LAG gap analysis: n, span, max gap, >2/5/30s counts, downtime. | Any DB coverage audit. |

### Execution & accounting
| Tool | Import / entrypoint | What it does | Reuse it for |
|---|---|---|---|
| **Fee-aware net EV** | `from net_ev import net_ev_per_dollar, taker_fee_per_stake, maker_rebate_per_stake, breakeven_winrate` | Per-$1-staked net EV with the confirmed Polymarket taker-fee curve (`0.07·p·(1−p)`) + hold/maker-rest exits; breakeven solver. | **Every** profit calc — favorite-tail, fear-dip, b-component, validation, any backtest. |
| Paper execution harness | `from exec_engine.broker import PaperBroker, OrderManager` | Resting-limit sim: queue/fill model + settlement; `OrderManager` brackets entry+auto-exit. | `phase2`, `paper_trade`, any paper forward-test. |

### Inspection & charting *(infra — listed so they aren't reinvented)*
`python peek.py [windows] [--coin C]` · `python viewer.py [PORT]` · `python chart_capture.py [--coin C] [--once]` · `python supervisor.py` · `python make_gathered.py` / `analyze_all.py`

## 2. PROMOTE THESE (duplication found)

Ordered by call-site count. Proposed homes: a new **`analysis/stats.py`** (pure stats) and **`analysis/loaders.py`**
(multi-coin DB access), each **re-exporting** existing names so current imports keep working.

1. **Fee curve `0.07·a·(1−a)` — 4+ re-definitions** (`experiments/experiment_favorite_tail.py:69`, `experiments/experiment_b_component.py:198`, `dead_ends/experiment_favtail_adaptive.py:45`, inline `experiments/experiment_favorite_tail.py:125`). → delete all; `from net_ev import taker_fee_per_stake`.
2. **`wilson_lb` — 3 implementations** (`net_ev.py:70` authoritative, `analysis/exit_maps.py:52` z=1.0, `dead_ends/...adaptive.py:35`). → keep `net_ev`; `exit_maps` imports it and passes `z=WILSON_Z`; drop the dead-ends copy.
3. **Window-clustered bootstrap CI — 5+ hand-rolls** (favorite_tail, b_component:109, favtail_adaptive:115, spot_leadlag:129, calibration_test:85, validate_b_riskfilter). → one `analysis/stats.py:bootstrap_ci(data, fn, B=5000, alpha=0.05, cluster_key=None, seed=1)`.
4. **Multi-coin loader boilerplate — 7+ experiments** (the `for db in coins.all_dbs(coin): connect; query windows+snapshots` loop). → `analysis/loaders.py:iter_windows(coin, filters)` + `load_snapshots(coin, ws, cols)`; reuse `panel`'s ATTACH-merge.
5. **Favorite-tail position loader — 3+ near-identical copies** (b_component:60 re-imported by validate_b_riskfilter:30, two dead_ends, favorite_tail:26). → `analysis/loaders.py:load_favorite_positions(coin, tl_target, min_ask, tol, min_gap_bps=0)`.
6. **Causal price-at-time / backfill — 3+ copies** (b_component `Series.at` bisect, idio_spikes, lookahead_taker, vectorized `spot_leadlag.PriceAt`). → promote `PriceAt` as canonical + a scalar `TimeseriesLookup(d).at(t, tol=3)`.
7. **EV-summary aggregator — 3 names, one job** (`favorite_tail.summarize`, `validate_b_riskfilter.ev_of`, `fear_dip_variants.ev_stats`). → one `analysis/stats.py:ev_summary(rows, boot=4000)`.
8. **Pearson correlation — 2+ copies** (b_component:97, xasset_smt, lookahead_taker streaming). → `analysis/stats.py:pearson` + `PearsonAccumulator`; move the `signed_r`/`hit_edge`/`fisher_ci` trio here too.
9. **Placebo / permutation tests — inline in 2+** (validate_b_riskfilter `rand_ev`/`perm_ev`, fear_dip_variants random-subset). → `analysis/stats.py:placebo_test(...)` + `permutation_test(...)`.

## 3. GAPS (useful shared tools that don't exist yet)

- **`analysis/stats.py`** — no single import for win-rate CIs / bootstrap / correlation / EV-summary / null tests (scattered across net_ev, calibration_test, spot_leadlag, exit_maps, experiments). §2 collapses them here.
- **Overfitting guards** — the project repeatedly warns of data-mining bias but ships **no `deflated_sharpe`** and **no purged/embargoed CV**. Add `deflated_sharpe(returns, n_tests)` and `purged_rows(rows, test_window, embargo)`.
- **`analysis/loaders.py`** — canonical `iter_windows` / `load_snapshots` / `load_favorite_positions` over `coins.all_dbs` (today every experiment re-opens DBs by hand).
- **Causal price-at-time util** — promote `PriceAt` + scalar `TimeseriesLookup` as the one backfill primitive (risks look-ahead drift while re-coded per experiment).
- **Generic residual helper** — `realized − expected` appears ad-hoc (`won − price`, `r_alt − pred`); add `residual_stats(obs, pred)`.

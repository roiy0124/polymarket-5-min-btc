# EXPERIMENTS.md — strategy research log

What we tried to find a profitable limit-order strategy on Polymarket "BTC Up/Down
5-minute" markets, what each experiment does, and what it found. Honest record — most
results are **negative or near-breakeven**, and that is the point: each idea was
killed (or kept) cheaply by measurement instead of expensively by trading.

> **One-line state:** on ~3 days of data, **no robust profitable edge has been found**
> for a passive resting-limit strategy. Adverse selection is the structural wall.
> Best surviving *lead*: nested gap→time + 24h robustness gate ≈ **+0.02 EV/$1 OOS**
> (marginal, gross of fees, unconfirmed). The real bottleneck is **data volume**, not
> ideas — every honest result ends at "need weeks, not days."

---

## The core problem (why everything is hard)

Each market resolves **0/1** (token → $1 or $0 at a 5-min boundary vs the Chainlink
strike). We rest a limit BUY on a cheap outcome token and auto-sell higher. The
killer, confirmed by both our backtests and microstructure theory (deep-research):

- **Adverse selection.** A resting limit only fills when price moves *against* you.
  Exit-map "win rate" ~80% collapses to ~24% on realistic queue fills; predicted EV
  +0.4 becomes realized −0.3 to −0.6. The bid-ask spread *exists because* limit orders
  near fair value have negative expected return (Glosten-Milgrom). A passive order is
  formally **short an option to informed flow**.
- **−100% losses.** A miss costs the whole stake, so low-ROI exits need ~85–94% win
  rates; raising win-rate by lowering the sell just trades ROI for win-rate at constant
  EV. (Verified empirically.)

Net: a passive resting-limit edge is *structurally* unlikely. The structurally-sound
pivot (untested) is to become the **fair-value TAKER** — take mispriced quotes when a
faster feed (Binance spot / Chainlink stream) knows fair value before the Polymarket
quote adjusts. Scaffolding exists in `analysis/fair_vs_market.py` + `calibration_test.py`.

---

## Visualization tools (in `analysis/exit_maps.py`)

| Output folder | What it shows |
|---|---|
| `exit_maps/{up,down}/` | exit value vs **entry time**; fitted sell-line (Wilson-EV best buy-window + sell) |
| `exit_maps/{up,down}_margin/` | exit value vs **BTC gap from strike** at entry; buy/sell **decision overlay** (sell line + green gap BUY-zone(s) from `best_conditional`, Wilson-adjusted, drawn so the decision can be eyeballed) |
| `exit_maps/{up,down}_margin_filtered/` | the **time** exit map of only the dots **inside the gap buy-zone** (nests gap→time); a fitted line is drawn only if it clears a **dynamic guard** (n ≥ `FILT_LINE_FRAC`×original dots — proportionate, not fixed), else "too thin after filtering" |

Run: `BTC_ANALYSIS_DAYS=3 python -m analysis.exit_maps` (merges `old_dbs/`).

Key functions: `best_sell_window` (Wilson-EV optimal buy-window+sell, with coverage
gates), `best_conditional` (jointly picks sell + gap zone by Wilson-adjusted
conditional EV), `entry_and_exit` / `entry_margin` (per-window dot + its BTC gap).

---

## Experiment scripts (standalone, NOT in the menu; all read merged `old_dbs/`)

| Script | Approach | Key finding |
|---|---|---|
| `experiment_refresh.py` | live PAPER decay test, refresh signals every 30 min | signals decay fast (~1h after generation); overfit signature |
| `experiment_walkforward.py` | walk-forward OOS backtest (generate-before-T, trade-after); `open_merged()` unions live+archive DBs | realistic fills ≈ −0.4 EV/fill; exit-map win% doesn't survive |
| `experiment_config_sweep.py` | per-block brute force: config static-vs-dynamic + fixed REF + market conditions; `--end-ts` pins identical windows | config/lookback are 2nd-order; **config adaptation HURTS** (static > dynamic); regime (time) looked dominant but later shown unstable |
| `experiment_window_features.py` | per-window winner-vs-loser feature analysis | volume / BTC-move / hour separate winners from losers but **cap at breakeven** |
| `experiment_multitf.py` | 24h-anchored, damped, shorten-only multi-timeframe line | raises win% to ~46% but **EV flat** (win-for-ROI trade); pairs with a loss-stop |
| `experiment_combined.py` | two-screen (exit-line AND gap-response) decision | both-screens > parts, but ~breakeven |
| `experiment_nested.py` | NESTED: gap zone → filter → time line (the real strat), vs baseline | looked great at **6h cadence** (nested −0.06 vs baseline −0.25)… |
| `experiment_nested_tod.py` | nested at **30-min cadence**, broken by time-of-day | …but **cadence-fragile**: at 30-min nested −0.09 ≈ baseline −0.06. Refresh > nesting. **No clean time-of-day edge** (night≈day≈−0.1) |
| `experiment_spike_reversion.py` | do big instant BTC moves mean-revert? (move/revert window sweep) | **No.** ~half keep going, median retrace ≈ 0 at 10–120s scales. The vivid reverting charts were selection bias |
| `experiment_lookback_sweep.py` | sweet-spot 3-lookback combo from {24,16,8,6,4}h + robustness gate, baseline vs nested, entry from 5c | baseline: no sweet spot (all ~−0.1). nested + **24h anchor**: consistent **+0.01..+0.02** (6 combos agree) — most coherent positive yet; the 3-lookback **robustness gate** drove it. Marginal, gross of fees, unconfirmed |

---

## Strategies/approaches tried, in order

1. **Time-based exit line** — best buy-window + sell target by Wilson-EV. Caps at
   breakeven under realistic fills (adverse selection).
2. **Signal refresh / decay** — refreshing helps vs stale, but signals decay in ~1h
   (overfit-to-recent signature).
3. **Config / lookback / refresh-cadence / config-adaptation** — all second-order;
   adapting the config per regime is *worse* than a fixed config.
4. **Per-window gating** (volume / BTC move / hour) — separates winners from losers,
   caps at breakeven; can't manufacture profit, only "lose less."
5. **Multi-timeframe anchored line** — high win-rate, flat EV (the −100%-loss trade).
6. **Combined two screens** (exit-line AND gap-response) — better than parts, ~breakeven.
7. **Nested gap→time** (condition on the gap zone, *then* fit the time line) — the
   most promising architecture; gap is the strong variable, time the weak one. But the
   apparent edge was **cadence-fragile**.
8. **Lookback robustness gate** (line must hold across 3 timeframes incl. 24h) — the
   one filter that nudged nested marginally positive (~+0.02), more selectively.
9. **BTC spike-reversion** (side idea) — no systematic reversion; dead.

---

## Discipline lessons (do not forget)

- **Sweeps overfit.** Trying N configs manufactures a best by selection; high in-sample
  is *negatively* correlated with out-of-sample. Read the **full ranking** and look for
  a *consistent* cluster, not the argmax.
- **Per-block / per-slice "best" is hindsight.** Trust the **fixed-config, pooled OOS**
  number, not cherry-picked cells.
- **~3 days is wildly underpowered** (a rigorous multi-*year* microstructure study was
  still insignificant at 12% power). Confirm any lead over **weeks**, with non-
  overlapping walk-forward + deflated thresholds + **net of fees**.
- **Results flip sign with knobs** (cadence, entry range, gate) → that ±0.05 swing *is*
  the noise band on this much data.

---

## Where it stands / next steps

- **Best lead:** nested gap→time + 24h robustness gate ≈ **+0.02 EV/$1 OOS** (marginal,
  gross of fees). Open checks: (1) is it from the cheap-entry (5–19c) longshots? — run
  an **entry-price-band** breakdown; (2) does it survive **fees**? (3) does it hold over
  **weeks**?
- **Deferred levers:** the **loss-stop** (needs full price path; pairs with the high-win
  multi-TF line) and a **fair-value taker** built on the faster feed.
- **Prerequisite for any verdict:** add `book_events` **retention/compaction** and let
  the collectors run for **weeks** so the filtered/nested views have the 30–100+ dots
  they need. On 3 days they collapse to overfit (e.g. n=10 / 100%-win cherry-picks).
- **Live infra:** `live_runner.py` exists (proxy-wallet path, read-only connectivity
  verified) but is **gated and must NOT be armed** until an edge clears validation.

See agent memory (`deep-research-verdict`, `nested-edge-is-cadence-fragile`,
`per-window-gating-caps-at-breakeven`, `edge-is-regime-dependent`) for the detailed
verdicts behind each line above.

# EXPERIMENTS.md — strategy research log

What we tried to find a profitable limit-order strategy on Polymarket "BTC Up/Down
5-minute" markets, what each experiment does, and what it found. Honest record — most
results are **negative or near-breakeven**, and that is the point: each idea was
killed (or kept) cheaply by measurement instead of expensively by trading.

> **One-line state:** the **passive resting-limit** family is a confirmed dead end
> (adverse selection; the last +0.02 nested lead was a guard artifact → breakeven with the
> live-matching guard). The **fair-value TAKER** is now tested and is the live direction:
> `experiment_lookahead_taker.py` shows **BTC LEADS the Polymarket quote by ~1s** (lead-lag
> cross-corr peaks at L=+1s, r=0.36, sharp) and a faster feed lifts taker EV **monotonically**
> with look-ahead Δ — your-feed-speed *is* a real lever. The remaining wall is **execution**:
> crossing the spread to exit costs more than 1–3s of lead recovers, so pooled catch-up EV is
> ~−0.01..−0.02; only the clean cut (1-per-window, big dislocations, tight exit) reaches
> **+0.009/$1 at the clairvoyant upper bound**. Next levers: a genuinely faster BTC feed +
> **maker-exit** (earn the spread, don't cross it), then weeks of data.

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

Live now (after a cleanup that removed 7 dead-end orphans — `refresh`, `config_sweep`,
`window_features`, `multitf`, `nested`, `nested_tod`, `spike_reversion`; their findings
are folded into "Strategies tried" below):

| Script | Approach | Key finding |
|---|---|---|
| `experiment_walkforward.py` | **(shared lib)** walk-forward OOS backtest; `open_merged()` / `replay_leg()` / `generate_signals()` reused by the others | realistic fills ≈ −0.4 EV/fill; exit-map win% doesn't survive |
| `experiment_combined.py` | **(shared lib)** two-screen (exit-line AND gap-response); exports `load_full` / `train_dots` | both-screens > parts, but ~breakeven |
| `experiment_config_tod.py` | config brute-force × time-of-day, 30-min cadence, **live-matching guard** | DECISIVE: nested +0.02 was a **guard artifact**; corrected guard → EV/fill ≈ **0.00** (breakeven), no edge |
| `experiment_lookback_sweep.py` | sweet-spot 3-lookback combo + robustness gate, baseline vs nested, **live-matching guard** | passive nested ≈ breakeven once the guard matches the executor |
| `experiment_lookahead_taker.py` | **FASTER-FEED test** (the live one). (A) lead-lag cross-corr BTC vs Polymarket Up-mid; (B) clairvoyant-Δ taker, catch-up vs hold exit, Δ∈{0,.5,1,2,3}s, costed (cross the spread) | **BTC LEADS Polymarket by ~1s (r=0.36, sharp).** Taker EV rises **monotonically** with Δ — feed speed *is* a real lever. But the **spread you cross is the wall**: pooled catch-up ≈ −0.01..−0.02; only the clean cut (1-per-window, big dislocations edge≥0.08, exit 1s) flips to **+0.009/$1** at full clairvoyance. Edge structure EXISTS; binding constraint is now execution/spread, not signal |

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
   one filter that nudged nested marginally positive (~+0.02); later shown to be the
   guard artifact → breakeven with the live-matching guard.
9. **BTC spike-reversion** (side idea) — no systematic reversion; dead.
10. **Fair-value TAKER / faster feed** (the pivot away from passive) — *the first
    structurally-sound positive signal.* Lead-lag cross-corr proves **BTC leads the
    Polymarket quote by ~1s** (r=0.36); a faster feed lifts taker EV **monotonically**
    with look-ahead. But exiting by crossing the spread eats it (pooled ~−0.01..−0.02);
    only the clean cut reaches +0.009/$1 at the clairvoyant upper bound. The constraint
    moved from *signal* (passive: none) to *execution* (taker: spread). Levers left: a
    real faster feed + **maker exit** (rest at new fair, earn the spread).

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

- **Live direction = the fair-value TAKER.** `experiment_lookahead_taker.py` confirmed
  the BTC→Polymarket lag (~1s, r=0.36) and that feed speed lifts taker EV monotonically.
  The binding constraint is now the **exit spread**, not signal. Open work, in order:
  (1) **maker-exit** model — instead of selling at the bid (crossing), rest a limit at the
  freshly-repriced fair and *earn* the half-spread (with a realistic fill prob); this is
  the single change most likely to push pooled EV positive. (2) Source a **genuinely
  faster BTC feed** (Binance WS is already logged sub-second; the clairvoyant Δ was an
  upper bound — measure the *real* achievable lead vs the quote). (3) Selectivity: trade
  only large, fresh dislocations (edge≥0.08, first-per-window) where the move clears the
  spread. (4) **Net of fees** + over **weeks**.
- **Passive branch: closed.** No edge survives realistic fills (adverse selection).
- **Deferred:** the **loss-stop** (needs full price path; pairs with the high-win multi-TF
  line) — only relevant if a passive variant is ever revived.
- **Prerequisite for any verdict:** add `book_events` **retention/compaction** and let
  the collectors run for **weeks** so the filtered/nested views have the 30–100+ dots
  they need. On 3 days they collapse to overfit (e.g. n=10 / 100%-win cherry-picks).
- **Live infra:** `live_runner.py` exists (proxy-wallet path, read-only connectivity
  verified) but is **gated and must NOT be armed** until an edge clears validation.

See agent memory (`deep-research-verdict`, `nested-edge-is-cadence-fragile`,
`per-window-gating-caps-at-breakeven`, `edge-is-regime-dependent`) for the detailed
verdicts behind each line above.

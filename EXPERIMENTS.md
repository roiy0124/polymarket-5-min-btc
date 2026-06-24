# EXPERIMENTS.md — strategy research log

What we tried to find a profitable limit-order strategy on Polymarket "BTC Up/Down
5-minute" markets, what each experiment does, and what it found. Honest record — most
results are **negative or near-breakeven**, and that is the point: each idea was
killed (or kept) cheaply by measurement instead of expensively by trading.

> **One-line state:** the **passive resting-limit** family is a confirmed dead end
> (adverse selection; the last +0.02 nested lead was a guard artifact → breakeven). The
> **fair-value TAKER** is the live direction and is now measured WITH window-clustered
> bootstrap CIs (`experiment_lookahead_taker.py`). Findings: **BTC LEADS the Polymarket
> quote by ~1s** (lead-lag peak L=+1s, r=0.36, sharp), and a faster feed is **provably worth
> money** — the EV lift over the no-advantage control is significant at every lead (~**+0.006
> EV/$1 per second**, saturating by ~2s). BUT the **bid-ask spread is the dominant cost**: the
> taker→maker exit gap (~+0.008..+0.011) is *bigger than the feed lift*, and at the clairvoyant
> UPPER BOUND feed-speed + maker-exit only reach **~breakeven** (`+0.000 [−0.001,+0.002]`). No
> clean **time-of-day** gate (every hour's CI straddles/below 0) and high-vol is NOT best
> (it widens the spread); mid-vol is least-bad. So the structure is right but the lag is too
> small to clear the spread on this data. Ranked levers: **maker-exit > faster feed > (no)
> regime gate**; then weeks of data.

---

## 2026-06-23 — FULL IDEA AUDIT + PER-COIN REPLICATION (read this first)

Re-ran/audited EVERY idea on current data (~22h alts, ~98h BTC); each verdict adversarially
verified by an independent skeptic. Per-idea "potential / what's left to discover" detail is in
agent memory `idea-audit-full-2026-06-23` + `passive-multicoin-dead`. Key meta-finding: the
recorded numbers were generally **too OPTIMISTIC** (the taker charged no fee, the passive fill
model fills you 100% in losers, "breakeven" cases are pre-fee) — so the kills are SAFER than
the docs claimed. 9 of 10 verdicts robustly dead/breakeven; **only B has an unrun decisive test.**

### BEST STRATEGY WE HAVE, AND HOW IT PERFORMS
**We do NOT have a profitable strategy. Everything tested is net-negative or statistically
breakeven after fees.** Ranked by how close to viable:

1. **Favorite-tail taker, hold to resolution** (least-bad; best fit to the consistency goal) —
   buy a deep favorite (ask ~0.90–0.97) late in the window; rest a maker sell at target, else
   HOLD to 0/1 (never taker-exit). Pooled 6 coins, time-clustered: ask≥0.94 = **+0.003 EV/$1,
   CI [−0.005,+0.010]**; hold-to-res ask≥0.90 = **+0.013, CI [−0.008,+0.031]**; ask≥0.95 = +0.006
   [−0.016,+0.024]. Win-rate ~90–97% (realized ≈ ask), coverage ~every window, fee only 0.2–0.7%.
   **= statistical BREAKEVEN, not a proven edge**, and the −100% flip tail is real (1 loss ≈
   30–160 wins; losses occur even at 0.99+). (net_ev() to score it is still UNBUILT.)
   **Selectivity tested + REJECTED (2026-06-23):** fixed score-margin (signal-finder), a D
   risk-filter (its 100%-win is a zero-variance bootstrap artifact — Wilson-LB < ask breakeven),
   a fair-value score gate (borderline HIGH>LOW, CIs include 0), and an ADAPTIVE consistency-
   weighted walk-forward cutoff all FAIL to beat baseline OOS (adaptive +0.0038 ≈ baseline
   +0.0046, CI incl 0). The in-sample ORACLE cutoff (+0.0133*) is overfit/look-ahead — NOT
   tradeable; ORACLE−ADAPTIVE ≈ +0.0095 = pure overfit. You can't out-select a calibrated market;
   a winner needs a FORWARD underpricing gate (idea B). Scripts: experiment_favorite_tail.py,
   experiment_favtail_selectivity.py, experiment_favtail_adaptive.py.
   STRESS-TEST (4 independent methods + reproduction, 2026-06-23, workflow wf_4345f501): confirmed
   dead at the rigorous bar. Best forced candidate (top-50% fair-P−ask) = +0.0144 vs +0.0049, 6/6
   EV-positive, but Wilson-LB(win) < ask+fee breakeven on EVERY coin + every leave-one-out fold,
   per-coin stars are loss=0 artifacts, and the placebo clears only via BTC (alt-only placebo P=0.143
   vs pooled 0.023). Only real signal = latency-residual (6/6 sign-consistent) but spread/fee-capped
   at the favorite band. NEXT = idea B reframed as a FORWARD cross-asset (BTC→alt) underpricing gate
   (route the latency signal cross-asset, where it isn't priced), validated with alt-only-placebo +
   Wilson-LB-vs-breakeven + per-coin replication.
2. **Fair-value taker** (~1s BTC→quote lead) — structurally soundest, but **−0.002…−0.004 EV/$1**
   after the real 0.07·p·(1−p) entry fee. Negative.
3. **Passive resting-limit / exit-map / nested** — **−0.31 EV/fill pooled** across 6 coins. Dead.

### Per-idea verdicts
| idea | status | fresh result | kill |
|---|---|---|---|
| A favorites-tail | dead standalone | late favorites well-calibrated; pooled tail +0.003 CI[−0.005,+0.010] | robust |
| A exit policy | KEEP (sound) | maker-rest-at-target ELSE hold-to-res, never taker-exit | n/a |
| B cross-asset SMT | **LIVE (Part 3 unrun)** | underlying conv +0.031 CI[+0.004,+0.056] but single-coin (DOGE); gap-vs-QUOTE never tested | premature |
| D settlement basis | dead | 4.1% Binance↔Chainlink flips; quote prices it; residual trade loses net −0.06 | robust |
| E maker-rebate | dead standalone | rebate ∝ p(1−p) → ~0 at tails; keep only as +term in net_ev | robust |
| F multi-coin | adopt (overstated) | ~1.5 eff. coins for market-wide edges; ~6× only for idiosyncratic (B) | n/a |
| G OFI/queue-imbalance | dead-as-proxy | snapshot QI contemporaneous; 6-coin pooled +0.010 CI incl 0; SOL/XRP neg net | robust |
| H digital fair value | dead (closed) | market Brier beats fair on every coin; pooled corr(signal,resid) −0.018 | robust |
| KNOW / trend (wall) | dead | residual ≈0 at all 15 lookback×horizon cells; Brier 0.11–0.13 | robust |
| faster-feed taker | net-negative | −0.002…−0.004 EV/$1 after real fee (clairvoyant upper bound) | robust |
| passive / nested | dead, all coins | pooled −0.31 EV/fill; every coin's best config FAILS OOS holdout | robust |

### Per-coin passive simulation (walk-forward, 12h, 30-min refresh, OOS, real-trade fills)
EV/$1-on-fill (window-clustered CI): btc −0.46[−0.87,+0.05] (n=24), eth −0.34*[−0.64,−0.01],
sol −0.54*[−0.74,−0.32], xrp −0.88 (n=3), doge −0.04[−0.58,+0.59], bnb −0.13[−0.44,+0.18].
**POOLED −0.31, CI [−0.46,−0.14]** (significant<0). Win% on fills 17–38% (vs ~80% mid-path) =
adverse-selection collapse, replicated across coins.

### Per-coin config brute-force (20 configs = base/nest × 3-lookback combos) + train/test holdout
Every coin's in-sample-best combo FAILS out-of-sample: btc nest:4/16/24 −0.03→−0.11; eth −0.12→−0.11;
sol +0.00→−0.08; xrp −0.07→−0.27; doge +0.11→−0.15; bnb −0.15→+0.01 ("holds" at +0.01 = noise).
6/6 fail. BTC best-powered (n=1450) is the clincher (all 20 configs negative, no stable per-bucket
config). Per-timeframe "best combos" (e.g. doge 15–18h +0.72) are hindsight argmax that evaporate OOS.
(`experiment_walkforward.py` + `experiment_config_tod.py` are now `--coin`-aware; config_tod gained a
train/test holdout + per-coin best-times. The A/D/G tests were ad-hoc — TODO: promote to repo scripts.)

### NEXT STEP (the one live thread)
**B Part 3** — `corr(gap, outcome − up_mid)` per coin, window-clustered, DOGE→XRP: is the divergence
gap UNPRICED by the quote? If non-zero → **encode `net_ev()`** (taker-entry fee 0.07·a·(1−a); maker-or-hold
exit = 0; −100% term; +rebate) and run **B2** net of DOGE's real spread. Only D reopener = a FREE
Chainlink replica from exchange feeds; only G reopener = true event-level OFI from `book_events` deltas.

### B as a COMPONENT on the favorite-tail (2026-06-23, run + stress-tested wf_c3533092) — first real direction
Routed idea B as a risk-filter: SKIP an alt favorite-tail entry when BTC's last ~15s move OPPOSES the
favorite (`experiment_b_component.py`). The convergence/gap framing is DEAD (doge noise). The btc-opposing
risk-filter is the FIRST genuinely directional, cross-coin-consistent, placebo-significant component:
tl=30/ask≥0.95, drop bottom-20% BTC-opposing → net EV +0.0151 vs +0.0037 baseline, all 5 alts + every LOCO
positive, BTC-signal permutation p=0.002, subset placebo p=0.004. BUT NOT deployable: its Wilson-LB>be pass
hangs on the gated subset having ~1 loss (one more loss → breakeven), per-coin replication is mostly
degenerate 0-loss subsets, and it's ~25h ≈ one independent stretch. PRE-REGISTERED for an OOS re-test on
≥2–4 weeks more data (≥30–50 alt losers); `live_runner` GATED. So: a real lead, not yet a real edge —
the combination program is exhausted at *deployable* altitude, with this one live hypothesis to validate forward.

**Tooling + repo layout (2026-06-23):** live strategy + tests in root — `experiment_favorite_tail.py`,
`experiment_b_component.py`, `net_ev.py` (fee-aware accounting), `validate_b_riskfilter.py` (LOCKED
push-button re-test; `--all` = in-sample dry-run). All **proven-dead experiments archived in `dead_ends/`**
(walkforward/combined/config_tod/lookback_sweep/trend_outcome/lookahead_taker/xasset_smt/
favtail_selectivity/favtail_adaptive) — see `dead_ends/README.md`.

### Reversion / fear-dip + idiosyncratic-spike (2026-06-24, ACTIVE — see memory reversion-fear-dip-idea, idiosyncratic-spike-idea)
Contrarian short-term reversal (SMT-gated): buy a laggard alt's Up token when underpriced, hold to 0/1.
`experiment_fear_dip.py` (dip-bottom: DEAD, resid −0.04, the discount is justified), `experiment_fear_dip_variants.py`
(PEER-SURGE / AFTER-RECOVERY: residual flips POSITIVE +0.01..+0.03, peer-surge ~breakeven+ EV — BORDERLINE:
placebo p=0.09-0.14, per-coin mixed eth/sol+ xrp−, Wilson<be; not over the bar), `experiment_hybrid.py`
(favorite-tail + fear-dip; the +0.89 "recovered" subset is SURVIVORSHIP). `experiment_idio_spikes.py`
(lone idiosyncratic small-cap spot spikes: asymmetry confirmed btc 0/eth 1 vs sol 16/doge 7; immediate-revert
rare at 1/s). Reversion = real pulse not deployable; spike = the noise-filter for it, parked. NAIVE adaptive
params (30-min refit best combo) = the documented overfit trap (favtail-adaptive + config_tod died OOS).

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
| `experiment_trend_outcome.py` | **TREND→OUTCOME vs PRICE** (knowledge-edge test), one obs/window, bootstrap CIs. corr(recent BTC trend, outcome) vs corr(trend, residual=outcome−market_price) | **Trend strongly predicts the OUTCOME** (corr +0.15..+0.40, significant, grows with lookback) — but **the market PRICE already prices it**: corr(trend, RESIDUAL) ≈ **0** at every lookback & horizon (CI includes 0, no `*`). The token price is highly efficient (Brier ~0.12 @60s). True-but-useless: no knowledge edge from trend. Matches the position finding (`fair_vs_market`: corr −0.03) |
| `experiment_lookahead_taker.py` | **FASTER-FEED test** (the live one), window-clustered bootstrap CIs. (A) lead-lag cross-corr; (B) **Q1 value of real-time**: clairvoyant-Δ taker, bid(taker) vs mid(maker) exit, Δ∈{0,.5,1,2,3}s, lift-vs-Δ0 CI; (C) **Q2 when**: EV by 3h-UTC hour + by BTC-vol tercile | **BTC LEADS by ~1s (r=0.36).** Q1: feed lift **significant at every lead** (~+0.006/$1 per sec, saturates ~2s) — faster feed provably worth money. BUT **spread dominates**: taker exit −0.011..−0.020, maker(mid) −0.001..−0.009; the taker→maker gap (>feed lift) means **maker-exit is the bigger lever**. At the **clairvoyant upper bound**, feed+maker ≈ **breakeven** (`+0.000[−0.001,+0.002]`). Q2: **no clean hour** (all CIs straddle/below 0); **high-vol NOT best** (widens spread), mid-vol least-bad. Structure right, lag too small to clear the spread on this data |

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
10b. **Trend → outcome (knowledge edge)** — recent BTC trend strongly predicts the 5-min
    outcome (corr up to +0.40) **but the token price already prices it** (corr with the
    residual ≈ 0, not significant). Same verdict as static fair-value: **the market is
    efficient on knowledge** (price Brier ~0.12). Predicting the outcome ≠ beating the price.
10. **Fair-value TAKER / faster feed** (the pivot away from passive) — *the first
    structurally-sound signal,* now measured with window-clustered CIs. Lead-lag proves
    **BTC leads the quote by ~1s** (r=0.36). **Q1:** a faster feed is **provably worth
    money** — the lift over the no-advantage control is significant at every lead (~+0.006
    EV/$1 per second, saturating ~2s). **But the spread dominates:** exiting as a taker is
    −0.011..−0.020, as a maker −0.001..−0.009, and the taker→maker gap is *bigger than the
    feed lift* → **maker-exit is the #1 lever, faster feed #2.** At the clairvoyant UPPER
    BOUND the two together only reach ~**breakeven**. **Q2:** **no clean time-of-day** edge
    (every hour's CI straddles/below 0) and **high-vol is not best** (it widens the spread);
    mid-vol is least-bad. Verdict: structure correct, lag too small to clear the spread on
    this data; needs maker-exit + a real (sub-clairvoyant) fast feed + weeks of data.

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

- **VERDICT (2026-06-22): no retail edge on this 5-min market as it stands.** Knowledge is
  priced (market efficient: position + trend, Brier ~0.12). The one inefficiency (~1s latency)
  is spread-capped AND — **confirmed live** — the 5-min market carries the dynamic **taker fee**
  (`feeSchedule` rate 0.07, takerOnly, p(1-p): ~3.5%+/stake), which sinks the retail taker. The
  fee-exempt **maker** side is the adverse-selected passive branch; the 20% maker rebate is far
  too small to offset it. All three avenues (know / take / make) are walled.
- **Live direction = the fair-value TAKER.** `experiment_lookahead_taker.py` (with
  window-clustered bootstrap CIs) answered the two open questions: **Q1** a faster feed is
  *significantly* worth money (~+0.006 EV/$1 per second of lead, saturating ~2s), but the
  **bid-ask spread dominates** and even the clairvoyant upper bound only reaches breakeven;
  **Q2** there is **no clean time-of-day or vol gate** (high-vol widens the spread). The
  binding constraint is the **exit spread**, not signal and not timing. Open work, in order:
  (1) **maker-exit fill model** — the headline mid-exit assumes we capture half the spread;
  model a realistic *fill probability* for resting a limit at the repriced fair (truth is
  between the bid and mid columns). This is the #1 lever. (2) Measure the **real achievable
  feed lead** vs the quote (Binance WS is logged sub-second; the clairvoyant Δ is a ceiling —
  how much of it can a real loop capture?). (3) **Net of fees/gas** + over **weeks**. (4) If
  still sub-breakeven after (1)-(2), the honest call is that retail can't clear the spread here.
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

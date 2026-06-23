# STRATEGY — Favorite-Tail Taker, Hold-to-Resolution

**Our chosen / best candidate strategy.** The closest-to-viable, best-aligned-with-the-goal
(steady high-coverage wins) strategy the project has found.

> **STATUS (2026-06-23):**
> - ✅ **Real-time implementable, NO look-ahead** — verified causal (see "Causality"). This was the gate for adopting it.
> - ⚠️ **Performance = statistical BREAKEVEN, not yet a proven winner.** Pooled net EV +0.001…+0.005 per $1, 95% CI **includes 0** in every variant. Best we have, *not money yet*.
> - **Selectivity refinements were tested and REJECTED** — fixed margin, a D risk-filter, a fair-value score gate, and an adaptive (consistency-weighted, walk-forward) threshold all fail to beat the baseline out-of-sample (see "Selectivity tests"). **Do NOT adopt the in-sample ORACLE cutoff — it is overfit/look-ahead, untradeable.**
> - It becomes a *winner* only by stacking a **forward underpricing** signal (idea B), not a smarter threshold.

Test suite (all causal, read-only): `experiment_favorite_tail.py` (base + `--min-gap-bps` D filter),
`experiment_favtail_selectivity.py` (score-tercile/margin cuts), `experiment_favtail_adaptive.py`
(walk-forward adaptive cutoff). Reproduce base: `python experiment_favorite_tail.py --coin all --min-ask 0.95 --tl 30`.

---

## The rule (exactly what a live bot does)
At a fixed decision time late in each 5-min window (e.g. **time_left ≈ 30s**):
1. **Identify the favorite** from the CURRENT Binance price vs the window's strike:
   favorite = `Up` if `price_binance ≥ strike_binance` else `Down`.
2. **Read the favorite side's live ASK.** If `ask ≥ MIN_ASK` (e.g. 0.95) and `ask < 1.0`, **BUY** (taker).
3. **Exit (decided policy):** rest a maker sell at target; if unfilled, **HOLD to the 0/1 resolution.
   NEVER taker-cross to exit.** ⇒ the taker fee bites only the ENTRY (`0.07·ask·(1−ask)`, ~0.2% at ask≈0.97).

One position per window. High coverage, high win-rate.

## Causality (why it passes the live gate)
Every decision input is observable AT the decision instant: strike (window start), current price
(Binance WS), favorite (`price ≥ strike`), ask (book), time_left (clock). The realized outcome is
used **only to score** the bet at resolution. The backtest reads one snapshot per window and nothing
after it. No future info enters the decision. ✅

## Performance (CAUSAL backtest, ~22h alts / ~98h BTC, net of the taker entry fee)
`min-ask 0.95, time_left≈30s`, one obs/window, window-clustered bootstrap CI:

| coin | n | win% | mean ask | EV/$1 | 95% CI |
|---|---:|---:|---:|---:|---|
| btc | 348 | 99.1% | 0.981 | +0.0092 | [−0.0025, +0.0178] |
| eth | 75 | 98.7% | 0.982 | +0.0031 | [−0.0262, +0.0194] |
| sol | 97 | 99.0% | 0.981 | +0.0071 | [−0.0155, +0.0199] |
| xrp | 97 | 100% | 0.982 | +0.0175 | [+0.0144, +0.0205] (loss=0 artifact) |
| doge | 89 | 98.9% | 0.982 | +0.0053 | [−0.0190, +0.0189] |
| bnb | 127 | 96.9% | 0.981 | −0.0139 | [−0.0473, +0.0120] |
| **POOLED** | 833 | 98.8% | — | **+0.0054** | **[−0.0051, +0.0136]** |

Pooled EV is **breakeven** (CI includes 0); bnb is negative; the per-coin "significant" cells are
**loss=0 zero-variance bootstrap artifacts** — not real. No cross-coin replication ⇒ not a proven edge.

## Risks / why it isn't money yet
1. **Breakeven** — realized win-rate ≈ ask (calibrated market), so buying at ask earns ~0 gross.
2. **−100% flip tail** — one loss ≈ 30–160 wins; losses occur even at ask 0.99+. No clean loss-stop (binary).
3. **Settlement basis** — favorite picked on Binance, resolves on Chainlink; ~4% of windows the basis flips the winner.
4. **Thin depth** at 0.95–0.97 (BTC median ~280 sh, SOL ~50) — filling size walks the book.
5. **No cross-coin replication** of significance ⇒ likely noise on ~22h.

## Selectivity tests (2026-06-23) — all REJECTED, base unchanged
We tried to turn breakeven into a winner by GATING entries (the "truth table" combination idea).
None beat baseline out-of-sample:
- **Fixed score-margin (signal-finder):** sign-inconsistent across coins; tighter margins starve to 0 trades.
- **D risk-filter** (skip near-boundary, basis-flip-prone favorites): at ≥10bps it showed 100%-win on
  all 6 coins — but that's the **zero-variance bootstrap artifact**; the honest Wilson-LB win-rate sits
  *below* the ~0.99 ask's breakeven (binomial P of all-wins-under-breakeven up to 0.79). It removed
  losses by selecting more-certain favorites, which the market already prices to ~1 → removed the room
  with the risk → net zero.
- **Fair-value score gate (A×H), HIGH vs LOW tercile:** the only one with a pulse — pooled HIGH +0.010
  vs LOW −0.009, 5/6 coins — but borderline (CIs include 0), bnb reverses, stars are loss=0 artifacts.
- **Adaptive threshold** ("calculate it, don't fix it, optimize for consistency"): the *correct* way to
  test selectivity — causal walk-forward, cutoff chosen each 30 min from past data by Wilson-LB, applied
  OOS. Result: **+0.0038 ≈ baseline +0.0046 (CI includes 0). No improvement.**

> **⚠️ THE OVERFIT TRAP — DO NOT ADOPT.** The in-sample ORACLE cutoff scores +0.0133 [+0.004,+0.022]*,
> but it is chosen with **full hindsight over the whole period** → **not real-time implementable**
> (look-ahead). ORACLE(+0.0133) − ADAPTIVE(+0.0038) ≈ **+0.0095 of pure overfit** — fake edge that
> vanishes once you can't see the future. The `*` is also propped up by loss=0 zero-variance buckets.
> Never use the oracle as the strategy. (This is "set your parameters after seeing the chart.")

**Conclusion:** you cannot out-SELECT a calibrated market — gating on certainty / in-sample score / a
backward fit is already priced. A winner needs a **forward underpricing** signal (idea B), not a threshold.

**Stress-test (4 independent methods + reproduction, 2026-06-23) — CONFIRMED dead at the rigorous bar.**
The best candidate the adversary could force (top-50% by fair-P−ask) shows higher EV (+0.0144 vs +0.0049,
6/6 coins EV-positive, LOO EV-stable) — but it **fails** the loss=0-proof bar: Wilson-LB(win-rate) is
**below the ask+fee breakeven on every coin and every leave-one-out fold**, the per-coin "stars" are
loss=0 degenerate-CI artifacts, and the placebo-vs-random clears only by leaning on BTC (**alt-only
placebo P=0.143**, vs pooled 0.023). So the lift is a faint, BTC-driven, fee/spread-capped re-discovery
of the already-priced HIGH-score tercile — not a tradeable edge. The one genuinely real signal is
**latency-residual** (BTC leads the quote ~1s, sign-consistent 6/6) but it is spread/fee-capped exactly
at the favorite band (indistinguishable from random subset-leverage at ask≥0.90; only beats random at
the 0.85 band, which is itself breakeven).

## Idea B as a component — TESTED (2026-06-23): a real DIRECTION, not yet a deployable edge
We routed idea B as a **risk-filter component** on the favorite-tail (NOT standalone, NOT the
convergence/gap framing — that's dead, doge-driven noise): **SKIP an alt favorite-tail entry when BTC's
last ~15s move OPPOSES the favorite** (`btc_sig = sign_fav · BTC_return_15s`; drop the most-opposing ~20%).
Script: `experiment_b_component.py`; verified independently + by a 4-angle stress-test (`wf_c3533092`).

**It is the first component whose DIRECTION is genuinely real.** At tl=30 / ask≥0.95, dropping the
bottom-20% BTC-opposing windows lifts net EV to **+0.0151 vs +0.0037 baseline** (delta +0.011),
consistent across all 5 alts and every leave-one-coin-out fold, with a **BTC-signal permutation placebo
p=0.002** and a subset placebo p=0.004 (rules out subset-leverage and selection luck). Mechanism: it cuts
the rare boundary-flip losers that the alt quote hasn't yet repriced from BTC's lead.

**But it is NOT yet a deployable edge — DO NOT ARM.** Its only "Wilson-LB(win) > ask+fee breakeven" pass
hangs on the gated subset having ~1 loss: **one additional losing window takes Wilson-LB back to breakeven**
(drop-20%: 1 loss → +0.0038; +1 loss → 0.0000; +2 → −0.0035). The per-coin "replication" is mostly
degenerate 0-loss subsets; the whole edge is cutting ~6 of 7 flip-losers over only **~25h ≈ one
independent stretch** of cross-correlated coins. By our own loss=0 rule it does not clear the deployable bar.

**PRE-REGISTERED hypothesis — lock now, re-test on FRESH data** (see memory `b-riskfilter-preregistered`):
*tl=30, ask≥0.95, L=15s, skip `btc_sig` in the bottom ~20% (BTC opposes the favorite).* Re-evaluate ONLY
after ≥2–4 more weeks of alt data accumulate **≥30–50 alt favorite-tail losers** (so the win-rate Wilson-LB
is non-degenerate). This finding was in-sample-discovered (multiple-comparisons exposure); a clean
pre-registered OOS re-test on fresh data is the ONLY thing that upgrades it from "intriguing direction" to
"edge." Build `net_ev()` before any live use; `live_runner` stays GATED until it clears on fresh data.

**Dead ends confirmed (do not revisit):** the gap/convergence framing (doge noise); BTC-confirming *entry*
gate (hurts EV); B as a standalone trade; favorite-tail selectivity (all variants).

## Live wiring (GATED — do not arm until an edge clears validation)
- `live_runner.py` exists but must NOT be armed until B2 shows a replicated, net-positive edge.
- Decision loop: at `time_left ≈ TL`, favorite from live Binance vs strike, ask ≥ MIN_ASK, size by depth,
  taker buy, rest maker sell at target else hold to settlement.
- Pre-register MIN_ASK + TL in advance (no per-coin/per-hour argmax — the documented overfit trap).

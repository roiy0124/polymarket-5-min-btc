# winning_strategies/

> **⚠️ STATUS 2026-06-25 — Tier 1 is EMPTY; no deployable edge exists. See `../POSTMORTEM.md`.**
> A deflated, cluster-robust re-test (`analysis/stats.py`) + a re-experiment of every still-open idea
> (`analysis/gate_open_ideas.py`, second-mind reviewed) overturned the roster:
> **favorite-tail is NET-NEGATIVE** (pooled −0.0029, deflated p=1.0); the **B risk-filter** is
> **FALSIFIED** (the alt's own momentum gates better than BTC ⇒ no cross-asset content — `validate_b_riskfilter.py`
> CHECK 5); **spike-fade** is **DEAD** (no dose-response + falling-knife fail); the **lead-lag** is a real
> predictor the quote already prices. The borderline "pulses" were best-of-N noise that regressed on more data.
> **Two genuinely close-to-edge threads remain, both forward signals whose kill is cost+power, not a falsified
> mechanism:** (1) **`overround-gate.md`** (NEW 2026-06-25) — gate favorite-tail on tight over-round (makers'
> revealed fear); the gate signal is real AND ask-independent (joint logistic p=0.0006 — it passes the
> joint-control test that *falsified* the B risk-filter), lifts fav-tail −0.006→+0.0065, but is loss-light
> (13<30) + fee-capped → INSUFFICIENT. (2) **`token-fear-follow.md`** — significant at the mid (resid +0.052,
> cluster-p=0.008, all 6 coins), flips via a fee-free maker-Down entry. Both are *candidates*, NOT live winners.
> Gate any future idea through `analysis/stats.assess`.

The curated roster of strategies that have earned a place — with an **honest tier**
on each, because on this market the difference between "predicts" and "pays" is the
whole game (the market is calibrated; a signal that's real can still be fully priced).

This folder is the **trophy cabinet + candidate board**. A strategy gets a card here
the moment it clears the causality gate; its TIER says how far it has actually gotten.
Nothing is armed for live trading until it reaches Tier 1.

## The bar (what each tier means)

- **Tier 1 — DEPLOYABLE WINNER.** Causal & live-implementable, AND net-positive after the
  confirmed ~3.5% taker fee + spread on **fresh, out-of-sample, pre-registered** data, with
  cross-coin replication and a non-degenerate loss base (not a loss=0 zero-variance artifact).
  → **EMPTY today.** Nothing has cleared this yet. That's the goal.

- **Tier 2 — PROVEN BASELINE (causal, breakeven).** Verified no look-ahead, real-time
  implementable, high-coverage — but EV is statistical breakeven (CI includes 0). The
  *foundation* you stack a forward edge onto; not money by itself.
  → **`favorite-tail.md`**

- **Tier 3 — PRE-REGISTERED CANDIDATE (real signal, OOS proof pending).** A genuinely
  directional signal found and **params LOCKED**, awaiting confirmation on fresh data. Must
  NOT be re-mined on current data (that's the overfit trap that already died twice here).
  → **Over-round-gated favorite-tail** (`overround-gate.md`, NEW 2026-06-25) — gate favorite-tail (ask 0.95–0.99)
     on TIGHT over-round (`up_ask+down_ask−1 ≤ 0.012` = makers calm). The makers widen the pair defensively when a
     near-certain favorite is about to flip, so the over-round is their revealed fear. **First gate to pass the
     joint-control test** (over_round significant-negative p=0.0006 with fav_ask in the model — B failed exactly
     this). Lifts fav-tail −0.006→+0.0065 but loss-light (13 losers) + fee-capped. `experiment_overround_gate.py`.
  → **Token-fear FOLLOW** (`token-fear-follow.md`) — buy the alt DOWN token on an un-proportionate token
     dump. **The closest-to-edge parked thread:** the only idea whose signal is statistically significant at
     the mid (resid +0.052, cluster-p=0.008, **all 6 coins positive**) — killed purely by the taker fee +
     Down spread, not by absence of signal. Graduates via a **fee-free maker-Down entry** or n_fired≳1800.
     `ideas_old/experiment_token_fear.py --follow` (LOCKED).
  → **B risk-filter** — ~~BTC-opposing skip on favorite-tail~~ **FALSIFIED 2026-06-25** (the alt's OWN 15s
     move gates better than BTC's; cross-asset component negative ⇒ generic favorite-momentum filter, not a
     BTC lead). See `validate_b_riskfilter.py` CHECK 5. **Demoted off the candidate board.**
  → **Spot cross-asset lead-lag** (`spot-leadlag.md`) — Stage-1 CONFIRMED across ALL 5 alts on deep
     spot: BTC 15s move → alt 5-min UP, r≈+0.11–0.13, **100% sign-stable over the full 5.5 years
     (575k windows/coin, every regime) and over 35 (coin×framing) robustness cells**; **Stage-2
     (beats the quote+fee) UNPROVEN and not spot-testable.** See `analysis/spot_leadlag.py`, memory
     `spot-history-two-stage-validation`.

## Promotion rule

A Tier-3 candidate moves up **only** on a clean pre-registered out-of-sample pass — never on
a better in-sample number, a per-coin/per-hour argmax, or a re-mine of the same data. A Tier-2
baseline becomes Tier-1 only by **stacking a Tier-3 edge that proves out** (the path for
favorite-tail is to add a forward-underpricing signal, e.g. the over-round gate or the lead-lag —
NOT a smarter threshold; out-selecting a calibrated market is already priced).

## Adaptivity policy — so the algos don't fall behind over time (2026-06-25, second-mind reviewed)

The concern is real (the market drifts), but the FIX is narrow, because this repo has already proven the
WRONG fix is fatal: **re-fitting a free threshold to recent data** (`experiment_favtail_adaptive`,
`config_tod`) DIED out-of-sample — it chases noise and deepens overfitting. So the only permitted
adaptivity is **self-normalizing** (`analysis/adaptive.py`): express a gate as a position RELATIVE to the
signal's own recent distribution (a causal trailing percentile, normalized **per coin**), so an absolute
constant floats with the regime **without adding a single fitted parameter**. The classifier:

| param type | example | rule |
|---|---|---|
| absolute **spread / size / move** | over-round ≤ 0.012; token-fear `drop ≥ 0.05` | **SELF-NORMALIZE** (per-coin rolling percentile) — these scale with vol/liquidity and differ across coins |
| **probability / price level** | favorite `ask ≥ 0.95` | **LEAVE FIXED** — 0.95 means the same thing in every regime; self-normalizing it would destroy the premise |
| **clock** position | `time_left = 30s` | **LEAVE FIXED** — a position in a fixed 5-min window, regime-invariant |

Two non-negotiables learned the hard way: (1) **normalize PER COIN** — over-round is ~5× larger on BNB
than BTC, so a pooled percentile silently gates on "which coin," not "which regime" (this bug made the
adaptive over-round gate look *worse* than fixed; fixed per-coin, it is *better*: +0.0091 vs +0.0065).
(2) **monitor with a powered detector** — the by-thirds win-rate split is a catastrophe-only smoke alarm
(blind below ~8pp drift); use `rolling_wilson_monitor` (rolling Wilson-LB(win) − breakeven) to catch a
slow edge decay below the fee wall, and alert when it crosses 0. The lookback is the ONLY knob — keep it
fixed, never tune it. Status of the sweep: favorite-tail's apparent 9→18 loser "decay" is **not
significant** (trend p≈0.07) and is consistent with a higher-vol recent regime, not efficiency erosion —
which is exactly why self-normalized + monitored beats reacting to noise.

## Roster

| strategy | tier | status | code |
|---|---|---|---|
| Favorite-tail taker, hold-to-resolution | **2 — proven baseline** | causal ✅, EV breakeven (pooled +0.005/$1, CI incl 0) | `experiment_favorite_tail.py` |
| **Over-round-gated favorite-tail** (makers' revealed-fear gate) | **3 — pre-registered (best forward signal)** | **gate signal REAL + ask-independent (joint logistic p=0.0006 — passes the test B failed); per-coin SELF-NORMALIZING form +0.0091 (beats fixed +0.0065) + drift-robust; loss-light (7-13<30) → INSUFFICIENT** | `overround-gate.md` · `experiment_overround_gate.py --adaptive` (LOCKED) |
| **Token-fear FOLLOW** (buy alt DOWN on an informed dump) | **3 — pre-registered (closest to edge)** | **signal real at mid (resid +0.052, cluster-p=0.008, all 6 coins); FAILS net — fee/spread-capped.** Flips via fee-free maker-Down or n≳1800 | `token-fear-follow.md` · `ideas_old/experiment_token_fear.py --follow` (LOCKED) |
| Spot cross-asset lead-lag (SMT) | 3 — pre-registered | Stage-1 real+stable (all 5 alts, 5.5yr, 100% sign-stable); Stage-2 EV unproven | `spot-leadlag.md` · `analysis/spot_leadlag.py` |
| ~~B risk-filter (skip BTC-opposing favorites)~~ | ~~3~~ → **FALSIFIED** | own-momentum gates better than BTC ⇒ no cross-asset content (`validate_b_riskfilter.py` CHECK 5) | `validate_b_riskfilter.py` |
| ~~Spike-gated fade~~ | ~~3~~ → **DEAD** | no dose-response across z + falling-knife fail; n=18 was best-of-cell noise | `experiment_spike_fade.py` |

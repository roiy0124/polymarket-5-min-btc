# winning_strategies/

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
  → **B risk-filter** (BTC-opposing skip on favorite-tail) — `validate_b_riskfilter.py`, LOCKED.
  → **Spot cross-asset lead-lag** (`spot-leadlag.md`) — Stage-1 CONFIRMED across ALL 5 alts on deep
     spot: BTC 15s move → alt 5-min UP, r≈+0.11–0.13, **100% sign-stable over the full 5.5 years
     (575k windows/coin, every regime) and over 35 (coin×framing) robustness cells**; **Stage-2
     (beats the quote+fee) UNPROVEN and not spot-testable.** See `analysis/spot_leadlag.py`, memory
     `spot-history-two-stage-validation`.

## Promotion rule

A Tier-3 candidate moves up **only** on a clean pre-registered out-of-sample pass — never on
a better in-sample number, a per-coin/per-hour argmax, or a re-mine of the same data. A Tier-2
baseline becomes Tier-1 only by **stacking a Tier-3 edge that proves out** (the path for
favorite-tail is to add a forward-underpricing signal, e.g. the B risk-filter or the lead-lag —
NOT a smarter threshold; out-selecting a calibrated market is already priced).

## Roster

| strategy | tier | status | code |
|---|---|---|---|
| Favorite-tail taker, hold-to-resolution | **2 — proven baseline** | causal ✅, EV breakeven (pooled +0.005/$1, CI incl 0) | `experiment_favorite_tail.py` |
| B risk-filter (skip BTC-opposing favorites) | 3 — pre-registered | real direction (perm p=0.002), not yet deployable | `validate_b_riskfilter.py` (LOCKED) |
| Spot cross-asset lead-lag (SMT) | 3 — pre-registered | Stage-1 real+stable (all 5 alts, 5.5yr, 100% sign-stable); Stage-2 EV unproven | `spot-leadlag.md` · `analysis/spot_leadlag.py` |
| Spike-gated fade (idiosyncratic-spike noise filter on the fade) | 3 — pre-registered | resid +0.115, all-4-coin positive — but n=18 (~1σ, not significant); needs OOS | `experiment_spike_fade.py` (LOCKED) |

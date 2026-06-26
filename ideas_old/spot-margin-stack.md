# Spot-margin gate + favorite-tail confidence STACK — TESTED, real signal but NO incremental edge (2026-06-26)

Script: `../experiment_favtail_stack.py` (kept — it is the additivity-diagnostic artifact). Second-mind reviewed (agent aaf2cb46).

## Thesis (why it could work)
The favorite-tail dies only to rare FLIPS. Two independent forward signals should each predict a flip:
(1) **over-round tight** = makers' revealed confidence ([[overround-gate-candidate]], a live Tier-3
candidate), and (2) **spot MARGIN** = `|price_binance − strike| / strike` (bps) — a favorite physically
FAR from the boundary is less likely to flip on a late spot wiggle, *even at the same ask*. If the two are
independent, stacking both gates should roughly double the loser-cut and push favorite-tail clearly +EV.

## Verdict: margin is REAL and independent, but the STACK adds nothing tradable.
- **Margin is a genuine independent signal** (not a confound): survives controlling for the ask
  (`won~ask+margin`: margin +0.495, positive in 99% of cluster-robust refits; corr(margin,ask)=+0.20) AND
  for the over-round (`won~over_round+margin`: both survive, margin +0.389; corr(margin,over_round)=−0.20).
  Losers sit closer to the strike (5.9 vs 7.3 bps). The 3-way joint logistic has ask +0.07 (weak),
  over_round −0.31, margin +0.37 — the two gates dominate the price.
- **But stacking does NOT beat the over-round gate alone.** Per-coin self-normalized: over_round-only EV
  +0.0091 (7 losers) → STACK +0.0096 (4 losers). Δ = **+0.0005, cluster-CI [−0.011,+0.013], P(stack >
  over_round-only) = 0.52** (a coin flip). Margin-alone is +0.0008 (≈0, weaker than over_round on every axis).

## Why it probably failed (the durable lesson)
The two signals are **statistically orthogonal as predictors but cut the SAME losers**: Jaccard(gates)=0.45,
and 11 of the 14 losers margin removes were ALREADY removed by the over-round gate (only 3 incremental).
The flip windows that makers widen the over-round on ARE the low-margin near-strike windows — different
*measurements* of the same physical danger. So stacking discards 119 winners to cut 3 extra losers, trading
a sliver of EV (statistically zero) for 3× fewer losers (4) = deeper into the loss-light trap.
**Orthogonal-as-signal ≠ orthogonal-in-which-losers-it-cuts** — the key correction to the naive
edge-stacking thesis ([[edge-stacking-philosophy]], [[combination-gating-principle]]): additivity of
coefficients does not imply additivity of tradable EV when the signals target the same failure events.

## Disposition
- **Over-round gate stays the single robust primary** (`winning_strategies/overround-gate.md`), NOT replaced.
- **Margin = a confirmed covariate of flip-risk, not a tradable gate** (like the idiosyncratic-spike idea:
  real, but its role is diagnostic). Not a standalone candidate.
- The stack script is kept as the additivity diagnostic.

## More loser-cutters screened (2026-06-26) — all fail the two-bar test
Systematically screened additional favorite-tail loser-cutters for the rare partner that is BOTH low-Jaccard
AND ask-independent (the two bars from [[additivity-overlap-lesson]]): spot-velocity-toward-strike,
token-spread, favorite-persistence ([[favorite-persistence]] — low Jaccard but FAILS ask-control = priced
ask-proxy), trade-VOLUME (Jaccard 0.40 but high volume is NEGATIVE for favorite-tail: −0.0078 alone, stack
−0.0034 — more volume = more flips), trade-count, favorite book-depth (weak ask-coef). NONE clears both bars.
**The over-round gate is the unique signal that is strong, low-overlap-irrelevant (it IS the benchmark), AND
ask-independent.** No second forward signal exists to stack into a profitable edge on current data.

## Revisit if
Find a forward signal that cuts DIFFERENT losers than the over-round gate (low Jaccard) AND survives the
joint ask-control — only then does stacking add EV. Re-gate on fresh data with ≥30 stacked losers. LOCKED.

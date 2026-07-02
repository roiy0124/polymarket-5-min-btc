# Factor sweep — fresh idea generation from the under-mined data (2026-06-25)

Goal (user): surface *new* solid factors — each a story of how traders/prices actually move — from
all the data we have, using the second-mind workflow, and screen them through the rigor gate
(`analysis/stats.assess`). NOT re-running dead ideas. The bar is the same wall as the post-mortem:
a factor must predict the **unpriced residual** `(resolved_outcome − up_mid)` AFTER the taker fee,
window-clustered and deflated — "predicts the outcome" is not enough (the mid does too).

## Method

Five independent trader-lens agents (the second-mind fan-out) each owned a microstructure
perspective and proposed causal, testable-on-our-data factors targeting unpriced residual:
order-flow/queue dynamics (`book_events`), trade toxicity/aggressor flow (`trades`), the two-token
Up-vs-Down structure, sub-second spot & settlement basis (`price_ticks`), and within-window
trader-population regime. The strongest non-degenerate candidates were then measured on the real data
via `analysis/factor_inventory.py` and `experiment_maker_timemap.py`, gated through `analysis/stats`.

## Two structural facts the sweep established (valuable regardless of EV)

1. **The Up and Down books are mostly ONE synthetic mirror.** In 75–81% of snapshots the Down book is
   an exact price+size reflection of the Up book (down price = 1 − up price, same sizes). Independent
   depth exists in only ~18% of moments and the micro-price divergence is sub-cent (std 0.0015). So the
   "two-token internal structure" lens (depth asymmetry, micro-price divergence) is **largely degenerate
   by construction** — there is no second, independent order book to exploit.
2. **Polymarket flow is ~13:1 BUY** (you go short a side by BUYING the opposite token, not selling).
   So the existing `analysis/flow.flow_imbalance` (single-token signed flow) measures a near-degenerate
   object. The correct signed-flow object is **cross-token**: BUY(Up)$ − BUY(Down)$ (CTAP below).

## Results — factor inventory (`analysis/factor_inventory.py`, tl≈60s, all 6 coins, n≈4300 windows)

| factor | story | corr(factor, won−mid) | cluster-CI | directional taker | verdict |
|---|---|---:|---|---|---|
| **CTAP** cross-token net aggressor BUY pressure | informed money lifts the winning token / buys it vs the loser | **+0.0002** | [−0.031, +0.032] | net −0.11, deflated p=1.0 | **PRICED** (CI spans 0) |
| **DEPTHA** deep bid-depth imbalance Up vs Down (independent-book subset) | resting size = where conviction sits, mid doesn't move on it | +0.0167 | [−0.040, +0.073] | net −0.21 | **PRICED** (spans 0) |
| **MICDIV** micro-price complementarity divergence | one book's queue leads the other's mid | +0.0042 | [−0.049, +0.036] | net −0.14 | **PRICED** (spans 0) |
| **OVERND** over-round `up_ask+down_ask−1` vs outcome uncertainty | makers widen the pair when unsure, tighten when confident | **+0.171** (vs \|won−mid\|) | — | n/a (a GATE, not a trade) | **REAL regime signal, no edge to gate** |

The corrected cross-token flow object (CTAP) — the toxicity lens's best idea — carries **no unpriced
residual** (corr ≈ 0, CI spans 0): the mid absorbs flow as fast as it arrives (efficient-on-knowledge,
confirmed on the proper object this time). Depth/micro factors are priced even on the non-mirror subset.

The **one genuinely real factor is the over-round** (corr +0.171 with outcome uncertainty): it is a
true "market-confidence thermometer" — wide pair ⇒ coin-flip window, tight pair ⇒ predictable window.
But it is a *conditioning* variable, and there is no profitable directional signal to condition, so it
adds no EV by itself. Worth keeping as a regime gate IF any future directional edge appears.

## Maker-toxicity time map (`experiment_maker_timemap.py`)

Tests whether the fee-free maker corner is dead EVERYWHERE or only at the window-open endpoint the
−0.365 kill measured. Rests a maker bid in mid-band [0.35,0.65] within each `time_left` band, models the
fill, holds to 0/1, credits rebate, no fee. Decisive column = fill-conditional residual `mean(won) −
mean(fill)` (a fair, non-toxic fill ≈ 0; rebate ceiling ~0.4% so a real corner needs |resid| < ~0.004).

| tl band | fills | loss | win% | mean fill | fill-resid | maker-EV | deflated p |
|---|---:|---:|---:|---:|---:|---:|---:|
| 300–240 (open) | 2340 | 1614 | 31.0% | 0.486 | **−0.176** | −0.358 | 1.00 |
| 240–180 | 1834 | 1198 | 34.7% | 0.482 | **−0.135** | −0.287 | 1.00 |
| 180–120 | 1384 | 906 | 34.5% | 0.480 | **−0.135** | −0.279 | 1.00 |
| 120–60 | 1092 | 713 | 34.7% | 0.483 | **−0.136** | −0.302 | 1.00 |
| 60–1 | 732 | 477 | 34.8% | 0.479 | **−0.130** | −0.057 | 1.00 |

**Every band's fill-conditional residual is −0.13 to −0.18** (a non-toxic fill needs |resid|<~0.004). So the
fee-free maker corner is dead across the WHOLE window, not just at the open endpoint the −0.365 measured.
The interior bands (the within-window agent's main hope) are −0.135 — slightly less toxic than open but
still catastrophically adverse-selected. The maker corner is now comprehensively closed.

## The ONE candidate the sweep produced: over-round-gated favorite-tail

The over-round (+0.171 with outcome uncertainty) is not just a thermometer — it gates the project's anchor.
**Story:** when a near-certain favorite (ask 0.95–0.99) is about to flip, the market-makers — who see the
flow — defensively WIDEN the pair, so the over-round rises. Tight over-round = makers calm = fewer
flip-losers. `experiment_overround_gate.py`: gating favorite-tail (tl~30, ask∈[0.95,0.99)) to tight
over-round (≤0.012) flips net-EV from **−0.0058 → +0.0065** and cuts losers 30→13 (win 96.5%→97.7%).

Second-mind adversarially reviewed (agent a954c636). **The SIGNAL is real and survives the decisive
anti-confound test** that killed the B-filter: joint logistic `won ~ fav_ask + over_round` gives
over_round coef −0.358, **z=−3.42, p=0.0006** (correct sign, tight→winning), while the favorite's own ask
is NOT significant (p=0.40) — over_round *dominates* the price; negative in 99% of cluster-robust refits;
permutation p=0.003; tight beats wide in every fine ask-matched bin. The confound (corr over_round vs
fav_ask) is only −0.075 on the actual trading band. **BUT the tradable EV is fee-capped + loss-light:**
CI spans 0, Wilson-LB < breakeven, only **4 extra losers flip it negative**, multiplicity-deflated p≈0.95.
Verdict: **pre-register the signal, do NOT deploy** — a real, ask-independent directional signal (the
first to pass joint-control), but still INSUFFICIENT by the gate. Re-gate when gated losers ≥30 with
deflated p<0.05 AND Wilson-LB>breakeven. Params LOCKED. Added to `winning_strategies/` as Tier-3.

## Bottom line

The fresh factor sweep found **one real new signal** (over-round = makers' revealed fear) and a pile of
honest kills. The signal lifts the favorite-tail anchor from breakeven-negative to breakeven-positive and
is genuinely better-founded than the dead B-filter (it passes the joint-control test, p=0.0006), but it is
fee-capped + loss-light so it is a pre-registered CANDIDATE, not a deployable winner. Everything else is
priced: the corrected cross-token flow (CTAP) is absorbed by the mid, the two-token book is one synthetic
mirror, and the fee-free maker corner is dead across the entire window. This both *advances* the list (a
new pre-registerable candidate grounded in trader behavior) and *strengthens* the walled verdict on the
directional-microstructure family. Durable artifacts: `analysis/factor_inventory.py`,
`experiment_maker_timemap.py`, `experiment_overround_gate.py`. Remaining untested-here hopes need LIVE
data (sub-second staleness on `price_ticks`).

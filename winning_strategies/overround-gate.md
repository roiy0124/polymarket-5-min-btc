# Over-Round-Gated Favorite-Tail (the makers' revealed-fear gate) — TIER 3 (pre-registered candidate)

**The strongest forward-signal candidate the project has found** — and the first gate to survive the
joint-control test that killed the B risk-filter. It does not predict better than the mid; it reads the
**market-makers' confidence** off the order book and skips the favorite-tail's rare flip-losers.

> **STATUS (2026-06-25, second-mind reviewed — agent a954c636):**
> - ✅ **Causal / real-time implementable.** The over-round is the live `up_ask + down_ask − 1` at the decision instant — fully observable, no look-ahead.
> - ✅ **The SIGNAL is real and ASK-INDEPENDENT** (the decisive test the B-filter failed). Joint logistic `won ~ fav_ask + over_round`: over_round coef **−0.358, z=−3.42, p=0.0006** (tight→winning), while the favorite's own ask is **not** significant (p=0.40) — over_round *dominates* the price. Negative in 98–99% of cluster-robust refits; permutation p=0.003; tight beats wide in every fine ask-matched bin.
> - ⚠️ **The tradable EV is fee-capped + loss-light.** Gated net-EV **+0.0065** (vs base −0.0058) but cluster-CI **[−0.009, +0.020]** spans 0, Wilson-LB < breakeven, only **4 extra losers flip it negative**, multiplicity-deflated p≈0.95. INSUFFICIENT (13 gated losers < 30), not SURVIVES.
> - It graduates ONLY on fresh data with ≥30 gated losers AND deflated p<0.05 AND Wilson-LB>breakeven. Params LOCKED; do NOT re-tune the threshold on this data.

## The rule (exactly what a live bot does)
At **time_left ≈ 30s** in each 5-min window:
1. **Favorite** = `Up` if `price_binance ≥ strike_binance` else `Down`. Read its live **ask**.
2. Require `0.95 ≤ fav_ask < 0.99` (the moderate-favorite band — at 0.99+ the gate adds nothing, the favorite is already certain).
3. **GATE (self-normalizing, recommended):** trade only if `over_round = up_ask + down_ask − 1` is in the TIGHT HALF of its OWN trailing distribution **for that coin** (rolling percentile ≤ 0.5, lookback 200). Equivalently the fixed form `over_round ≤ 0.012`, but the relative form tracks regime drift with no fitted constant. Skip if wide (makers defensive = flip risk).
4. **Taker-BUY** the favorite, **HOLD to 0/1** (fee only on entry). One position per window.

Reproduce: `python experiments/experiment_overround_gate.py --adaptive` (includes the joint-control anti-confound test + drift monitor).

## Adaptivity (so it doesn't fall behind over time — second-mind reviewed)
The gate's `over_round` threshold is an absolute **spread** in a quantity whose scale is ~5× different
across coins and drifts with vol/liquidity — exactly the kind of constant that goes stale. So the PRIMARY
form is **self-normalizing, PER COIN** (`analysis/adaptive.rolling_pct_rank(..., groups=coin)`): keep
windows whose over-round is in the tight half of *its own coin's* recent distribution. Done per-coin it
**beats the fixed gate on current data (+0.0091 vs +0.0065)** *and* is drift-robust by construction with
zero added DOF. (Pooling all coins into one percentile is a BUG — it gates on "which coin has tight
spreads," not "which window is tight for its regime"; that made the naive adaptive version look worse.)
The `ask ≥ 0.95` and `tl = 30s` params are LEFT FIXED — a probability and a clock position are
regime-invariant; self-normalizing them would destroy the premise. Monitor live decay with
`rolling_wilson_monitor` (rolling Wilson-LB − breakeven), NOT the underpowered by-thirds split. The
lookback (200) is the only knob — keep it fixed, never tune.

## The trader story (why it's a factor, not a fit)
The favorite token's **price** is the *level* of belief; the **over-round** is the *liquidity/confidence*
makers post around it — two different objects. When a near-certain favorite is about to flip, the
market-makers (who see the order flow first) turn defensive and **widen the pair**, raising the
over-round, *before* the flip shows in the resolution. So the over-round is the makers' revealed fear,
and it carries information the favorite's own quote hasn't absorbed — confirmed by the joint logistic
where over_round is significant (p=0.0006) and the ask is not. This is exactly a **forward-underpricing**
gate (the only kind the combination-gating principle says can add edge), not a backward score.

## Performance (causal, net of taker entry fee, window-clustered)
| set | n | losers | win% | net EV/$1 | cluster-CI |
|---|---:|---:|---:|---:|---|
| baseline favorite-tail, ask∈[0.95,0.99) | 854 | 30 | 96.5% | −0.0058 | [−0.022, +0.008] |
| **GATED tight over-round (≤0.012)** | 563 | 13 | 97.7% | **+0.0065** | [−0.009, +0.020] |

Loser separation: over-round on **winners +0.0246 vs losers +0.0487** (losers ~2× wider). Ask-controlled:
within 0.95–0.97 tight loss 2.8% vs wide 6.7%; within 0.97–0.99 tight 2.0% vs wide 5.2%; at 0.99+ no effect.

## Why it isn't money yet (the same wall, one step back)
1. **Fee-capped.** The signal is real but the gross edge (~+0.012 EV swing) barely clears the taker fee + spread, so the net CI still spans 0.
2. **Loss-light.** 13 gated losers; the project's documented degenerate-CI trap — **4 unlucky flips erase it**. Wilson-LB is below breakeven from the start.
3. **Multiplicity.** It came out of a dozens-of-factor sweep; deflated for that, the +EV is indistinguishable from best-of-N noise *as a strategy* (the SIGNAL, separately, is not — p=0.0006).

## Path to Tier 1
- **More data → ≥30 gated losers**, then re-gate LOCKED. Graduate iff deflated cluster-bootstrap p<0.05 AND Wilson-LB(win)>breakeven AND the joint-control still shows over_round significant-negative.
- **Lower fees / tighter spreads** would flip it directly (the gross edge already clears a smaller cost).
- **Stack with the spot lead-lag** (the other forward signal): both are forward-underpricing gates on the same favorite-tail base; the additivity diagnostic (unbuilt) would say whether they combine.

### Tested extension — spot-margin stack (2026-06-26, NO incremental edge → `ideas_old/spot-margin-stack.md`)
The spot **margin** `|price_binance − strike|/strike` is a *genuinely independent* flip-predictor (survives
controlling for both the ask and the over-round; losers sit closer to the strike, 5.9 vs 7.3 bps). But
stacking a margin gate ON TOP of the over-round gate adds **nothing tradable**: Δ EV +0.0005 (CI spans 0,
P=0.52), because the two signals cut the SAME losers (Jaccard 0.45 — near-strike windows are both
low-margin AND wide-over-round). Lesson: orthogonal-as-signal ≠ orthogonal-in-which-losers-it-cuts. So
margin stays a confirmed *covariate of flip-risk*, not a second gate; the single over-round gate remains
the robust primary. `experiments/experiment_favtail_stack.py` is the additivity diagnostic.

### Tested extension — maker entry in the gated windows (2026-06-26, breakeven, the FIRST non-adverse maker)
A structural bonus of this gate: it identifies windows where MAKER provision on the favorite is *fair*, not
adverse. Resting a maker bid on the favorite (1 tick below ask, fill-modeled from SELL prints, hold to 0/1,
no fee): in ALL windows it's adverse (fill-conditional win 92.1% vs fill 0.952, resid −0.032), but in
**over-round-TIGHT windows the fill is non-adverse** (win 95.7% vs fill 0.958, **resid −0.0007** — vs the
−0.18 that killed the mid-band maker-in-noise). This is the only fee-free non-adverse fill the project has
found. BUT maker-EV is only ~breakeven (−0.0001), NOT better than the taker gate: you fill just 45% of the
time and on the favorites that *dropped* to your bid (win 95.7% < the taker's full-population 98.7%), so the
fill-selection cost (~3%) cancels the spread saving (~1%). Keep the TAKER entry as primary; the maker variant
becomes attractive only if Down-side spreads widen (more spread to save) or fills improve. Proves the gate
finds maker-safe windows — a real, reusable structural fact.

Do NOT re-tune `or_thresh`, `ask` band, or `tl` on this data (overfit trap — the B-filter died on its
in-sample discovery). `execution/live_runner.py` stays GATED. This is the best lead since the program walled —
because its kill is **cost + power, not a falsified mechanism** (the mechanism passed the test that
falsified B).

# Favorite-Tail Taker, Hold-to-Resolution  — TIER 2 (proven baseline)

**The best, closest-to-viable strategy the project has found, and the anchor of this folder.**
Full detail + all the rejected refinements live in the canonical doc `../STRATEGY-FAVORITE-TAIL.md`;
this card is the honest one-page status.

> **STATUS (2026-06-23):**
> - ✅ **Causal / real-time implementable, NO look-ahead** — this was the gate it passed to be adopted.
> - ⚠️ **EV = statistical BREAKEVEN, not a proven winner.** Pooled net +0.001…+0.005 per $1, 95% CI **includes 0** in every variant; bnb negative; no cross-coin replication of significance. Best we have — *not money yet*.
> - It becomes a Tier-1 winner ONLY by stacking a **forward-underpricing** edge (the B risk-filter or the spot lead-lag), **not** a smarter entry threshold — every selectivity refinement was tested and REJECTED (out-selecting a calibrated market is already priced).

## The rule (exactly what a live bot does)
At a fixed decision time late in each 5-min window (**time_left ≈ 30s**):
1. **Favorite** = `Up` if `price_binance ≥ strike_binance` else `Down` (current Binance price vs the window's strike).
2. **Read the favorite side's live ASK.** If `MIN_ASK ≤ ask < 1.0` (e.g. 0.95), **taker-BUY** the favorite.
3. **Exit:** rest a maker sell at target; if unfilled, **HOLD to the 0/1 resolution. NEVER taker-cross to exit**
   ⇒ the taker fee bites only the ENTRY (`0.07·ask·(1−ask)`, ~0.2% at ask≈0.97).

One position per window. High coverage, high win-rate, fee only on entry.
Reproduce: `python experiment_favorite_tail.py --coin all --min-ask 0.95 --tl 30`.

## Performance (causal backtest, net of taker entry fee, window-clustered bootstrap CI)
| coin | n | win% | mean ask | EV/$1 | 95% CI |
|---|---:|---:|---:|---:|---|
| btc | 348 | 99.1% | 0.981 | +0.0092 | [−0.0025, +0.0178] |
| eth | 75 | 98.7% | 0.982 | +0.0031 | [−0.0262, +0.0194] |
| sol | 97 | 99.0% | 0.981 | +0.0071 | [−0.0155, +0.0199] |
| xrp | 97 | 100% | 0.982 | +0.0175 | [+0.0144,+0.0205] (loss=0 artifact) |
| doge | 89 | 98.9% | 0.982 | +0.0053 | [−0.0190, +0.0189] |
| bnb | 127 | 96.9% | 0.981 | −0.0139 | [−0.0473, +0.0120] |
| **POOLED** | 833 | 98.8% | — | **+0.0054** | **[−0.0051, +0.0136]** |

Pooled = breakeven (CI includes 0). Per-coin "significant" cells are loss=0 zero-variance artifacts, not real.

## Why it isn't money yet
1. **Breakeven by construction** — realized win-rate ≈ ask (calibrated market), so buying at ask earns ~0 gross.
2. **−100% flip tail** — one loss ≈ 30–160 wins; losses happen even at ask 0.99+; no clean loss-stop on a binary.
3. **Settlement basis** — favorite picked on Binance, resolves on Chainlink; ~4% of windows the basis flips the winner.
4. **Thin depth** at 0.95–0.97; filling size walks the book.
5. **No cross-coin replication** of significance on the ~22h alt sample.

## Path to Tier 1 (how this graduates to a deployable winner)
Stack a **forward-underpricing** signal that the calibrated quote hasn't yet absorbed — both candidates are in
Tier 3 of this folder, awaiting fresh-data proof:
- **B risk-filter** — SKIP an alt entry when BTC's last ~15s move OPPOSES the favorite (cuts boundary-flip losers
  the alt quote hasn't repriced from BTC's lead). Real direction (permutation p=0.002) but pre-registered, not yet
  deployable. Re-test: `python validate_b_riskfilter.py` (params LOCKED).
- **Spot cross-asset lead-lag** — same BTC-leads-alt mechanism, now confirmed real+stable on 5.5yr-deep spot
  (Stage 1). Needs Stage-2 proof that SOL's *quote* lags enough to beat the fee. `analysis/spot_leadlag.py`.

**Do NOT** adopt the in-sample oracle cutoff or any per-coin/per-hour argmax threshold — documented overfit trap
(oracle − adaptive ≈ +0.0095 of pure look-ahead that vanishes live). `live_runner.py` stays GATED until a stacked
edge clears a clean pre-registered OOS test.

# IDEAS.md — strategy edge backlog (discuss one at a time, then test)

Companion to **`EXPERIMENTS.md`** (what we have already TRIED + the verdicts). This is the
queue of ideas to *explore*: we discuss each one separately, write down the thinking, and
only then build a test. An idea graduates to `EXPERIMENTS.md` once it's been measured.

## The walls every idea must beat (proven, see EXPERIMENTS.md)
1. **Efficient on knowledge** — the token price already prices position AND recent trend
   (Brier ~0.12; residual correlations ~0). Predicting the outcome ≠ beating the price.
2. **Taker fee** (`crypto_fees_v2`, confirmed live on the 5-min market):
   `fee/stake = 0.07·(1−p)` → **3.5% at p=0.50, ~0.7% at 0.90, ~0.2% at 0.97**. Charged on
   every spread-cross. Makers exempt + 20–25% rebate.
3. **Maker side is adverse-selected** — resting limits fill exactly when you're wrong.
4. Plus: **−100% on a miss** (binary), and a real **~1s BTC→quote lag** that is spread-capped.

## Index (status)
- **A. Fee-topology: late-window favorites** — 🟢 discussing first (testable on existing BTC data)
- B. Cross-asset lead-lag matrix → laggard taker — ⚪ queued
- C. Basket-divergence SMT — ⚪ queued
- D. Settlement-basis edge (Chainlink vs Binance) — ⚪ queued (needs Chainlink data)
- E. Maker-rebate harvesting at the tails — ⚪ queued
- F. Multi-coin as a measurement multiplier (meta) — ⚪ queued

## Deferred tech-debt
- **Price-column naming.** `btc_binance` / `btc_pyth` / `btc_ticks` hold each coin's OWN
  price (legacy names, no bug). Rename to coin-neutral (`price_binance`/`price_pyth`/
  `ref_ticks`) **when**: we build cross-coin tooling that joins several coins' price columns
  in one query, or any other schema migration happens, or we hand off the dataset. Documented;
  safe until then.

---

## A. Fee-topology: trade late-window favorites where the fee ~vanishes

**Status:** discussing (2026-06-23). Testable NOW on the existing deep BTC data — no alts needed.

**The core observation.** The taker fee as a fraction of stake is `0.07·(1−p)`, so it
*collapses* toward the price extremes:

| ask (p) | fee/stake | breakeven win-rate `a + 0.07·a·(1−a)` |
|---|---|---|
| 0.50 | 3.50% | 0.518 |
| 0.80 | 1.40% | 0.811 |
| 0.90 | 0.70% | 0.906 |
| 0.95 | 0.35% | 0.953 |
| 0.97 | 0.21% | 0.972 |

At p=0.50 the fee alone (3.5%) swamps any small mispricing — which is exactly why the
taker died there. But buying a **near-certain favorite at ~0.96**, the fee adds only
**~0.3pp** to the hurdle. So a *small* underpricing of late-window favorites becomes
tradeable for the first time.

**Mechanism (why a gap might exist).** Late in the window with BTC clearly above (or below)
strike, the true P(favorite) may be ~0.99 while the quote lags at ~0.96 — because (a) MMs
quote conservatively near resolution, and/or (b) the ~1s BTC→quote lag hasn't caught up to
the move that cemented the outcome. The fee no longer eats it, so the lag-edge can survive.

**Why it fits the user's goal.** It's intrinsically **high win-rate / consistent** (you're
buying near-certainties), which matches the stated preference for steady coverage over big ROI.

**Test plan (existing BTC data, one obs per window for independence):**
- For each settled window, at late times (sweep T_left ∈ {5,10,20,30}s), take the **favorite
  side's ASK** (the side the BTC gap favors).
- Net taker EV per share = `outcome_win − ask − 0.07·ask·(1−ask)` (taker fill is certain).
- **Calibration at the tail:** bucket by ask (0.90–0.92, …, 0.98–0.99); realized win-rate vs
  ask. Edge if realized > breakeven (window-clustered bootstrap CI excludes 0).
- Also: does it concentrate when the BTC gap is large / the quote is visibly lagging?

**Risks / kill-criteria (be honest):**
- **Efficiency:** if the quote already = true p at the tail (realized ≈ ask), there's no gap.
  The market is well-calibrated overall — this must be checked *specifically* at the late tail.
- **−100% asymmetry:** one adverse fill (BTC flicks back across strike in the final seconds)
  at p=0.96 wipes ~24 wins of +4%. The true win-rate must *robustly* clear breakeven; a thin
  edge is fragile. Needs a hard loss-stop / sizing discipline.
- **Liquidity:** depth at the 0.96 ask is thin — can we fill real size?
- **Settlement basis:** "clearly above strike" on Binance may disagree with Chainlink at the
  boundary → we think 0.99, it settles the other way (ties into idea D).

**Open questions for discussion:**
1. Favorites only (fee-cheap). Longshots are fee-EXPENSIVE (`0.07·(1−p)` → ~6.7% at p=0.05),
   so they're out — confirm we're hunting the high-p favorite tail.
2. How late is the sweet spot — last 30s, 10s, 5s? (Later = more certain but thinner upside.)
3. Loss-stop appetite given the −100% tail risk.

**Decision:** _pending discussion._

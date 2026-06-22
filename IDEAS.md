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
- **A. Fee-aware net-EV signal selection** (was "late-window favorites") — 🟢 exit policy DECIDED (maker-rest-else-hold; never taker-exit); next = encode `net_ev` + wire into scorers
- **B. Cross-asset lead-lag → laggard taker** — 🟢 discussing now
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

### A.1 — Exit-execution sub-problem (under deep research, 2026-06-23)

Reframed (user): the fee is a **net-EV cost input to signal selection**, not a directional
bias. Score every candidate signal on profit *after fees*; the statistics decide. The fee is
price-dependent (`0.07·p·(1−p)`) so near-50/50 signals must clear a bigger gross edge — as a
consequence of honest accounting, not a steer toward the tails. KEY NUANCE: the taker fee
applies ONLY to spread-crossing fills; a resting limit that fills is a **maker (0 fee + 20–25%
rebate)**, and holding a binary to settlement is **fee-free** (not a taker trade).

So the open question is the EXIT POLICY. Candidates:
- **(a) rest a maker sell at target** — no fee + rebate, but fills only when price rises → on winners.
- **(b) rest, else cross to exit (taker)** — user's first instinct. CRITIQUE: the taker
  fallback fires exactly on losers (price fell, limit unfilled) → you pay the fee *and* book a
  loss; the cheap exit lands on winners, the dear one on losers = adverse selection relocated
  to the exit. Softens, doesn't escape it.
- **(c) rest, else HOLD to 0/1 resolution** — no exit fee EVER (settlement isn't a taker
  trade); cost is the full −100% on losers you'd likely lose anyway. Probably dominates (b).
- hybrids: timeouts, reprice toward mid, partial exits, trailing.

**Deep-research verdict (2026-06-23, run wf_51c2b4d1-413; 101 agents, 19 sources, 22 verified
claims; see memory [[exit-execution-verdict]]):**
- The resting maker SELL is **adversely selected by construction** (winner's curse): fills
  ~certainly on winners, unfilled on losers; fill prob is *negatively* correlated with
  outcome. (DeLise 2407.16527; Market Maker's Dilemma 2502.18625; Cont-Kukanov 1210.1625.)
- **Taker-cross-to-exit (policy b) is the WORST** — it fires precisely on losers (adverse
  selection moved to the exit) + pays the fee. Justified only under a hard deadline (not us).
- **REFUTED (0-3):** "sell orders escape the taker fee." Fees are taker-vs-maker, not
  buy-vs-sell; a crossing sell is a taker and pays. **Only fee-free exit = HOLD to settlement.**
- No simple price-taking strategy beats this structure (Snowberg-Wolfers, 6.4M races); aligns
  with our "efficient on knowledge" finding → retail net-positive after the 0.07 fee unlikely.

**DECIDED EXIT POLICY:** rest a **maker sell at the target; if unfilled, HOLD to 0/1
resolution. NEVER taker-cross to exit.** ⇒ the fee is **moot on exit** (maker = 0, hold = 0);
it only bites on a taker **ENTRY** (the latency play). So fee-aware net-EV = charge
`0.07·a·(1−a)` on taker entries only; model the maker-sell fill as **outcome-conditional**
(winner's curse), plus the −100% on held losers. Our existing exit-map reach-EV
(`reach·roi − (1−reach)`) already captures the winner's curse via the price path — just add
the taker-entry fee and do NOT add a taker-exit fallback.

**net_ev skeleton** (Cont-Kukanov + binary extensions): half-spread + taker fee on crossed
legs + maker rebate (minus an adverse-selection penalty) + asymmetric under/over-fill
penalties, PLUS a hold-to-0/1 branch and the −100% loss term, PLUS an explicit
adverse-selection penalty on the maker-sell fill probability.

**Measurements to run (settle the residual value):** (1) empirical outcome-conditional fill
rate + win rate of a resting sell at target on these 5-min markets; (2) the (p, time-left,
signal-win-prob) grid where hold-to-resolution beats any taker exit.

**Status:** ✅ exit policy decided + documented. Next: encode `net_ev(entry, exit, entry_mode,
exit_mode)` (taker-entry fee; maker-or-hold exit; −100% term) and wire into the signal scorers.

---

## B. Cross-asset lead-lag → laggard taker

**Status:** discussing (2026-06-23). Needs more alt data to test the EV; the lead-lag *matrix*
is testable sooner. This is the pairwise version of SMT; idea C is its basket generalization.

**Core hypothesis.** A leader coin (BTC, or whichever the data says) leads the alts. When the
leader moves, (1) the alt's *underlying* price follows within seconds, and (2) the alt's
*Polymarket quote* follows even **later**, because alt markets are sleepier / less contested.
So a bot that sees the leader move can take the alt's **stale quote** before it reprices — a
**taker entry on a genuine cross-asset information edge** (LONG the option, unlike passive).

**Two lead-lag layers (keep them separate):**
- *Underlying* lead-lag: does BTC's price lead ETH/SOL/XRP/DOGE/BNB's price? (Crypto is highly
  correlated; BTC often leads, but it's time-varying — prior research had Bybit/OKX leading
  Binance in some windows. Measure, don't assume.)
- *Quote* lead-lag: does each alt's Polymarket quote lag its OWN underlying (like BTC's quote
  lagged BTC ~1s), and does it lag *more* (sleepier = bigger window)?
The edge stacks both: leader move → predicts alt underlying → alt quote hasn't priced it yet.

**Why it might beat the walls.** Efficiency: alt markets *may* be less efficient than BTC's
(the whole hope) → the cross-asset residual could be nonzero where BTC-on-itself was zero.
Fee: it's a taker entry, so it pays `0.07·a·(1−a)` (use the idea-A net_ev) — needs a *fat*
dislocation to clear it. Adverse selection: a taker on real info is on the right side of it.

**THE CRUX RISK (be honest up front).** "Sleepier" cuts both ways: the same illiquidity that
makes an alt quote lag also makes its **spread wide and depth thin**. We cross that spread as a
taker — so a 5–10¢ alt spread can cost *more than the lag is worth*, and we may not fill size.
The make-or-break is whether **lag-capture > spread + fee** on any coin. Likely only the more
liquid alts (ETH/SOL) are tradeable; the sleepiest (DOGE/XRP/BNB) may lag most but be
un-crossable. The data decides.

**Test plan (in order; first step is ~data-ready):**
1. **Underlying lead-lag matrix** — 6×6 cross-correlation of 1s **% returns** (scale-normalized)
   between coins' Binance prices, swept over lags. Identifies leader→laggard pairs + peak lag.
   Cheap; needs only a few hours of multi-coin ticks (have some).
2. **Per-coin quote lag** — each alt's Polymarket-mid lag vs its own underlying (reuse the
   lookahead lead-lag tool). Which alts lag longest?
3. **Cross-asset residual test** — does the leader's recent move predict the laggard's OUTCOME
   *beyond* the laggard's market price? `corr(leader_move, alt_outcome − alt_price)`. >0 (CI
   excludes 0) ⇒ the alt underreacts to the leader ⇒ edge. (Mirrors `experiment_trend_outcome`.)
4. **Net-EV taker sim** — when the leader moves enough, take the alt's stale quote (taker
   entry, pay fee), exit maker-rest-or-hold (idea-A policy); window-clustered CIs; explicitly
   net of the **alt spread**. This is where `net_ev` gets built.

**Risks / kill-criteria:** (a) alt markets as efficient as BTC's → residual ~0; (b) alt spread
+ thinness eats the lag (the crux); (c) leader→laggard relationship time-varying / breaks on
alt-idiosyncratic moves; (d) fee needs a fat dislocation.

**Open questions for discussion:**
1. Leader choice — BTC only, or the best leader per the matrix (could be ETH/SOL)? (I'd let the
   matrix decide.)
2. We must measure the **net** (lag-capture − spread − fee), not just the lag — agree the crux
   is the spread/liquidity of the sleepy alts?
3. Scope now: run the **underlying lead-lag matrix** soon (data-light) and defer the residual/
   EV tests until alts have ~days of windows?

**Decision:** _pending discussion._

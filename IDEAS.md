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
- **B. Cross-asset divergence scan (SMT)** — 🟢 design agreed; B1 simple existence test next (absorbs C)
- ~~C. Basket-divergence SMT~~ — **merged into B** (B is the scan-and-compare divergence)
- **D. Settlement-basis edge (Chainlink vs Binance)** — 🟢 discussing now
- E. Maker-rebate harvesting at the tails — ⚪ queued
- F. Multi-coin as a measurement multiplier (meta) — ⚪ queued

## D. Settlement-basis edge (Chainlink vs Binance/Pyth)

**Status:** discussing (2026-06-23). Discussion/design only; tests deferred until more data.

**Mechanism.** Each market RESOLVES on the **Chainlink** `<COIN>/USD` data stream, but we — and
most retail, and the feeds the crowd watches — read **Binance spot / Pyth**. Near the window
boundary, the Binance↔Chainlink **basis** can *flip* the outcome (when the final price sits
within a few $ of the strike). Two edge forms:
- *Information:* be ON the settlement feed (Chainlink) → know the true outcome a beat before a
  market that prices off a CEX.
- *Basis modeling:* if the Binance↔Chainlink basis has a predictable lag/bias, correct our
  Binance read toward the likely Chainlink value to sharpen boundary-case outcome prediction.

**Why it might beat the walls.** It's a *different* knowledge than position/trend (which the
market already prices). The whole question is whether the **quote already prices Chainlink** —
sophisticated MMs must, since they price the settlement; if so, no edge. If many participants
lag (price off the CEX), knowing Chainlink first is an edge. Either way it's concentrated in the
**minority of "coin-flip" boundary windows** (most windows resolve unambiguously).

**Crux doubts (honest).** (a) MMs probably DO price off Chainlink → quote already reflects it →
same efficiency wall. (b) The fast Chainlink **Data Stream is auth-gated/paid** (acquisition
cost); the free **on-chain** Chainlink feed updates only on a heartbeat/deviation (not
sub-second) → likely too stale at the boundary. (c) Few opportunities (boundary windows only).
(d) Still a latency race at the close.

**First test (DATA-READY, deferred).** Measure the Binance-vs-Chainlink **outcome disagreement
rate** on resolved windows: `our_outcome` (Binance final ≥ strike) vs `resolved_outcome`
(official = Chainlink). The disagreement % **sizes the opportunity** — ~0% ⇒ basis never flips,
dead; X% ⇒ that's where a Chainlink edge would live. We already log BOTH columns, so no new
feed is needed just to size it. (Then, if non-trivial: does `resolved_outcome` track the QUOTE
better than our Binance-final near the boundary — i.e., is Chainlink already in the price?)

**Open questions for discussion:**
1. Goal — the *information* edge (needs the fast Chainlink feed) or just *basis-modeling*
   (correct Binance→Chainlink, no new feed)?
2. Appetite to acquire Chainlink data — free on-chain heartbeat read vs the paid fast stream?
3. Agree the cheap first step is the **disagreement-rate sizing** (data-ready, run later)?

**Decision:** _pending discussion._

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

**Core hypothesis (refined w/ user 2026-06-23).** NO fixed leader and NO fixed coin to trade.
We **scan all six coins continuously and compare their moves**. Crypto is highly correlated, so
when one coin's *market* hasn't moved in line with its peers (a divergence **GAP**), that coin's
quote is stale → we act on *whichever* coin shows the gap, in *whichever* direction. (This
**absorbs the old idea C "basket divergence" — same thing**, just stated as a live scan.) It's a
**taker entry on a cross-asset information gap**, exit maker-rest-or-hold (idea A).

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

**Testing philosophy (user):** start with the SIMPLEST test with the FEWEST moving parts —
just check whether the SMT gap EXISTS and carries information — *before* layering in spread/
fee/fill realism. **24h of data is enough for first conclusions.**

**B1 — does the gap exist & inform? (simple; ~24h; NO cost modeling yet):**
1. *SMT prerequisite* — pairwise correlation of the coins' 1s **% returns** (do they move
   together at all? high corr ⇒ divergences are meaningful). Optional: peak lag per pair.
2. *Convergence* — define each coin's GAP at time t = (peer-consensus recent %move) − (that
   coin's own recent %move); test whether the gap predicts the coin's **forward** move (does the
   laggard catch up?): `corr(gap, forward_return) > 0`. Underlying-only — no market data needed.
3. *Beyond the price* — does the gap predict the coin's OUTCOME **residual** (`outcome − up_mid`)?
   i.e., is the gap NOT already in the quote? (the only part needing snapshots.) >0 with CI
   excluding 0 ⇒ a real, **unpriced** SMT margin.
   → if B1 is flat: gap already priced, or coins don't diverge informatively → stop.
   → if B1 is positive: proceed to B2.

**B2 — is it tradeable? (the realistic layer, DEFERRED until B1 is positive):** net-EV taker
sim — take the laggard's stale quote, net of the **alt spread** + taker fee (idea-A `net_ev`),
maker-rest-or-hold exit, window-clustered CIs. This is where the crux (is spread > lag?) is decided.

**Risks / kill-criteria:** (a) alt markets as efficient as BTC's → residual ~0; (b) alt spread
+ thinness eats the lag (the crux); (c) leader→laggard relationship time-varying / breaks on
alt-idiosyncratic moves; (d) fee needs a fat dislocation.

**Decision (2026-06-23):** design agreed — scan-and-compare (no fixed leader/target; absorbs C);
**B1 simple existence test first** (correlation prerequisite + gap→convergence + gap→outcome-
residual, no cost modeling), on ~24h of data; **B2 net-of-spread taker sim deferred** until B1
is positive. Built `experiment_xasset_smt.py`.

**B1 FIRST PASS (2026-06-23, only ~4.3h of overlap — PRELIMINARY, not the 24h bar):**
- Part 1 (prerequisite) — **STRONG: coins move together, mean pairwise corr +0.64** (BTC–ETH
  0.73; all 0.57–0.73). Divergences are meaningful. Robust even on 4.3h. ✅
- Part 2 (convergence) — **inconclusive: corr(gap, fwd) = +0.037, CI [+0.004,+0.069]**. Tiny,
  the CI is *understated* (return autocorrelation), and it's only 4.3h. NOT a signal yet.
- DATA NOTE: alts only began clean collection 06-22 16:11 UTC (~4.3h); the double-supervisor
  left **duplicate snapshot rows** (123% coverage) — B1 dedupes by second so it's unaffected,
  but run the dedupe pass before deeper analysis.
- NEXT: re-run at **≥24h** (≈20h away); add a **per-coin** convergence breakdown (pooling the
  leader BTC with laggard alts dilutes — alts should converge more, BTC less); then, if Part 2
  firms up, do Part 3 (gap vs the QUOTE = is it unpriced) → B2.

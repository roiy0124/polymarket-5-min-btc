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

## Guiding principle (user, 2026-06-23)
We are **not** hunting one silver bullet that flips us to profit — we're **stacking small
edges**. Because the strategy sits right at the wall (~breakeven after the structural costs),
**each small edge can flip the sign**, and they're additive. So a thin convergence signal, a
0.5% fresher feed, a 0.3% fee saving, a better settlement read — individually marginal, jointly
decisive. Evaluate every idea as a *contributor*, not as a standalone money-printer.

Corollary on the **TIME/SPEED edge** (a recurring want): the fastest *free* price is a direct
**exchange WebSocket** (Binance spot/perp, multi-venue) — NOT an oracle. Chainlink is downstream
of the exchanges, so it can't beat them on speed; it's only relevant for settlement *correctness*
(idea D). No paid streams (if a paid feed gave a clean edge it'd already be standard).

**Prediction, not trading (the translation principle).** This is **outcome prediction** of a
binary 0/1, not continuous-P&L trading. Any trading strategy (SMT, pairs, ICT, order-flow,
momentum…) is only useful here if, once translated, its signal **predicts the binary OUTCOME
better than the token PRICE already does** — a positive **residual** `corr(signal, outcome −
price)`, net of fees, ideally replicating across coins (idea F). Predicting *direction* is
worthless if the price has it. This is how we judge every candidate — exactly how SMT became
idea B. (Strategy-survey deep research in flight: run `wf_28066528-bb1` → will spawn ideas G+.)

## Index (status) — updated by the 2026-06-23 full audit (see EXPERIMENTS.md "FULL IDEA AUDIT")
- **A. Fee-aware net-EV signal selection** (was "late-window favorites") — 🔴 favorite-tail TESTED (first time): late favorites well-calibrated, pooled tail +0.003 EV/$1 CI[−0.005,+0.010] = breakeven, dead standalone. Exit policy (maker-rest-else-hold) KEPT. `net_ev` still UNBUILT (next, needed for B2).
- **B. Cross-asset divergence scan (SMT)** — 🟡 **TESTED as a favorite-tail component (2026-06-23).** Convergence/gap framing DEAD (doge noise). But the **btc-opposing RISK-FILTER** (skip alt favorite-tail when BTC's last ~15s move opposes the favorite) is the FIRST real directional signal: +0.0151 vs +0.0037 baseline at tl30/ask≥0.95, all-coin + LOCO positive, permutation p=0.002. NOT deployable yet (Wilson-LB>be hangs on a 1-loss subset; ~25h data). **PRE-REGISTERED for an OOS re-test on ≥2–4 weeks more data** (see memory b-riskfilter-preregistered); live_runner GATED. `experiment_b_component.py`.
- ~~C. Basket-divergence SMT~~ — **merged into B** (B is the scan-and-compare divergence)
- **G. Order-flow imbalance (OFI / queue) nudge** — 🔴 TESTED (first time): snapshot QI is contemporaneous; 6-coin pooled corr(resid) +0.010 (CI incl 0); SOL/XRP negative net. Dead-AS-PROXY. Only reopener = true event-level OFI from book_events deltas (unbuilt).
- **H. Digital-option fair-value benchmark** — 🔴 CLOSED: market Brier beats fair on every coin; pooled corr(signal,resid) −0.018 (CI incl 0); lone BNB positive is in-sample artifact. Fair loses at every horizon 60–270s.
- **D. Settlement-basis edge (Chainlink vs Binance)** — 🔴 DEAD: ~4.1% flips; the boundary Chainlink-lean (88%) is a last-second artifact (decays to ~58% at 120s), tradeable category only 3–7%, residual trade loses net −0.06. Only reopener = a FREE Chainlink replica from exchange feeds.
- **E. Maker-rebate harvesting at the tails** — 🔴 ruled out standalone; keep rebate as a capped +term in net_ev. Re-verify live rebateRate=0.20 (per-fee vs per-notional) before encoding.
- **F. Multi-coin as a measurement multiplier (meta)** — 🟢 ADOPT, but power OVERSTATED: ~1.5 effective coins for market-wide edges (not 2–3×); ~6× only for idiosyncratic edges (B) → F pairs best with B.

## Pre-registered candidates (real direction, params LOCKED, awaiting OOS on more data)
> **RIGOR PASS 2026-06-25 (see `POSTMORTEM.md`):** all of these FAILED the deflated, cluster-robust re-test.
> **Peer-surge / after-recovery reversion: RETIRED** (re-run flipped to net-negative, deflated p=1.0 — the
> "+0.03 borderline" was best-of-N noise). **B risk-filter: dying** (locked OOS validator returns NOT VALIDATED,
> gated EV −0.0017, 8 losers<30). **Spike-gated fade: INSUFFICIENT** (n=18) — its ONLY remaining status is
> "blocked on data"; prior is now LOW it survives (both reversion siblings regressed negative on doubled data).
> Do NOT believe any of these without a *deflated* pass at n_loss≥30. The base they sit on (favorite-tail) is
> net-negative, so gating it can't create alpha.
- **Idiosyncratic-spike → spike-gated FADE** 🟡 — premise CONFIRMED (idiosyncratic spot spikes partially mean-revert ~15-20%, all scales, SOL/DOGE strong, BNB none — `analysis/idio_reversion.py`, 5.5yr 1s). The combined test (`experiment_spike_fade.py`): gate the dead fear-fade on the alt's OWN idiosyncratic spot z<-3 → resid **+0.115, EV +0.168, all 4 alts positive** — the predicted "noise spike → token over-reacts → fade pays" signature. **BUT n=18 (~1σ, not significant; Wilson<be; placebo couldn't run).** PRE-REGISTERED (LOCKED: drop≤-0.05/30s, spot z<-3, hl300, buy Up hold-0/1, band 0.20-0.85) → re-run `experiment_spike_fade.py` after ≥2-4 wks more alt-token data (need n≥40-50 w/ losers); promote iff resid stays >0 & >all-dumps & placebo p<0.05 & Wilson-LB>be & cross-coin. Do NOT loosen to chase n. Memory `idiosyncratic-spike-idea`.
- (also: **B risk-filter** `validate_b_riskfilter.py` — see Index B above.)

## Revisit watchlist (parked in `ideas_old/` — re-check when the trigger fires, don't forget)
- **Fear stock-sell (token-vs-token), the FOLLOW flip** — 🟡 PARKED, real-but-fee-capped. FADE (buy Up) is dead (the un-proportionate token dump is *informed*, not fear); FOLLOW (buy Down) has a REAL all-6-coin residual **+0.055** but nets only +0.0195 (placebo p=0.19, Wilson-LB<breakeven) — the ~3.5% fee + ~2¢ Down spread eat it. **TRIGGER → re-run `python ideas_old/experiment_token_fear.py --follow` when:** (1) `n_fired ≳ 1800` (~a few more months of the running collector — the Wilson-LB crosses breakeven there *if* win-rate holds), OR (2) the 5-min taker fee drops / a fee-free maker-Down entry works / Down spreads tighten (gross-of-fee the edge is ~+0.05/$1). **Viable iff Wilson-LB(win)>breakeven AND placebo p<0.05.** Params LOCKED (drop5¢/gap5¢/peer-tol2¢, buy-Down) — no re-tune (overfit trap). Full writeup: `ideas_old/fear-stock-sell.md`.

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

**Refinement (user 2026-06-23):** D is a **correctness** edge, NOT a speed edge — Chainlink is
*downstream* of the exchanges (it aggregates them), so it's structurally SLOWER than Binance;
you can't gain speed from it. The free way to get D's benefit: **replicate Chainlink's
settlement value ourselves from the free exchange feeds** (its published methodology) rather
than buying the gated stream — gives the settlement-correct value as fast as the exchanges, for
$0. **No paid streams** (a paid edge would already be standard). The separate *speed* edge =
direct exchange WS (Binance perp / multi-venue), also free — tracked under the guiding principle
+ [[faster-feed-lag-is-real]].

**Decision (2026-06-23):** pursue D **free only** (replicate Chainlink from exchange feeds, or a
free on-chain read), never paid. **Gate on the disagreement-rate** (`our_outcome` Binance vs
`resolved_outcome` Chainlink — how often they differ = the whole opportunity size); if ~0%, drop
D. Frame as a small *contributor* edge (per the guiding principle), concentrated in coin-flip
boundary windows. Testing deferred until more data.

## E. Maker-rebate harvesting at the tails

**Status:** discussed 2026-06-23 → **ruled out as a standalone strategy**; the rebate survives
only as a small additive term. (Discussion-only; no test needed — the kill is structural.)

**The idea was:** makers pay 0 fee + earn a rebate, so rest limit orders to collect rebates +
benign fills, specifically at the **extremes** (deep favorites ~0.95 / longshots ~0.05) where
informed/toxic flow — and thus adverse selection — is thinnest.

**Why it dies (structural, quantified):**
1. **The rebate uses the SAME fee curve:** `rebate_equiv = C·feeRate·p·(1−p)`. So it is LARGEST
   at p=0.50 and **→0 at the tails**. Best-case (you = all maker volume, crypto 20% share):
   ~0.7% of stake at 50/50, **~0.07% at p=0.95**. So "rebate at the tails" is self-defeating —
   the rebate is **biggest exactly where toxicity is worst (50/50)** and **negligible exactly
   where toxicity is low (the tails)**. The two desiderata are anti-correlated by the formula.
2. **Even at 50/50 the rebate (~0.7%) is dwarfed by adverse selection** (the passive branch
   lost ~−0.3 to −0.6 EV/fill). The rebate can't offset it. (Confirmed: [[deep-research-verdict]],
   [[exit-execution-verdict]].)
3. **Rebates LOWER fill rates** (NASDAQ pilot: 3.65%→14.86% when the subsidy was removed) — and
   the rebate is **pro-rata by filled volume**, so resting-for-rebate fills rarely → earns little.
4. **Adverse selection persists at the tails** (winner's curse): a resting buy at 0.95 fills
   exactly when the favorite is about to crater → −95%. Brutal asymmetry, thin rebate.
5. **Pro-rata pool favors big MMs** — retail's share of the 20% pool is crumbs.

**What survives (per the edge-stacking principle):** don't *farm* rebates, but **include the
rebate as a small `+` term in `net_ev` for any maker leg we'd take anyway** (e.g., the
maker-rest exit in idea A). It's a marginal contributor, not a strategy.

**Decision:** ruled out as standalone. Keep `+ maker_rebate(p)` in the net-EV for maker fills
(small). No separate test.

## F. Multi-coin as a measurement multiplier (meta)

**Status:** discussed 2026-06-23 → **ADOPT as the standard evaluation methodology** (it's not a
strategy — it's how we test the others). Discussion-only.

**What it is.** Not a trading edge — a force-multiplier on *evaluating* edges. Six coins sharing
the same structure (same MMs, same fee curve, same 5-min mechanic) let us test any candidate
edge on **six markets at once**.

**Why it matters — it attacks our #1 chronic problem.** Every result this project produced was
underpowered / overfit-prone on thin data ("need weeks not days"). Multi-coin helps two ways:
1. **More samples / tighter CIs** — ~6× windows per unit time ⇒ confirm a marginal edge faster.
2. **Cross-coin replication = overfit guard** — an edge on BTC but NOT the other 5 is noise; an
   edge consistent across all 6 is structural. This is the strong, out-of-sample-like test we've
   lacked (the discipline lessons: sweeps overfit, ±0.05 is the noise band).

**Honest caveat — coins are CORRELATED (~0.64), so 6 ≠ 6× independent.** Effective sample < 6×:
- *Market-wide* edges (direction/latency): coins highly correlated ⇒ little extra independent
  info (effective maybe ~2–3×).
- *Idiosyncratic* edges (idea B's divergence, by definition the non-common part): coins more
  independent ⇒ bigger multiplier. **So F pairs BEST with B.**
Also coins differ (liquidity/spread/vol/price-scale) ⇒ pooling assumes a homogeneity that may
not hold; per-coin estimates guard against it.

**How to apply (standard from now on):**
- Every edge test reports **PER-COIN + POOLED**; an edge must **replicate across coins** to be
  believed.
- **Respect correlation:** cluster CIs by **TIME** (same-time windows across coins are
  correlated), not just by coin; estimate effective N from the outcome correlation.
- It **amplifies measurement, doesn't create edge.**

**Decision:** adopt as the evaluation framework for B/D and any future idea. No standalone test.

## G. Order-flow imbalance (OFI / queue imbalance) directional nudge

**Status:** proposed from the strategy survey (2026-06-23), discussion-only. Honest prior: WEAK,
a candidate small contributor at best.

**What it is.** The best-evidenced short-horizon *direction* signal in the microstructure
literature: order-flow imbalance (OFI), best-bid/ask **queue imbalance**, bid-ask spread, and
VWAP-to-mid deviation. Canonical model: price move ≈ OFI / depth (linear, slope ∝ 1/depth;
multi-level book adds info with diminishing weight by distance from the spread).

**Translate to us.** Compute OFI/queue-imbalance on the **Polymarket CLOB** (`book_events`) and/or
the **underlying exchange** (`btc_ticks`/book) as a small probability nudge for the binary
outcome — then the residual test (does it beat the quote?).

**Why it's weak here (honest).** (a) The OFI→price relation is **contemporaneous, not forward-
predictive** — to use it predictively you need a lead (our ~1s exchange→quote lag is the only
candidate, and the latency-taker is already ~breakeven). (b) Net-of-fee taker edge was
significant **only on small-caps, NOT on BTC/LTC** (p≈0.75) — our coins are large-cap. (c) The
on-point 5-min crypto paper: weak, non-significant, negative net Sharpe.

**Test (deferred).** Engineer the universal feature set per coin (OFI, spread, VWAP-to-mid,
queue-imbalance); **simple logistic** regression to P(up); residual `corr(signal, outcome−price)`,
**per-coin coefficients**, purged/embargoed walk-forward CV, cross-coin replication (F).
**Decision:** keep as a low-priority candidate contributor; expectations low on large coins.

## H. Digital-option fair-value benchmark

**Status:** proposed from the survey (2026-06-23); largely ALREADY built/tested.

**What it is.** Each market IS a short-dated **digital option**; a principled fair `P(up)` =
`Φ((S−K)/(σ√T))` (drift≈0) — exactly what `analysis/fairvalue.py` computes — gives a fair-value
benchmark to trade the residual `quote − fair` against. (Formal: digital = limit of a tight
call spread; ATM-near-expiry is a known-hard region.)

**Status of evidence on us.** Already tested (`analysis/fair_vs_market.py`): the market is
**efficient** w.r.t. this fair value (residual corr ≈ −0.03). So H is mostly a *closed* check,
not a fresh edge. The survey's one wrinkle: examine the residual **away from ATM-near-boundary**
(where the model is least stable but also least informative for the quote) and consider a
**probability-of-touch / barrier** refinement. **Decision:** low priority; re-look only as a
regional refinement / sanity benchmark, not a standalone edge.

## Research methodology guardrails (from the strategy survey)
Apply to ALL idea tests (reinforces F + the discipline lessons):
- **Simple linear/logistic combiners, NOT GBM/deep nets** — flexible ML overfit catastrophically
  on weak short-horizon crypto signals (OOS R² −11%, significant in the WRONG direction).
- **Purged + embargoed walk-forward CV** (no leakage).
- **Per-coin coefficients** (microstructure alpha does NOT transfer across coins) but the **same
  feature set** replicates (per F).
- **Always the residual test** (`outcome − market_price`), with **cross-coin replication** as the
  overfit gate. Every "profitable" result in the literature was continuous-P&L on perps; none
  tested the binary residual we need.

## Testing phase plan (PAUSED 2026-06-23 — resume when multi-coin data ≥ ~24h)

Idea pass A–H complete; now waiting for the databases to grow. On resume, in order:
0. **Dedupe pass** — drop exact-duplicate `snapshots`/`btc_ticks` rows per coin (the
   double-supervisor episode left dupes; 123% coverage) so count-based analyses are clean.
1. **B1 re-run on ≥24h** — add the **per-coin** convergence breakdown AND read the **SIGN**
   (convergence `+` vs seesaw/reversal `−`, per the survey). Decide if the cross-asset gap is
   informative and which direction.
2. If B1 positive → **B Part 3** (gap vs the QUOTE = is it unpriced?) → **B2** net-of-spread
   taker sim using the idea-A `net_ev` (maker-rest-or-hold exit; taker-entry fee).
3. **D disagreement-rate sizing** — `our_outcome` (Binance) vs `resolved_outcome` (Chainlink);
   gate D (drop if ~0%).
4. **G** (low priority) — OFI/queue-imbalance residual test (simple logistic, per-coin, purged CV).
All under the methodology guardrails + the edge-stacking lens (small additive contributors).

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

**Research update (2026-06-23, strategy survey wf_28066528-bb1):** the academic analogue of
cross-asset SMT is the crypto **"seesaw effect"** — a *NEGATIVE* intraday lead-lag (large coins
*negatively* predict others at 5–10 min). Two consequences: (i) **the SIGN may flip** — B's
"convergence" (laggard catches up, +) could actually be **reversal** (laggard goes the other
way); B1 measures the real sign, so this is settled empirically, not assumed. (ii) **Epps
headwind** — cross-crypto correlation is *weakest* exactly at 5-min. The "survives transaction
costs" extension was REFUTED → genuine but FRAGILE. REFINEMENT: replace the raw %-gap with a
**copula relative-value** measure (`h^{1|2}` vs 0.5 = which coin is rich/cheap vs peers) — more
principled (Tadi & Witzany 2025; profitable as a continuous 5-min perp spread, untested as a
binary residual).

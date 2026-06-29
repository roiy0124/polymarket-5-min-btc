# RESEARCH-PLAN-FIELDS.md — the field-by-field deep-research program (the "clear planned goal")

**Created 2026-06-28, to be executed AFTER a `/compact`.** A structured, multi-phase deep-research program that
attacks the wall by studying the broad ACADEMIC/PRACTITIONER FIELD behind each "string" of the maker's formula,
broad-first then subtopic-by-subtopic, deciding for each whether it has potential to break the wall.

## The goal
The maker's quote is `up_mid = Φ( ln(spot/strike) / (σ·√t) )`, settled on Chainlink, with a spread/over-round
overlay and a taker fee. We've walled every *direct* attack (directional, microstructure, σ, drift, maker-side).
This program zooms OUT: each component of the formula belongs to a broad FIELD with its own literature and
frontier. We deep-research the fields systematically to find a subtopic / result we haven't applied that could
break the wall — gating every candidate through `analysis/stats.assess` + the second-mind, honestly.

## The map — each string → its broad field
| # | formula string | broad FIELD | what it relates to | prior coverage |
|---|---|---|---|---|
| **A** | `Φ` + the digital-option FORM | **Option-pricing theory & probability** | risk-neutral pricing, Black-Scholes-Merton digitals, the Gaussian/log-normal assumption vs **jump-diffusion / stochastic & local vol / rough vol**, **model-free option-implied densities** (Breeden-Litzenberger), tail/skew pricing | barely covered → **connects to the live model-form/skew seam** (maker_behavior §10) |
| **B** | `σ` (the one free input) | **Volatility modeling & forecasting** | realized vs implied vol, **GARCH/HAR-RV/rough vol**, the **variance risk premium**, vol-of-vol, vol term structure, vol forecasting skill | partial — σ-lag (latency), VRP (self-priced) walled |
| **C** | `spot`, `strike`, price formation | **Market microstructure & price discovery** | order-flow imbalance, **Kyle / Glosten-Milgrom**, latency arbitrage, cross-venue lead-lag, EMH and its micro-violations | heavy — **all walled** (efficient-on-knowledge) |
| **D** | `t` (time decay) | **Option time-decay & the short-dated / 0DTE regime** | theta/gamma, the **0DTE literature**, intraday vol seasonality, calendar & term-structure arbitrage, near-expiry dynamics | partial — Topic 1 (term-structure, nested-arb) |
| **E** | settlement → outcome | **Oracle design & settlement mechanics** | Chainlink Data Streams / DON median, **oracle aggregation**, OEV/MEV, stablecoin (USDT/USD) basis, settlement-source mismatch | partial — Topic 2; **Thread B (the one open thread)** |
| **F** | spread / over-round / inventory | **Market-making theory & adverse selection** | **Avellaneda-Stoikov inventory**, Glosten-Milgrom adverse selection, optimal MM, **bid-ask spread decomposition**, liquidity-provision economics | partial — Topic 3 (rewards unfunded) |
| **G** | binary payoff + fee | **Prediction-market efficiency & betting economics** | **Grossman-Stiglitz**, favorite-longshot bias, Kelly sizing, deflated-Sharpe / multiplicity, betting-market (in)efficiency | partial — Topic 3; the fee = the wall |

## Phase 1 — research the BROAD FIELDS (understand them, broad-first)
For EACH field A–G, run a deep-research pass (the deep-research workflow) that answers, at the FIELD level (not yet
our market): What is this field's core object & canonical results? What is its current FRONTIER / open problems?
What other fields does it connect to? Where in this field do *retail-accessible* inefficiencies historically live?
**Output: a one-page "field brief" per field** appended to `RESEARCH-EXTERNAL.md` (Phase-1 section). NO trading
claims yet — just map the terrain. Group/parallelize sensibly; ~7 field briefs.

## Phase 2 — research the SUBTOPICS, assess wall-breaking potential
For each field, enumerate its subtopics (from the Phase-1 brief). For each promising subtopic, run a focused
deep-research pass and DECIDE: could this subtopic break OUR wall on the 5-min Chainlink-settled binary, given what
we've already walled? Tag each subtopic: **DEAD** (already-walled / inapplicable) · **DATA-GATED** (real but needs
data we lack) · **TESTABLE** (could test now on our data → promote to an experiment). Every TESTABLE candidate is
then built + gated through `analysis/stats.assess` (n_loss≥30, deflated, cluster-bootstrap) + the joint-control +
the **second-mind** adversarial refutation, with a pre-committed KILL. Honest verdicts; archive dead ones in
`dead_ends/`, real ones in `winning_strategies/`.

## Execution order (priority)
1. **A — option-pricing FORM** first (highest potential: it owns the live skew/model-form seam, the one new lead;
   model-free implied densities / non-Gaussian digital pricing is the least-covered field).
2. **F — market-making theory** (the maker's own discipline; may reveal a maker-behavior subtopic we missed).
3. **B — volatility** (refine the σ frontier: rough vol, vol-of-vol, conditional skew).
4. **D, E, G** — refresh/extend the already-partly-covered fields (Topics 1–3) at the subtopic level.
5. **C** — last (most thoroughly walled).

## Method & discipline (standing)
Deep-research workflow per field/subtopic (fan-out → fetch → 3-vote adversarial verify → synthesize). Gate every
wall-breaking claim against our walls + `stats.assess`; run the second-mind; be honest (a clean kill is a result);
document in `RESEARCH-EXTERNAL.md`; commit per field. The maker is near-perfect on its own market — the bar is a
subtopic that gives us a component the maker computes WRONG or an information set it lacks, that survives the fee.

## How to resume after `/compact`
Read this file + memory `field-research-program` + `RESEARCH-EXTERNAL.md` (Topics 1–3 already done) + `maker_behavior.md`
§10 (the skew seam). Then START Phase 1, Field A. The two live on-market leads going in: **Thread B** (data-gated)
and the **model-form/skew residual** (testable now — likely the first Phase-2 experiment out of Field A).

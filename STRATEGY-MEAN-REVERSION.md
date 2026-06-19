# Mean-Reversion / Liquidity-Provision Strategy — Research Assessment

Cited assessment of the user's "buy the overshoot at ~0.22, sell the reversion at
~0.33 before resolution" idea. From a deep-research pass (2026-06-19): 22 claims
3-vote verified, 3 refuted. (The workflow's auto-synthesis hit a session cap, so
this synthesis is hand-written from the verified claims.)

## Verdict (read this first)

**The mechanism is real, but the strategy faces two strong, documented headwinds,
and one variable decides whether it works.** It is NOT a free lunch — and the
naive "it reverts 90% of the time" framing is exactly the trap the literature
warns about.

- ✅ **The reversion MECHANISM is documented.** Market makers set price *below*
  fundamental value to absorb sell imbalances; unwinding produces a positive
  expected return that shows up as negative return autocorrelation — i.e. a
  *liquidity-provision reversal premium* [SSRN 2275982]. Forced block sells create
  a **temporary** price impact that **reverses** after the trade completes,
  distinct from permanent (informed) impact [Kyle–Obizhaeva]. So "provide
  liquidity to a forced seller, capture the bounce" is grounded in real theory.
- ⚠️ **Headwind 1 — short-horizon prediction markets lean efficient / underreact,
  not overreact.** Real-time prediction-market prices *underreact* to news
  (Kalshi: a 1-min change in true win-prob moves the midpoint only ~0.64-for-1)
  [arxiv 2606.07811]. Crypto-prediction-market calibration slope is ~1.0 near
  resolution (≈efficient). Buying depressed long-shots is, on average, a **losing**
  proposition before any reversion edge (OTM index options get progressively worse
  expected returns the further OTM) [SSRN 424421], and the favorite-long-shot bias
  is **weakest near resolution** [arxiv 2602.19520]. ⇒ **Don't assume 0.22 is "too
  cheap" — it may simply be fair.**
- ⚠️ **Headwind 2 — adverse selection of limit fills ("negative drift").** This is
  the big one. Limit fills are **non-random**: you get filled precisely when price
  moves against you. Conditional on a buy fill, subsequent mid-price drift is
  **significantly negative** (a random control sample shows ~zero drift)
  [arxiv 2407.16527]. The hidden cost ≈ **half a tick per fill** — so resting
  orders do *not* cleanly "save the spread." Adverse fills are *mechanically
  inevitable*: if price trades through your level, you're filled at a now-worse
  price [arxiv 2409.12721]. **Backtests that model price and order flow
  independently systematically understate adverse fills and overstate edge.**
  ⇒ Your "90% reverts" is the **unconditional** rate; the rate **conditional on
  actually getting filled on the way down is worse**.
- 🎯 **The decisive variable: can you separate non-informational (panic/forced)
  flow from informed (toxic) flow?** Order flow is "toxic" when it adversely
  selects makers; the reversal premium only exists for *liquidity-driven* selling
  [VPIN / quantresearch.org]. Reversals are ~6× larger around information events
  [SSRN 2275982] — context matters. **If you can filter toxic flow, the edge can
  survive; if you can't, adverse selection eats it.** This is the make-or-break
  test.

## What changes in the test plan (vs the naive version)

1. **Measure the CONDITIONAL reversion, not the unconditional one.** The number
   that matters is `P(price reaches 0.33 before window end | a buy actually filled
   at 0.22 on the way down)` — not `P(price touched 0.22 → later touched 0.33)`.
   Use the published **stopping-time / "spatial setup"** efficiency test (regress
   on quotes sampled when the price first hits a bound) to handle this selection
   bias correctly [MDPI 2227-9091].
2. **Null hypothesis = martingale** (last quote is the best predictor of the
   outcome; earlier quotes insignificant). The edge only exists if you can
   *reject* this [MDPI 2227-9091].
3. **Build a flow-toxicity filter as the entry gate.** Compute trade-sign
   imbalance / trade size / arrival speed / VPIN-style bucketed volume imbalance
   from `trades` + `book_events`; compare reversion conditional on **low- vs
   high-toxicity** flow. Only low-toxicity (panic) dips should bounce.
4. **Model fills WITH adverse selection.** Use the RiskAverse queue fill (fill only
   after volume clears the size ahead) and subtract the empirical negative-drift /
   ~half-tick cost. Never assume a fill is a clean win.
5. **Size for negative skew.** Loss is ~2× the win and fat-tailed; penalize with
   the **Deflated Sharpe Ratio** (skew/kurtosis terms) and use **fractional Kelly**.
6. **Control the number of trials.** Every entry-price / exit-target / time /
   toxicity-filter combo you try inflates the expected max Sharpe even at zero true
   edge — the single most important thing to track. Use DSR / PBO [SSRN 2460551].

## Refuted (for transparency — do NOT rely on these)
- "Prediction-market prices show 5–15 min momentum continuation" — **refuted (1-2).**
- "Crypto prediction markets are perfectly calibrated (slope ≈1.0) at short
  horizons" — **refuted (1-2)** (so don't assume *perfect* efficiency either; the
  truth is in between — which is *why* it must be measured on our own data).
- "VPIN computes toxicity without parameter optimization, usable as a real-time
  filter" — **refuted (1-2)** as stated; treat VPIN as one candidate filter to
  validate, not a guaranteed tool.

## Leads worth reading (found but not independently verified here)
- **Quantpedia — "Exploiting Mean Reversion in Decentralized Prediction Markets:
  Evidence from Polymarket Binary Contracts"** — directly on-point; read first.
- benjamin.bigdev (Medium) — Polymarket 5-min last-second dynamics & bot strategies.
- laikalabs.ai — prediction-market biases / how to exploit.

## Key sources
- Liquidity-provision reversal premium: https://www.wallstreethorizon.com/upload/SSRN-id2275982.pdf
- Temporary vs permanent impact (overshoot-revert): https://pages.nes.ru/aobizhaeva/Kyle_Obizhaeva_metamodel.pdf
- PM underreaction (Kalshi): https://arxiv.org/html/2606.07811
- PM efficiency / stopping-time test: https://www.mdpi.com/2227-9091/9/2/31
- Favorite-longshot in options: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=424421
- Longshot bias vs horizon: https://arxiv.org/pdf/2602.19520
- Limit-fill negative drift / adverse selection: https://arxiv.org/pdf/2407.16527 · https://arxiv.org/html/2409.12721
- Order-flow toxicity / VPIN: https://www.quantresearch.org/From%20PIN%20to%20VPIN.pdf
- Deflated Sharpe / backtest overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Polymarket mean-reversion (lead): https://quantpedia.com/exploiting-mean-reversion-in-decentralized-prediction-markets-evidence-from-polymarket-binary-contracts/

## Bottom line for the A/B build
This does NOT kill your idea — it sharpens it. The reversion premium is real for
non-toxic flow; the whole game is (a) measuring reversion **conditional on fill**,
and (b) **filtering out informed flow**. Build it on the shared harness (see
ANALYSIS.md) alongside the digital-option fair-value strategy, with the
adverse-selection-aware fill model applied equally to both, and let the
walk-forward + DSR scoreboard decide.

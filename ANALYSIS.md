# Analysis & Backtest Methodology Blueprint

A cited methodology for finding and validating a **resting-limit-order edge** in
Polymarket "Bitcoin Up or Down" 5-minute binaries, using the data this project
collects. This is the plan for the (future) analysis layer — not yet implemented.

Source: deep-research pass (2026-06-19), 110 agents, 24/25 claims 3-vote verified.

> **The single most important caveat — read first.** Almost every *magnitude* in
> the literature below (OFI R² of 33–86%, queue-imbalance classification gains of
> 50–60%, micro-price superiority) comes from **equities** (NYSE/Nasdaq/CSI 500)
> or generic crypto LOBs — **not** Polymarket binary outcome tokens. The model
> **forms and signs transfer; the coefficients do not.** Treat every cited number
> as a *hypothesis to re-validate on our own SQLite data*, never as a guaranteed
> edge. Second caveat: our BTC price is a **Binance/Pyth proxy** for the gated
> Chainlink settlement feed — measure how much apparent edge is just proxy *basis
> risk* at the window boundary before believing any microstructure edge.

---

## The six layers

### 1. Fair value — price each window as a digital option
Over a ≤5-min horizon with near-zero drift, **Bachelier (arithmetic BM) and
Black–Scholes-digital are interchangeable** (the convexity term `σ²T/24` is
negligible at `T ≈ 5min`). Theoretical probability of Up:

```
P(Up) = N(d),    d = (S - K) / (σ · √T)
```
where `S` = current BTC price, `K` = strike (price at window start), `T` =
time-left (in years), `σ` = short-horizon volatility, `N` = standard normal CDF.
- **σ estimate:** baseline = **5-minute realized volatility** (Andersen–Bollerslev;
  Liu–Patton–Sheppard "Does anything beat 5-min RV?" — little does, across ~400
  assets). With our ~78 tick/sec BTC feed you can do better — **realized-kernel /
  pre-averaging** estimators — so 5-min RV is a *conservative baseline*, not the ceiling.
- **Edge = market implied prob (Up mid-price) − this fair value P(Up).**
- Refs: Bachelier↔BS [arxiv 2104.08686]; 5-min RV [Concordia MSc 2025]; applied
  Polymarket example [dev.to "Black-Scholes on Polymarket"].

### 2. Microstructure signals (compute from `book_events` + `trades`)
- **Order-Flow Imbalance (OFI)** — Cont–Kukanov–Stoikov: over short intervals
  price change is mainly driven by a single signed measure of best-quote order
  flow. `ΔP = β·OFI + ε`, with **β = c/AD ∝ 1/depth** (thinner book ⇒ bigger
  moves; `AD` = avg best-quote depth, available from top-10 depth). A stationarized
  **log-GOFI** variant scores higher OOS. [SSRN 1712822; arXiv 2112.02947]
- **Micro-price** — Stoikov: mid adjusted for spread + imbalance
  `I = Vb/(Vb+Va)`; it is a **martingale by construction** (weighted-mid is not),
  and beats mid/weighted-mid for short-horizon prediction. [SSRN 2970694]
- **Queue/book imbalance** `I = (nb−na)/(nb+na) ∈ [−1,1]` — positively predicts
  the next mid-move; fit with **logistic regression read directly as P(up | I)**.
  Gains are largest for *large-tick* instruments — and our 0.01-tick-on-[0,1]
  binary is large-tick-like, so the stronger regime *may* apply. [arXiv 1512.03492]
- Caveat: the imbalance effect is **weak and decays in seconds**, often below
  transaction costs — qualifies exploitability, not existence.

### 3. Fill-probability modeling (queue position is unobservable — model it)
The public feed gives aggregate size per price level, not per-order ordering, so
fill probability **must be modeled**. Reference models (hftbacktest, which is
Market-By-Price like Polymarket's CLOB):
- **RiskAverseQueueModel** — fills your resting order **only after cumulative
  trade volume clears the size that was ahead of it**; cancels assumed at the
  tail. Most conservative ⇒ use as the **lower bound**. [hftbacktest order_fill]
- **ProbQueueModel** — advances queue position probabilistically (decreases
  happen partly ahead, partly behind); variants Identity/Square/Power/Log.
- **NautilusTrader `prob_fill_on_limit`** (0 = back/never-at-touch, 0.5 = middle,
  1.0 = front) — a single-knob sensitivity range bracketing the conservative bound.
- **Validate** the chosen model against our actual `trades` prints.
- Use **full `book_events` (L2/L3-equivalent)** for fills, not snapshot mids —
  real depth determines impact; L1-only sims must *fake* slippage. [NautilusTrader]
- **REFUTED (0-3):** you *cannot* recover true queue position by replaying
  synthetic infinitesimal orders against the event stream — stick to modeled fills.

### 4. Adverse selection — the maker's dilemma
A resting order tends to fill **precisely when the market is about to move against
it** — acutely near the resolution boundary where info arrives fast. Measure with
**markout / post-fill price drift** at fixed horizons (e.g. mid at fill vs mid
+5s/+30s). Subtract it so the backtest doesn't overstate edge. *(Markout method
needs a primary cite added — see Gaps; databento/markout is a starting reference.)*

### 5. Backtest rigor (passive maker)
- Realistic fill sim from `book_events` (§3); **no look-ahead**.
- Model **fees, $5 min order, 0.01 tick, and maker rewards** (`rewardsMinSize` /
  `rewardsMaxSpread` per market).
- **Walk-forward / out-of-sample**; correct for data-mining across the many
  feature combinations you'll test: **Deflated Sharpe Ratio** + **CPCV / purged
  cross-validation** (López de Prado). [deflated-sharpe.pdf; Purged CV]

### 6. Calibration, significance & sizing
- **Is the market implied prob calibrated** vs realized Up frequency? Reliability
  diagrams, **Brier-score decomposition**, log-loss. Hunt for **favorite-longshot
  bias, theta/time-decay patterns, end-of-window/last-second dynamics**.
- **Significance:** hypothesis-test win rate vs break-even-after-fees; size the
  sample for the target power.
- **Sizing:** **fractional Kelly** for binaries; check **risk of ruin**.
- **Joint fill+edge:** queue depth imbalance `QI=(Q_near−Q_far)/(Q_near+Q_far)`
  also predicts fill probability/speed (negative QI ⇒ fills faster) — lets you
  model edge and fill together. [Maglaras–Moallemi–Wang, Quant Finance 2022]

---

## Suggested build order (each step is independently useful)

1. **Panel builder** — reconstruct the book at each second from `book_events`;
   compute mid/microprice/spread/depth/imbalance; join `strike`/`final`/
   `resolved_outcome`. Compute fair-value `P(Up)` per tick (§1).
2. **Calibration study (do this FIRST — needs no fill model)** — is the Up
   mid-price calibrated to realized outcomes? Reliability diagram + Brier. Look
   for favorite-longshot / time-decay / last-30s effects. *This directly reveals
   whether and where mispricing exists.* (§6)
3. **Proxy basis-risk check** — how well does Binance/Pyth track the settlement at
   window end? Quantify before trusting any boundary edge. (open question)
4. **Signal study** — OFI / imbalance / microprice vs subsequent move & outcome;
   logistic fit; strict OOS. (§2)
5. **Fill model** — RiskAverse lower bound + Prob range; validate vs `trades`. (§3)
6. **Maker backtest** — signal × fill × adverse-selection × fees; walk-forward;
   deflated Sharpe / CPCV. (§4, §5)
7. **Sizing** — fractional Kelly + risk of ruin. (§6)

## Gaps / TODO citations (not nailed down this round)
- Adverse-selection markout methodology (sub-Q4) — add primary cite.
- López de Prado toolkit specifics (deflated Sharpe, CPCV) — add cites.
- Prediction-market calibration tooling + favorite-longshot evidence (sub-Q6).
- Sample-size / fractional-Kelly / risk-of-ruin math (sub-Q7).
- *(Several of these are already covered by the `trading-strategy-knowledge`
  skill in the parent environment.)*

## Polymarket-specific reading (blog-quality, unverified — read critically)
- "Unlocking edges in Polymarket's 5-minute crypto markets: last-second dynamics,
  bot strategies" [medium @benjamin.bigdev]
- "AI-augmented arbitrage in short-duration prediction markets — live trading of
  Polymarket" [medium @gwrx2005]

## Key sources
- Bachelier vs BS digital: https://arxiv.org/pdf/2104.08686
- 5-min realized vol: https://spectrum.library.concordia.ca/995904/1/Sarrafshirazi_MSc_F2025.pdf
- OFI: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822 · https://arxiv.org/pdf/2112.02947
- Micro-price: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694
- Queue imbalance: https://arxiv.org/pdf/1512.03492
- Fill models: https://hftbacktest.readthedocs.io/en/py-v2.1.0/order_fill.html · https://nautilustrader.io/docs/latest/concepts/backtesting/
- Fill-prob via depth imbalance: https://business.columbia.edu/sites/default/files-efs/citation_file_upload/deep-lob-2021.pdf
- Deflated Sharpe: https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Purged CV: https://en.wikipedia.org/wiki/Purged_cross-validation

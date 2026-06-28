# RESEARCH-EXTERNAL.md — literature / others'-approaches research log

Deep, adversarially-verified web research on what OTHERS do to exploit oracle-settled short-dated binary /
prediction markets, run topic-by-topic (each via the deep-research workflow: fan-out search → fetch → 3-vote
adversarial verify → synthesize). This is DISTINCT from our own experiments (those live in `EXPERIMENTS.md` /
`POSTMORTEM.md`). Every conclusion here is gated against our own walls before belief. Verdicts are honest.

---

## Topic 1 — Term-structure / nested-market arbitrage & cross-market consistency (2026-06-28)

**Question:** do Polymarket's nested crypto Up/Down durations (5m ⊂ 15m ⊂ hourly) price consistently under
no-arbitrage; is there a term-structure / calendar / vol-term-structure edge a retail quant could exploit?

**Verdict: NO clean new taker edge.** 104 agents, 25 claims verified, 15 killed. The one genuinely-new angle
(vol-term-structure richness) collides with our already-walled maker-adverse-selection corner.

### Verified findings (survived 3-vote adversarial verification)
1. **No static nested-arbitrage.** "Up over the hour" (`final_60 ≥ strike_0`) is NOT the product of per-window
   ups — path-dependence + each sub-window has a DIFFERENT strike (the prior close). The only rigorous no-arb
   object is the **subset inequality** (a narrower event prices ≤ a broader one), verified on Polymarket NBA
   markets (arXiv 2605.00864): real but **tiny (~101bp median), fleeting (median 16s), capacity-bounded
   (~$15/episode)** — and it does NOT cleanly transfer to time-nested crypto windows (different strikes).
2. **Vol-term-structure / VRP (the one NEW angle):** short-dated options/0DTE carry a structurally **negative
   variance risk premium** and are systematically **rich (~0.75–1.0 vol pts)** (Carr-Wu 2009; Verdad; CBS 0DTE
   study). BUT the edge accrues to the **SELLER of short-dated vol = a fee-free MAKER**, not a taker. The
   tradeable short-straddle extension (Verdad's +Sharpe 0.85–1.4) was **REFUTED (0-3)** → richness is a PRIOR,
   not a proven net edge.
3. **Implied vol from a 5-min quote is jump-contaminated** — the intraday-jump risk premium is ~2× the combined
   diffusion+vol premia (Bozovic 2025, SPXW 0DTE) → a naive constant-/diffusion-vol cross-duration no-arb check
   is structurally unsound.
4. **Calibration is horizon-dependent & transitory:** efficient near open AND near expiry, biased only at
   INTERMEDIATE horizons (Berg-Rietz 2019). In a 5-min market the whole life is near-expiry → the bias window
   may never open. (The competing "crypto perfectly calibrated at short horizons" AND "overconfidence to fade"
   claims were BOTH refuted — assume neither direction.)
5. **Fee model VERIFIED:** docs `fee = 0.07·p·(1−p)` per SHARE = `0.07·(1−p)` per STAKE = exactly `net_ev.py`.
   Symmetric, peaks ~1.75%/shares at p=0.5, ~0.33% at p=0.95. **Our accounting is correct.** Caveat: the
   schedule changed ~Jan–Apr 2026 → re-verify `feeds.fetch_fee_schedule` live before any build.
6. **Multiple durations DO coexist** (5m, 15m confirmed; hourly/daily not corroborated). Testing nesting would
   require ALSO collecting the 15m+ books — we only collect 5m today.

### Refuted (do NOT rely on these)
- The Polymarket-vs-Binance-option cross-venue gap (arXiv 2606.19517: "5.6pp persistent, AR(1) 4h half-life,
  delta-hedged arb profitable") — **refuted 0-3** on the persistence/tradeability. (Pre-empties the obvious
  cross-venue version of Topic 4.)
- Dutch-book "YES prices sum to 1" / combinatorial no-arb as DIRECTLY transferable to time-nested windows — refuted.
- Short-0DTE-straddle as a documented +Sharpe strategy — refuted.

### My critical synthesis (gated against our walls)
The vol-richness finding is **consistent with what we already measured** — the maker IS the vol seller earning
the VRP (it pads σ ~15%). The literature confirms the premium accrues to the *seller/maker*, which on Polymarket
is the adverse-selected corner we walled (maker-in-noise −0.365). So Topic 1 does **not** open a new taker door;
the only source-motivated harness (back out cross-duration implied vol, test a fee-free maker vol-seller net of
adverse selection) needs **new 15m/hourly collection** AND must beat the maker-adverse-selection wall = **low
prior, large build.** Nesting-arb is structurally weak/fleeting/capacity-bounded.

**Actionable:** (a) fee model confirmed correct — no code change; (b) cross-venue-gap refuted — reshape Topic 4;
(c) park the vol-term-structure-maker idea as LOW-priority (needs 15m collection + collides with maker wall).

---

## Topic 2 — Settlement-oracle mechanics & exploitation (2026-06-28) — VALIDATES + bounds Thread B

**Question:** how is the settlement ORACLE exploited in oracle-settled short-dated binaries; what are the exact
Chainlink settlement semantics to encode for our Thread B (maker-prices-Binance / market-settles-Chainlink)?

**Verdict: premise VERIFIED, harness CORRECT, edge BOUNDED (consistent with the wall).** 107 agents, adversarially
verified.

### Verified findings (3-0 unless noted)
1. **Settlement = Chainlink Data Streams BTC/USD, NOT Binance.** Polymarket's own market-page rule (primary):
   "this market is about the price according to Chainlink **data stream** BTC/USD, **not according to other
   sources or spot markets**." Our Thread B premise is fully primary-sourced.
2. **Semantics to encode:** Up iff `final ≥ strike`; **ties (final == strike) resolve UP** ("greater than OR
   equal to"). (Near measure-zero on a high-precision price.) Our harness uses exactly this (label = official
   `resolved_outcome`).
3. **The settled value is the DON consensus MEDIAN** (multi-venue aggregate, int192), pulled off-chain and
   verified on-chain at resolution — so the basis is **Binance(single venue) vs Chainlink-multi-venue-median**,
   NOT a clean USDT/USD two-feed gap. Flips are driven by **Binance-idiosyncratic moves** the median doesn't
   follow → "smaller and noisier than a clean two-feed gap." Our harness (decision-time median vs Binance)
   captures this correctly.
4. **Data Streams v3 = sub-second, schema has second-precision timestamps** (validFromTimestamp /
   observationsTimestamp / expiresAt), int192 DON-median price, simulated bid/ask. The settlement is a sub-second
   pull report — do NOT model it as a stale push value (heartbeat/deviation applies to the *push* aggregator, a
   different feed).
5. **Oracle-sniping / OEV / latency-arb / Synthetix front-running does NOT transfer** (multiple 0-3/1-2 refutals):
   every technique needs a *movable, mempool-observable* stale on-chain price; a one-time settlement SNAPSHOT
   offers none — you can only position BEFORE. No MEV angle; Synthetix is precedent, not transferable technique.
6. **Binding wall (Synthetix's economic law):** an edge needs `fee < exploitable move`. Against our verified
   taker fee and a near-zero/noisy residual, this is the constraint that walls it — consistent with the standing
   verdict. USDT/USD basis ≈ tens of bps, two-sided, largely cancels; the **persistence/AR(1) and depeg-severity
   sub-claims were REFUTED** → do NOT model the basis as a predictable slow drift.

### Refuted / cautions
- The v3 report's bid/ask as a model-able settlement residual — **refuted 0-3** (settlement uses the MEDIAN only).
- Polymarket's exact report-selection at the boundary (which validFrom/observations report settles the snapshot)
  is NOT established by docs — confirm against the resolution contract before encoding boundary logic.
- The crypto stream's exact sub-second cadence (100ms/500ms/1s) is unquantified anywhere.

### My synthesis / actionable
Topic 2 **sharpens** Thread B (settlement = DON median not pure Binance; ties→Up; no-sniping; fee<move is the
wall) and **confirms the harness is structurally right**. It does NOT produce a new edge — it explains WHY the
residual is likely sub-fee. The research's own #1 open question ("is the near-strike Binance-vs-median residual's
tail ever > fee, gated through stats.assess") is *exactly* what `experiment_settlement_basis.py` measures →
**data-gated, unchanged plan.** Encoding confirmations added to the harness docstring.

---

## Topic 3 — How profitable traders ACTUALLY operate + maker-rewards economics (2026-06-28) — THE one open lead

**Question:** what real, documented edges do profitable Polymarket participants use, and (crucially) do
maker-rewards flip the adverse-selected maker to net-positive on the 5-min book?

**Verdict: ONE genuinely-open, on-topic, testable lead — the MAKER-REWARDS SUBSIDY vs adverse selection on the
5-min book — which our prior maker-walls never credited.** Everything else refuted or out-of-scope. 104 agents.

### The lead (verified mechanics, open economics)
- **Maker-rewards program is real + formula-documented (3-0, Polymarket primary docs):** reward score
  `S(v,s) = ((v − s)/v)² · b` (v = per-market max spread, s = distance from the size-adjusted mid, b =
  at-the-money/in-game multiplier). Pays MOST for resting nearest the mid; scales with size; **paid daily in
  cash** (PUSD), $1/day floor, no rollover. Two-sided required (tails strictly; mid-band one-sided penalized by
  c=3.0). Payout is YOUR_score / Σ(all makers' scores) — a **shared pool**.
- **Why it's a real gap in our walls:** rewards pay for *resting/quoting*; adverse selection only bites on
  *fills*. Our maker kills (maker-in-noise −0.365, maker-timemap −0.13..−0.18) measured **fill-conditional** P&L
  — they did NOT credit the daily reward on the (much larger) un-filled resting volume. The at-the-money `b`
  rewards quoting near 0.50, and the 5-min book sits near 0.50 much of the window = structurally favorable.
- **The open question (no source closes it):** does the subsidy EXCEED adverse-selection cost on the 5-min book?
  Testable only with live fills + the live `rewardsConfig` (max-spread v, min-size, c, b, daily pool) per market.

### Verified-but-not-for-us / refuted
- **Profits are hyper-concentrated:** top 1% take 76.5% of profit; ~1,200 users take >half (SSRN 6443103). The
  paper's "makers win, takers lose" is a **population avg over months-long EVENT markets** — does NOT establish a
  5-min ~50/50 maker wins (our adverse-selection finding can co-exist). The pool is shared → pros dilute it.
- **Whale-flow-leads-price: REFUTED for crypto** (the large-trade-order-imbalance result is 2024 ELECTION
  markets only; does not transfer to short-dated crypto). Relevant since the user runs a whale-tracker — it
  does NOT port here.
- **UMA dispute edge: OUT OF SCOPE** — touches only UMA-resolved *event* markets; the crypto Up/Down markets
  resolve automatically via Chainlink, no human dispute. No resolution-layer edge for us.
- **Cross-market / combinatorial arb:** ~$40M extracted but mostly *intra-market* YES/NO rebalancing that the
  matcher collapses for a single binary; cross-market leg ~$95K, sub-100ms bots. Not transferable.
- **Cross-platform (Polymarket vs Kalshi):** real 2-4% deviations but un-nettable / hold-to-resolution
  capital-locked; APYs come from short horizons not mispricing. Tangential.
- **Cross-platform vs options:** BTC threshold "Yes" overpriced 5.6-6.3pp but delta-hedged proxy borderline
  (p=0.053, CI crosses 0) and **long-dated low-prob** contracts — opposite end from our 5-min ~50/50.

**This pre-answers Topic 4** (cross-venue / derivatives lead-lag): its core — the Polymarket-vs-Binance-option
gap and whale/large-flow lead — was refuted here AND in Topic 1; the latency-taker version is our already-walled
edge. A literal Topic 4 would be redundant.

### Decision → the lead is DEAD: the 5-min crypto markets are NOT in the rewards program (verified live)
Before building a feasibility harness I pulled the live `rewardsConfig` from the CLOB. **Decisive kill in one
API call:** for ALL SIX coins' 5-min markets, `rewards.rates = None` — the reward config fields exist as defaults
(`min_size=50`, `max_spread=4.5¢`) but **no daily reward pool is funded.** Control (our reader is correct): other,
funded markets show `rates=[{rewards_daily_rate: 2..3}]` (e.g. "Extended FDV above $3B" pays $3/day) — so the
`None` is real, not a parse error. **There is no maker-rewards subsidy to harvest on the 5-min crypto Up/Down
product**, so the one promising lead from the whole sweep dies on a single fact (no funded pool) — no harness
needed. (Even the funded markets pay only $2–3/day over a shared pool; and `volume24hrClob ≈ $849`, `holdingRewardsEnabled=False`.)
Added `feeds.fetch_rewards(window_start, coin)` so this is RE-CHECKABLE in one call — **re-open the lead only if
`funded` ever flips True.**

---

## Sweep verdict (Topics 1–4)
Four planned topics; Topic 4 (cross-venue/derivatives) was **pre-answered** (cross-venue gap refuted in 1 & 3,
whale-flow refuted, latency-taker already walled). Net result of the external research: **no new exploitable edge
for this product.** The literature *confirms* our own walls (efficient-on-knowledge; fee = price of the edge; the
maker is the vol-seller earning the VRP; makers-win-takers-lose is concentrated in pros on long-dated event
markets) and the one genuinely-new, on-topic lead (maker-rewards subsidy) is **unfunded on the 5-min crypto
markets**. The single open thread remains **Thread B (settlement feed), data-gated** — and the research *validated*
its premise and *sharpened* its encoding without producing a verdict. Durable artifacts added: `feeds.fetch_rewards`
(rewards authority, mirrors `fetch_fee_schedule`), and the verified fee-model reconciliation (our `net_ev` is correct).

---

# PHASE 1 — Field briefs (the field-by-field program; see `RESEARCH-PLAN-FIELDS.md`) — 2026-06-28

Each "string" of the maker's formula `up_mid = Φ(ln(spot/strike)/(σ√t))` belongs to a broad academic/practitioner
FIELD. Phase 1 deep-researched all seven (8-agent workflow, 7 field-research agents + 1 synthesis/critic, ~597k
tokens, 161 web tool-calls). **Terrain only — no trading claims.** Verdict (bottom): the survey surfaced **NO new
wall-breaking angle**; it reconfirms the wall with explicit academic mechanism and sharpens the **two** seams we
already had (skew model-form = TESTABLE; settlement basis = DATA-GATED). Full agent JSON archived in the session
task output `w8m9x585b`.

### Field A — Option-pricing theory & probability (the `Φ` / digital FORM) ★ owns the live seam
- **Core object:** a cash-or-nothing digital = the discounted risk-neutral CDF `e^{−rT}·N(d2)` — a PURE BET on the
  risk-neutral CDF at the strike. Our maker's `Φ(ln(spot/strike)/(σ√t))` is exactly this with r=0 and a single σ:
  the flat-vol, driftless, **symmetric** special case → encodes **zero skew** by construction.
- **The seam equation (load-bearing):** a digital is the strike-derivative of a call, so with a vol smile the true
  price is `D = N(d2)_flatvol − vega·(dσ/dK)`. A symmetric Φ **omits the `−vega·dσ/dK` skew term**. Sign rule:
  negative skew (`dσ/dK<0`) **raises** the digital-call (Up under-priced); positive skew lowers it.
- **Why it's largest at 5 min:** rough-vol (Gatheral, H≈0.1) gives ATM skew `ψ(τ) ∝ τ^{H−1/2} ≈ τ^{−0.4}` — the
  skew term is near its **maximum** at our ultra-short tenor; diffusive models can't generate it. Binary gamma ∝ 1/τ
  and vega flips sign at the strike → the at-the-money near-expiry digital is the single most skew-sensitive object.
- **Measurement instrument:** Breeden-Litzenberger (RND = `e^{rT}∂²C/∂K²`, model-free) / the Deribit 25Δ
  risk-reversal is the market's direct price of the skew the maker omits. Caveat: Deribit's shortest tenor ≫ 5 min →
  extrapolating the skew term-structure down to 5 min is itself a research risk.
- **Seam tag:** the conditional-skew model-form residual = **TESTABLE now** (the one new lead). Caveat from crypto
  evidence: the **sign flips by regime** (crypto *inverse* leverage effect — up-moves can be the violent tail), so a
  causal, real-time, per-coin skew-sign proxy is the make-or-break unknown.

### Field F — Market-making theory & adverse selection (spread / over-round / inventory)
- **Core object:** a maker sets quotes around unobserved fair value; the spread decomposes into order-processing +
  inventory + adverse-selection. Glosten-Milgrom: the spread IS the adverse-selection tax (the theoretical floor
  under our 2-4¢ spread). Kyle's λ: price = fair + λ·orderflow. Avellaneda-Stoikov: reservation price
  `r = s − q·γ·σ²·(T−t)` skews quotes off-mid with inventory `q`, and that skew **collapses as t→T**.
- **Seam:** **over-round asymmetry** (`up_ask+down_ask−1` and up/down ask-vs-mid asymmetry) is the maker's
  *revealed* pricing of asymmetric risk — the most theoretically-motivated maker observable we have, and the
  closest built instrument to the skew seam (`experiment_overround_gate.py`, passed joint-control, loss-light).
- **Reverse favorite-longshot on surprise:** a symmetric quote engine cannot load extra margin onto the tail that
  *just became more likely* from a one-sided move — the F-framing of the same skew residual.
- **Seam tag:** over-round = **TESTABLE** but only as a *conditioning feature/joint-control on the skew candidate*
  (standalone it walks into the G-M spread = the maker's tax; already INSUFFICIENT/fee-capped). Measure loser-Jaccard
  before believing any stack (additivity lesson). Inventory-drift & stale-quote pick-off = WALLED (HFT/self-priced).

### Field B — Volatility modeling & forecasting (the `σ` input) ★ companion to A
- **Core object:** the conditional return distribution's 2nd moment. VRP (implied>realized; BTC ~14% vs S&P ~2%) —
  the premium accrues to the vol *seller* = the fee-free adverse-selected maker. HAR-RV (Corsi) = the SOTA σ
  benchmark; rough vol (H≈0.1) = log-vol rougher than Brownian → fast mean-reversion + the τ^{H−1/2} skew explosion.
- **The single most relevant fact to the skew thread:** the **crypto INVERSE leverage effect** — EGARCH on BTC shows
  positive returns raise vol more (FOMO); the sign flipped ~2016 and is regime-unstable. So the maker's 3rd-moment
  error is **not a fixed sign** in crypto; it can be POSITIVE skew in risk-on. Sign must be measured per regime.
- **Seam tags:** conditional-skew = **TESTABLE** (B supplies the magnitude + sign model for A). Calendar/seasonality
  stale-σ = **DEAD** (σ-lag in clock clothing + the OOS-death re-fit trap). Jump/tail under-weighting = **DEAD** as a
  buy signal (it adds the −100% loss tail → a risk-CONFOUND that already sank favorite-tail, not an edge).

### Field D — Option time-decay & the short-dated / 0DTE regime (the `t` input)
- **Core object:** Greeks as t→0. A digital → a 0/1 step at the strike; delta→∞, gamma concentrates into a narrowing
  spike on the strike. Confirms the maker's Φ(d) is the **correct** 0DTE-digital form in t — the seam is *skew*, not
  the t-limit. Theta/gamma accelerate 4-5×/10× into expiry.
- **0DTE pinning (Dim-Eraker-Vilkov; Ni-Pearson-Poteshman):** dealer-gamma drives strike pinning — **but it requires
  a dealer delta-hedging the UNDERLYING**, which our cash-settled binary has none of → pinning does NOT mechanically
  transfer. Only an *exogenous* spot-pin near a big BTC option strike could matter (a spot-distribution-shape test).
- **Banging-the-close (Onur-Reiffen):** single-instant settlements invite closing-window trades; averaged windows
  (Deribit 30-min TWAP, VIX SET) are manipulation-resistant. Our **single-instant Chainlink-median settle is the
  vulnerable end** — but for retail this is the basis question (Thread B), amplified by D in the final seconds.
- **Beckmeyer:** long 0DTE loses ~4.7%, ~60% of retail loss = transaction cost; the winner is the theta/spread
  harvesting MAKER — the same walled-maker/taxed-taker picture. **Seam tags:** pinning, time-of-day, spread-dominance
  all **DEAD** (no dealer hedge / re-fit trap / confirmatory). D's only contribution = a τ-amplification bucket for A.

### Field E — Oracle design & settlement mechanics (settlement → outcome) ★ Thread B
- **Core object:** Chainlink settlement = a **median-of-medians** across all CEX/DEX venues (NOT Binance). Polymarket
  crypto resolves via Data **Streams** (sub-second PULL oracle) + Automation, `final ≥ strike → Up`, ties→Up —
  **not** the slow 0.5%/heartbeat push FEED (a common retail confusion that kills the naive "front-run the stale
  oracle" idea). No UMA dispute surface (that's for subjective markets). OEV ($500M+) lives in push-feed liquidations,
  not pull-settled binaries → no retail front-run.
- **The concrete unlock:** Polymarket's public **RTDS socket streams BOTH `binance` and `chainlink` values**,
  sub-second, no auth — the path to observe the *true settlement oracle* directly (`coins.chainlink_pair()` already
  names it). Converts Thread B from "can't see the label" to a pure numeric-basis question once logged.
- **USDT/USD depeg** is an independent additive to the basis (sub-bp in calm, magnitude-5 in stress).
- **Seam tag:** settlement-as-attack = **WALLED** (deterministic pull oracle, no UMA/OEV/front-run); the numeric
  Binance/Pyth-vs-Chainlink **basis = DATA-GATED** (settlement-LAG framing already killed: basis ~2.8% > ~1.2%
  tolerance, deflated p=0.89; only the near-strike-gated residual remains, needs months of flips).

### Field G — Prediction-market efficiency & betting economics (binary payoff + fee) ★ the sign-critic
- **Core object:** is `P∈[0,1]` a calibrated probability? Grossman-Stiglitz: perfect efficiency is impossible, the
  residual must just cover the marginal sophisticate's cost — **in a fee'd market the fee IS that cost.** An edge
  larger than the fee wedge is the anomaly to hunt; an edge at/below it is exactly what theory predicts.
- **Favorite-longshot bias (the SIGN objection):** longshots over-priced, favorites under-priced. Kalshi
  (300k contracts, Burgi-Deng-Whelan 2026): **takers lose ~32%, makers ~10%**; fees hit longshots hardest; the ONLY
  after-fee-positive cell is high-price FAVORITES (= our favorite-tail family, which we found pooled NET-NEGATIVE at
  5 min). **Critically: standard FLB makes the cheap UNDERDOG OVER-priced — the OPPOSITE of "underdog-Down
  under-priced."** So the skew seam is only live in genuine negative-skew regimes that *reverse* the usual FLB sign.
- **Calibration is BEST at the shortest horizon** (5 min) — the regime hardest to beat. Kelly/-100% geometry +
  Deflated-Sharpe/purged-CV (already our `analysis/stats.py`) = the methodology layer every candidate must clear.
- **Seam tags:** favorite-cell, maker-asymmetry, cross-venue-wedge all **DEAD/walled** for our 5-min product; G's
  real role = the **adversary** (its FLB result is the strongest reason to doubt the skew sign).

### Field C — Market microstructure & price discovery (spot/strike formation) — wall-confirming refresher
- **Core object:** how order flow forms price. OFI ~ linear in mid-move (Cont-Kukanov-Stoikov), horizon sub-second
  to ~10s; crypto study: imbalance-return corr ~0.20 @10s, **expected return <10bps vs ~20bps fee → fee-capped**
  (mirrors our market exactly). Crypto lead-lag is **sub-second** (CME→Binance ~55ms) → fresher-feed = HFT-only.
  Budish-Cramton: even *public* info creates a **speed rent** in a continuous book, won by the fastest → 1s-polling
  retail structurally loses every race (the theoretical backbone of our wall).
- **Cross-coin double-kill:** Capponi-Cont — genuine cross-impact adds **<1%** of explained variance over own-OFI +
  common factor; Epps effect — high-freq cross-corr → 0 (any slow-sampled corr is already in the slow quote). Both
  independently match our **B-risk-filter falsification** (alt's own 15s move gates strictly better than BTC's).
- **Seam tags:** OFI, lead-lag, cross-coin OFI, microprice — **all DEAD/WALLED** (sub-second/HFT or fee-capped). No
  overlooked door; the only adjacent live thread (settlement-source divergence) belongs to Field E, not fast C.

### Phase-1 synthesis — cross-field map, candidate ranking, verdict
**Cross-field joins that matter:**
- **A⊗B (the core seam):** the `−vega·dσ/dK` term A says Φ omits IS a property of B's vol *surface*; B supplies WHY
  a short-dated skew must exist (rough-vol τ^{−0.4}, maximal at 5 min) and WHICH WAY (inverse-leverage → regime-
  flipping). These fuse into one candidate = the conditional-skew residual. The single most load-bearing connection.
- **A⊗G (sign CONFLICT to resolve before testing):** A/B say negative-skew under-prices the digital-call; G's FLB
  says the cheap underdog is over-priced. They **disagree on sign** → the seam is a narrow regime-conditional bet
  against a strong null, not a standing edge.
- **E⊗B⊗D (Thread B stack):** basis-flip prob scales with short-horizon σ (B) and is largest in the final seconds
  (D's gamma∝1/τ) → near-strike + near-expiry + high-vol, exactly the gate already coded in `experiment_settlement_basis.py`.
- **F⊗A⊗G:** over-round = the maker's revealed skew/risk loading = the best built conditioning instrument for A.
- **C⊗E:** the basis is the cross-venue residual that single-venue (walled) lead-lag misses.

**Phase-2 candidate ledger (pre-ranked vs our walls):**

| candidate | field | tag | why |
|---|---|---|---|
| **Conditional-skew model-form residual** (`won−up_mid` vs causal trailing-skew proxy) | A⊗B | **TESTABLE** | NOVEL — a 3rd-moment error a symmetric Φ provably can't reach; orthogonal to every wall (1st-moment/σ-lag/HFT). Not yet built. LOW prior (σ-padding absorbs symmetric tails; fee brutal at p≈0.3-0.5; sign regime-flips). |
| **Settlement basis, near-strike gated** (RTDS chainlink) | E | **DATA-GATED** | = Thread B, built & pre-registered; Chainlink only logging since 2026-06-27 → INSUFFICIENT by construction; needs months. |
| **Over-round asymmetry as conditioner** | F | **TESTABLE** | only as a non-redundant gate/feature on the skew candidate (measure Jaccard); standalone = G-M spread = walled. |
| Tail/fat-tail OTM mispricing | A/B | DEAD | the absorbable (symmetric) half; cuts *against* favorite-buy = risk-confound. |
| Near-expiry instability harvest | A/D | DEAD | sub-second/HFT in time-decay clothing; demote to a τ-bucket for the skew test. |
| Calendar/time-of-day stale σ | B/D | DEAD | σ-lag + the re-fit-to-recent-data OOS-death trap. |
| Cross-venue LOOP wedge (4h half-life) | G | DEAD | hourly horizon, not our 5-min window; needs option/Chainlink leg. |
| Selective maker-in-noise | F/G | DEAD | already killed (−0.365 adverse selection); 5-min markets unfunded. |
| OEV settlement front-run | E/C | DEAD | pull-oracle + deterministic resolution closes the window; HFT-only. |
| Cross-coin OFI lead-lag (BTC→alt) | C/B | DEAD | Capponi-Cont <1% + Epps + our own B-filter falsification. |

**Field priority for Phase 2:** **A** (the only new on-data candidate) → **B** (supplies A's magnitude+sign model) →
**E** (Thread B, real but a waiting game) → **F** (the conditioning instrument/rigor wrapper for A) → **G** (the
sign-critic + the deflation gate) → **D** (confirmatory, a τ-bucket) → **C** (most walled, no new door).

**Honest bottom line:** the broad-field survey produced **no new edge**. It converts "the wall *feels* structural"
into "the wall *is* structural, for documented reasons," kills 8 of 10 seams with explicit mechanism, and leaves
exactly the two we already had. Its real value is three things: (a) it gives the skew candidate its rigorous form
(`won−up_mid` vs a causal trailing-skew proxy, joint-controlled against mid AND trend); (b) it raises the serious
FLB **sign objection** (the skew seam only lives in regime-reversed negative-skew windows; crypto's inverse-leverage
makes that sign unstable = the make-or-break risk); (c) Field B gives the τ^{−0.4} reason the skew term is maximal at
5 min = the strongest argument the seam is non-trivial. **Next:** ONE honest Phase-2 build of the skew residual (low
prior, expect priced-by-σ-padding or fee-capped), Thread B stays the patient data-gated bet.

**PHASE 2 RESULT (2026-06-28):** the skew residual is **DEAD** — the maker prices the skew (n_loss=412 = a real
verdict; moment coef +0.002, net-EV FAILS deflated p=1.0; robust whiff is BTC-only/coin-incoherent/fee-capped;
second-mind 0/40 deflated grid cells survive). See POSTMORTEM §1d / `dead_ends/experiment_skew_residual.py`.

---

# PHASE 3 — "Play a DIFFERENT GAME": how people ACTUALLY beat opponents like our maker — 2026-06-28

User reframe: we keep trying to out-RUN Usain Bolt (beat the maker at pricing the digital) and always lose because it
does the basics better; the winners "drive a car" = change the GAME. A 10-agent workflow (6 research angles +
2 surviving adversarial skeptics [different-game + accessibility lenses; the evidence-skeptic agent failed the schema]
+ synthesis, ~822k tokens) researched documented winners against analogous opponents and mapped each to our position.

**THE FINDING (validates the reframe):** EVERY documented winner against a sharp opponent changed the GAME —
role / information / scale / instrument / venue / fee-structure — and **NONE won by out-pricing a fast public-data
maker** (the exact game we keep losing). Benter (HK racing): a model BUT the edge was PRIVATE data + blending the
public odds as a feature + pool scale (R²=0.1245 model alone → 0.1396 only after adding public odds). Jane St/SIG/
Optiver: market-MAKING + structural-flow capture, not prediction. Medallion: 50.75% hit-rate × 150k tiny uncorrelated
trades/day, capacity-capped, execution mastery. Théo ($80–85M on Trump): commissioned private YouGov polls.
Starlizard/Smartodds: a data moat + syndicate scale + closing-line value. Betfair scalpers (Webb >£1M, Berry vetted
>£100k): they BECOME the bookmaker — and Betfair's Premium Charge taxing the winning 0.3–0.7% is hard proof the
maker role persistently wins on the right venue. Kalshi (300k contracts): makers lose −10% vs takers −32% — the role
flip is worth ~22 points but is STILL net-negative un-subsidized, and only favorites pay.

**THE VERDICT for US (honest):** there is **NO retail different-game on THIS specific 5-min product** — it is the
uniquely hostile case: SINGLE-venue (no identical contract to arb), UNFUNDED (maker earns no rebate, adverse-selected
−0.365/$1 — `experiment_maker_noise.py`, `feeds.fetch_rewards` rates=None), BORN-MATURE (an always-present R²=0.91
Φ-maker, no thin-market window), and DETERMINISTICALLY settled on a public Chainlink price (no information or
settlement edge; settlement-basis already killed). But this is "**closed for US on this product**," not "closed for
everyone" — the same skill set has escape routes that fit a small account, and **they all require changing the
PRODUCT, not the tactic.**

**Ranked candidate "different games" (3-skeptic-rated; available = to a small 1s-polling retail account):**

| # | different game | avail | tried? | verdict |
|---|---|---|---|---|
| **1** | **Delta-neutral funding-rate / cash-and-carry CARRY** (hold spot, short the perp, collect funding) | **YES** | **NO (never)** | The ONLY approach BOTH skeptics rate REAL_AND_APPLICABLE. True change of role+instrument+venue: you become the house the over-leveraged-long crowd overpays; the fee becomes a cash flow you COLLECT, no maker to out-price; slow 8h/1h clock (no latency needed); reuses `coins.py` per-coin polling + a public funding feed. **Honest:** compressed to single-digit APY (BTC basis 25%→4.5%, 93% of days < ~5% breakeven) + liquidation/short-squeeze/exchange-counterparty risk = a steady carry, not a windfall. **This lives entirely OFF Polymarket.** |
| **2** | **Favorite-longshot REVERSAL on LONGER-HORIZON Polymarket markets** (buy cheap favorites, hold) | PARTIAL | PARTIAL (only on 5-min, where it's net-neg) | The most robust documented prediction-market bias, but it lives on LESS-efficient longer-dated markets (politics/sports/longer crypto), NOT our well-calibrated 5-min clock. Reuses our CLOB plumbing + `stats.assess`. Thin, selection-sensitive (84% of PM wallets lose). Off the 5-min clock. |
| **3** | **DOV-style NON-TOXIC-FLOW-conditioned maker gate** (sell as maker only in clock buckets where taker flow doesn't predict won−mid) | PARTIAL | NO (naive maker tried → −0.365) | The ONE genuinely-new idea that lives ON our 5-min data, a pure `stats.assess` experiment on data we already store. LOW prior (near-expiry toxic + unfunded = no rebate to pad the tail), but un-run as a conditioned cell and cheap to test once. |
| **4** | **Maker rebate + liquidity-rewards on adjacent FUNDED markets** (scan `feeds.fetch_rewards` for funded pools, quote there) | PARTIAL | YES on our product (dead) | Real & retail-reachable on FUNDED markets, but a decaying subsidy (~10% APY ceiling) needing a maker bot + sustained two-sided-quoting capital. A different product. |
| 5 | Benter residual-blend / breadth (IR=IC·√breadth) / capacity / execution mastery | — | YES (it's our standing policy) | These are DISCIPLINES we already enforce (= why we keep correctly finding no edge). 0×N=0; our 6 coins ~0.6 corr ≈ one bet. Routes back to "change the product." |
| 6–8 | Cross-venue arb / PFOF; copy on-chain sharps / airdrop farming; settlement-dispute / dispersion / GEX | NO | n/a / walled | HFT/capital/license-only, or survivorship/marketing, or structurally absent on our deterministic public-price binary. |

**HONEST RECOMMENDATION:** the cleanest "fly a plane" move is **#1 — a Stage-1, NO-CAPITAL measurement of
delta-neutral funding carry** on the Binance feed we already poll (log per-coin funding + spot-perp basis, measure
persistence + net-of-fee carry over weeks, gate before any capital). It's the single approach both skeptics
independently rate fully applicable and the repo has literally never touched (every `experiment_*.py` is on the
walled 5-min binary). Secondary: favorite-reversal on longer-horizon Polymarket; tertiary: the one-shot non-toxic-flow
maker-gate test on data we already have. **Bottom line:** keep re-pricing the 5-min digital and we keep losing to
Bolt; the realistic shot requires pivoting the infrastructure to one of these adjacent games. (Full agent JSON:
session task `w1ya0ds3p`.)

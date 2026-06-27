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

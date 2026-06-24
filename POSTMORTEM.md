# POST-MORTEM — Is there a retail edge in Polymarket "Crypto Up/Down (5-minute)"?

**Verdict (rigor-corrected, 2026-06-25): No edge survives an honest test. The market is walled for
retail takers.** Every candidate fails once you (a) charge the verified fee, (b) account for the −100%
binary skew, (c) deflate for the hundreds of trials we ran, and (d) use the effective (not nominal)
sample size. This is not a tooling gap — we *built* the missing rigor and the conclusion held.

This document is the honest endpoint of the research program. The durable deliverable is the **rigor
module** (`analysis/stats.py`) that produced these verdicts and will gate every future idea.

---

## 1. Every candidate, through the corrected gate

The gate (`analysis/stats.assess`): **deflated cluster-bootstrap p < 0.05 on the fee-aware net-EV stream
AND cluster-CI excludes 0 AND ≥30 losers.** (Per-bet Sharpe is a monotone function of win-rate, so DSR /
PSR / Wilson are the *same* test — they're shown as presentation, not stacked into the gate.)

| candidate | n | losers | mean net-EV/$1 | deflated p | verdict |
|---|---:|---:|---:|---:|---|
| **Favorite-tail** (the base) | 1849 | 36 | **−0.0029** | 1.00 | **FAILS** (was "breakeven"; 4/6 coins negative) |
| **B risk-filter** | — | 8 | negative (fwd) | — | dying → ~dead (gates a negative base) |
| **Spike-gated fade** | 18 | 6 | +0.17 | — | INSUFFICIENT (no null at n<20) |
| **Residual basket** (market-neutral) | 34 | — | **−0.092** | 1.00 | **FAILS** (pays 2 taker fees) |
| **Reversion: after-recovery** | 262 | 121 | **−0.0041** | 1.00 | **FAILS** (was "+0.011 borderline") |
| **Reversion: peer-surge** | 254 | 167 | **−0.16** | 1.00 | **FAILS** (win-rate flipped 41.6%→34.3%) |
| **Spot cross-asset lead-lag** | 575k (spot) | — | — | — | real predictor, **never beats the quote** (priced) |

The borderline "pulses" (b-filter p=0.002, peer-surge +0.034, spike-fade 12/18) all **regressed to
negative or insufficient as data accrued** — the textbook deflated-Sharpe null asserting itself.

## 2. Why — the walls, reframed against theory

- **Efficiency = Grossman-Stiglitz.** The token already prices recent knowledge (residual ≈ 0). We were
  re-deriving equilibrium, not finding a bug.
- **The fee *is* the price of the edge.** Verified live (`feeds.fetch_fee_schedule`): `rate 0.07,
  takerOnly, exponent 1` → `0.07·(1−p)` per stake = **3.5% at p=0.5**, charged on every spread-cross.
  Polymarket introduced it *explicitly* to neutralize the latency arb we kept re-finding.
- **The −100% binary tail.** Single-name bets are severely negatively-skewed (favorite-tail skew −6.8),
  so the **mean-EV lies** — PSR/deflation reveal "+0.005 breakeven" as mildly negative.
- **Market-neutral is worse, not better.** A long/short basket sidesteps efficiency and the −100% tail
  but pays the taker fee **twice** (~7% near p=0.5) → −0.092.
- **The only fee-free income is the maker rebate, and it's tiny.** Capped at ~0.4%/$1 (`net_ev` cap
  0.004), and the maker side is adverse-selected (filled when wrong). Even a perfect noise-window maker
  earns ~0.4% on a fairly-priced bet while bearing the −100% tail — not a retail edge.

## 3. The one corner we could not settle (low prior)

**Maker liquidity-provision in cross-venue-confirmed noise windows.** It is the only theoretically-open
cell, but (a) its income ceiling is the ~0.4% rebate, (b) it requires winning the adverse-selection
battle the passive branch already lost, and (c) it **cannot be tested on our ~2 days of thin token data
with unobservable queue position** — it needs live liquidity provision. Prior: low.

## 4. The methodology that's wrong everywhere else, and what we fixed

The program's central error (caught by an independent second-mind review): **reporting raw p-values and
"breakeven" as if k=1**, with no deflation, no skew correction, and nominal (not effective) n. We built
`analysis/stats.py` to fix it: deflated cluster-bootstrap residual test, Neff-aware (cross-coin outcome
corr ≈ +0.61 → ~1.45 effective coins), n_loss-gated, multiplicity-deflated. It was itself critiqued and
corrected (the first version's gate was dead code using a DSR slider). **This is the durable asset** —
every future idea now gets an honest verdict instead of an n=18 mirage.

## 5. What would change the verdict

1. **Materially lower fees** (or a fee-free maker path that demonstrably beats adverse selection).
2. **A genuinely faster-than-arbitrage price feed** — but the fee was designed to tax exactly this.
3. **Much more data** — the binding constraint everywhere was ~2 days of token data / 8–36 losers; a
   marginal real edge (if any) needs months to clear deflation. The collector keeps running; re-gate
   the pre-registered candidates only when losers ≥ 30–50, and only believe a *deflated* pass.

## 6. Honest one-line verdict

> On this market, as it stands, there is **no demonstrable retail edge**: it is efficient-on-knowledge,
> fee-taxed exactly where the edge would be, and negatively-skewed; the few positive flickers were the
> best-of-N noise the deflated-Sharpe predicts, and they vanished under an honest test.

*Evidence: `analysis/stats.py`, `analysis/audit_candidates.py`, `experiment_residual_basket.py`,
`experiment_fear_dip_variants.py`, `feeds.fetch_fee_schedule`; memory `program-walled-verdict`,
`best-strategy-favorite-tail`, `market-efficient-no-knowledge-edge`. (Past-experiment quality audit folded
in from wf_08502ec3.)*

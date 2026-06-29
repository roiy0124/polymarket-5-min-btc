# THE VERDICT — the wall, and why this market is a casino, not a skill game

**Final result of the research program (2026-06-25, rigor-corrected; reconfirmed on fresh data through
2026-06-28): there is no demonstrable retail edge in Polymarket's "Crypto Up/Down (5-minute)" markets.
The market is WALLED.** Every candidate fails an honest test once you (a) charge the verified live fee on
every leg, (b) account for the −100%-on-miss binary skew, (c) deflate for the hundreds of configs tried,
and (d) use the effective (clustered) sample size instead of the nominal row count. This is not a tooling
gap — we *built* the missing rigor (`analysis/stats.py`) and the conclusion only hardened.

> One-line verdict: **the product is a near-efficient casino with a built-in house edge, not a venue where
> prediction skill converts into profit.** The few positive flickers were the best-of-N noise the
> deflated-Sharpe null predicts, and they vanished under an honest test.

Full evidence trail: **`POSTMORTEM.md`** (every candidate through the corrected gate), **`FIELD-NOTES.md`**
(the transferable method this produced), `EXPERIMENTS.md` + `dead_ends/` (the kills), `analysis/stats.py`
(the gate), `feeds.fetch_fee_schedule` (the live-verified fee).

---

## 1. The wall, stated plainly

The 5-minute up/down market is quoted by a **single fair-value market-maker** that prices each side as a
digital option — `Φ(ln(spot/strike)/(σ√t))` — off the public Binance feed at **R²=0.91**, requotes
sub-second, and runs the Up and Down books as one synthetic mirror (`down ≈ 1 − up` in 75–81% of
snapshots). On top of that fair line the venue charges a **taker fee of `0.07·p·(1−p)` per share** — about
**3.5% of stake at p≈0.5** — which it introduced *explicitly* to neutralize the latency arbitrage that bots
had been extracting.

So the retail taker faces, simultaneously:

- **An efficient line** — every public predictor (recent trend, momentum, cross-asset lead-lag) is already
  in the price. The outcome is *predictable* (BTC's 15s move correlates with the result at ~+0.4), but the
  *residual* (`outcome − price`) is ~0. Predicting reality is not the same as beating the price; the price
  already did it (Grossman-Stiglitz efficiency).
- **A house edge** — the fee is charged on every entry, sized to be largest exactly where any residual
  edge would live (mid-prices).
- **A −100% binary payoff** — each market resolves 0 or 1; a miss is total loss of stake. The return stream
  is severely negatively skewed (favorite-tail skew −6.8), so the *sample mean lies*: a "+0.5% breakeven"
  is actually mildly negative once the tail is priced (PSR/deflation).
- **A high spin-rate** — a fresh, serially-independent market every 5 minutes (~288/day/coin) grinds that
  house edge against you with gambler's-ruin dynamics.

Net of all four: every measured strategy is net-negative or insufficient. The headline numbers, from the
corrected gate (`analysis/audit_candidates.py`):

| candidate | net-EV/$1 | deflated p | verdict |
|---|---:|---:|---|
| Favorite-tail (the base) | −0.0029 | 1.00 | FAILS (looked "breakeven"; 4/6 coins negative) |
| Residual market-neutral basket | −0.092 | 1.00 | FAILS (pays the taker fee **twice**) |
| Maker-in-noise (fee-free + rebate) | −0.365 | — | DEAD (mechanical adverse selection) |
| B cross-asset risk-filter | −0.0019 | 1.00 | FALSIFIED (own-momentum confound) |
| Reversion / spike / σ-lag / skew | ≤0 or n<30 | 1.00 | DEAD or INSUFFICIENT |

---

## 2. Why it's a **casino roulette**, not a skilled-trading scenario

Line the product up against a roulette table and the structures map almost one-for-one:

| Roulette | This 5-minute market |
|---|---|
| **The green 0/00 = the house edge** (≈5.3% American). Baked in, paid every spin, makes the game negative-sum. | **The `0.07·p(1−p)` taker fee** (≈3.5% at p=0.5). Baked in, paid every entry, makes the game negative-sum — and was *deliberately set* to cancel the one skill (latency) that worked. The house tightened a leaky table. |
| **The croupier is the house**, not a player you can out-think. It pays out at fair-minus-vig odds. | **The market-maker is the house.** A fast fair-value bot quotes both sides as one synthetic book (R²=0.91 vs Binance). You bet against a fair line minus a margin — you are not exploiting a counterparty's mistake, you're paying the vig. |
| **Past spins don't help** — the wheel has no exploitable memory; any "system" is variance. | **Prediction doesn't help** — the wheel *does* have memory (the outcome is forecastable), but it's already priced, so your forecast buys nothing. Residual ≈ 0. Different mechanism, identical result: analysis can't beat the line. |
| **Fixed-odds, all-or-nothing bet.** Chips down, ball lands, win the payout or lose it all — no managing the position. | **−100% binary.** Stake in, market resolves 0/1, win or lose it all — no scaling, hedging, or stop that changes the fixed payoff. |
| **High spin-rate grinds the edge.** Many independent spins ⇒ the house edge dominates outcomes over time. | **A new independent market every 5 min** (~288/day/coin) ⇒ the fee dominates over time; gambler's ruin. |
| **The "winning system" illusion.** Streaks and martingales *look* like edges and regress to the house edge. | **The best-of-N mirage.** Configs like "+0.08 residual, 97.7% win, p=0.006" or "b-filter p=0.002" looked like edges and **regressed to negative as data grew** — the deflated-Sharpe null asserting itself. |
| **The only "free" money is comps**, which never exceed the edge. | **The only fee-free income is the maker rebate** (~0.4%), and it's adverse-selected (you fill when wrong) → net −0.365. Comps that never cover the vig. |

The casino's whole design goal is to make a game where **no amount of player skill changes the expectancy** —
and to take a small cut every round. This market achieves exactly that, by two reinforcing mechanisms:
the fair-value maker prices out your *information*, and the fee taxes out your *residual*. The result is a
game you cannot beat by being smart, only by being lucky over a short run before the edge grinds you down.

---

## 3. The honest nuance — it is skill-**proofed**, not skill-**less**

(Data-detective discipline: state where the analogy *breaks*, so it isn't a glib overclaim.)

Roulette is unbeatable because its outcomes are **random by construction** — there is no signal to find.
This market is different and, in a way, *more* interesting: the outcomes are **richly informative and
structured** (real BTC price dynamics; a genuine cross-asset lead-lag exists, r≈0.12, sign-stable over 5.5
years). The signal is *real*. It is just **pre-priced and fee-taxed** out of reach. So the right label is:

> **A skill-PROOFED game, not a skill-LESS one.** The edge isn't absent; it's *absorbed* — by an efficient
> maker (Grossman-Stiglitz: the residual is sized to the fee) and a fee calibrated to the edge.

This distinction is not academic — it dictates the cure. In roulette the lesson is "stop playing." Here the
lesson is sharper: **you don't need a better predictor (the line already knows), you need to change the
game.** A genuinely skilled-trading scenario would restore at least one of the five things this product
strips out:

1. **A weaker counterparty who pays you** — biased/forced/uninformed flow (a real "payer"), not a fast
   fair-value house. *(e.g. retail-driven event markets, favorite-longshot biased books.)*
2. **Un-priced information or speed you uniquely hold** — a private signal or a feed the maker doesn't see,
   not public data it already prices.
3. **A cost structure that doesn't tax the edge out** — a fee-free or rebate-positive role, or a venue
   without a vig sized to the alpha.
4. **Position management that converts skill into asymmetric payoff** — scaling, stops, hedging — instead
   of a fixed all-or-nothing binary.
5. **A role rather than a bet** — *being* the house (market-making, collecting the spread on uninformed
   flow), providing a service, or harvesting a structural premium with a named payer (e.g. delta-neutral
   funding carry from over-levered longs).

This 5-minute product offers **none** of the five: the counterparty is the house, the information is public
and pre-priced, the fee is calibrated to the residual, the payoff is fixed-binary with no management, and
the only non-taker role (maker) is rebate-capped *and* adverse-selected. Strip all five and what remains is,
structurally, a casino game — an unusually *fair* one (no longshot bias to exploit either; that was tested
and dead), with a competitive house and a modest, mathematically-precise vig.

---

## 4. What would change the verdict

From the post-mortem — re-open only on a concrete trigger, never on a hunch:

1. **Materially lower fees**, or a demonstrably fee-free maker path that beats adverse selection.
2. **A genuinely faster-than-arbitrage feed** — but the fee was engineered to tax exactly this, so it must
   be *much* faster, not marginally.
3. **Much more data** — the binding constraint everywhere was the loser count (8–36); a marginal real edge,
   if any, needs months to clear deflation. The collector keeps running; re-gate the pre-registered,
   params-LOCKED candidates only when losers ≥ 30–50, and believe only a *deflated* pass.
4. **Change the product** (the real path) — a different venue/role/instrument with a weak payer, an
   un-priced signal, or a fee structure that doesn't eat the edge. That is a different project, not a tweak
   to this one.

---

## 5. The durable takeaway

The negative result is not the asset. The **method** is — the discipline that cheaply and honestly
established the wall, killed dozens of seductive false positives, and now transfers to any future
data/markets/decision project. It is written up as transferable principles in **`FIELD-NOTES.md`** and
encoded as reusable tooling: `analysis/stats.py` (the gate), the `quant` + `data-detective` skills, and the
`second-mind` / `vet-idea` / `scout-opportunity` workflows.

> The edge may not exist. The discipline that tells you so — cheaply, honestly, and once — is the thing
> worth keeping.

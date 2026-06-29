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
| **B risk-filter** | 449 (fwd) | 9 | **−0.0019** | 1.00 | **FAILS / FALSIFIED** (see below — own-momentum confound) |
| **Token-fear FOLLOW** | 599 | 243 | **+0.0236** | 1.00 | **FAILS net** (cluster-CI [−0.074,+0.122]; signal real at MID, fee-capped — below) |
| **Maker-in-noise** | 2254 | 1561 | **−0.365** | — | **FAILS / DEAD** (adverse selection; was wrongly "0 fills" — below) |
| **Spike-gated fade** | 18 | 6 | +0.17 | 1.00 | **DEAD** (no dose-response + falling-knife fail — below) |
| **Residual basket** (market-neutral) | 34 | — | **−0.092** | 1.00 | **FAILS** (pays 2 taker fees) |
| **Reversion: after-recovery** | 262 | 121 | **−0.0041** | 1.00 | **FAILS** (was "+0.011 borderline") |
| **Reversion: peer-surge** | 254 | 167 | **−0.16** | 1.00 | **FAILS** (win-rate flipped 41.6%→34.3%) |
| **Spot cross-asset lead-lag** | 575k (spot) | — | — | — | real predictor, **never beats the quote** (priced) |
| **Conditional σ-lag** (Thread A) | 919 | 32 | +0.008 gated | 1.00 | **DEAD** (priced latency-lag; loss-starved — §1c) |

The borderline "pulses" (b-filter p=0.002, peer-surge +0.034, spike-fade 12/18) all **regressed to
negative or insufficient as data accrued** — the textbook deflated-Sharpe null asserting itself.

### 1b. Re-experiment of every still-open idea (2026-06-25, second-mind reviewed)

On the user's instruction, every idea NOT yet *proven* dead was re-run on the now-larger dataset
(alts ~640 windows each, BTC ~1397), routed through `analysis/stats.assess` (`analysis/gate_open_ideas.py`),
and adversarially reviewed by an independent second-mind agent. All four resolved to DEAD or fee-capped:

- **Maker-in-noise — the prior "0 modeled fills / empty cell" was a GATE BUG, not an empty cell.** The
  toxicity gate measured pre-entry FLOW over `[entry−60s, entry]`, but entry fires at the first mid-band
  moment (`time_left≥60` == window OPEN, median entry tl=300), so the 60s prior is the *previous* window
  when the token barely traded → `flow_imbalance` returned `None` for ~100% (3/3716) → every candidate was
  dropped before the fill model ran. Removing the structurally-unavailable flow gate, the cell **populates**
  (2254 fills) and is decisively negative: **win 30.8% at mean fill 0.487 → −0.365/$1** even with rebate and
  no taker fee. This is *mechanical* adverse selection (a resting BUY fills precisely when SELL flow pushes
  the token toward 0 — fill and loss are the same event). The fill model is itself **optimistic**
  (`queue_ahead==0` for 99.8% of open-entries → assumes front-of-empty-queue instant fill), so −0.365 is an
  **upper bound**; live fills can only be worse. The one causal toxicity proxy *with* data (top-5 book depth
  imbalance) lifts it merely to −0.285 at strong bid support — nowhere near the ~0.485 breakeven. The fee-free
  corner is **DEAD**; the postmortem's *conclusion* (corner unviable) survives — only its *reason* was wrong.
- **B risk-filter — cross-asset story FALSIFIED, not merely "wait for data."** Forward gated EV is still
  negative (−0.0019). The decisive new test (now CHECK 5 in `validate_b_riskfilter.py`): replace BTC's last-15s
  move with the **alt's OWN** last-15s move as the gate. Own-momentum gates **strictly better** (+0.0091 vs
  B's +0.0052 in-sample; +0.0027 vs −0.0019 forward), and the "pure cross-asset" component (BTC net of own) is
  the **worst** of the three. In the subset where B uniquely keeps (own-momentum says skip), B keeps **losers**
  (−0.038). So B is a generic favorite-MOMENTUM filter (~77% sign-overlap with own-momentum) on a fee-negative
  base, not a BTC lead. The forward placebo p=0.035 dies at any honest N (Sidak N≥3 → >0.099) and the
  window-clustered one-sided p is 0.57. **DEAD** — stop the pre-registration clock.
- **Token-fear FOLLOW — signal is REAL at the mid, killed by spread+fee (record as fee-capped, not "no
  signal").** Decomposition on the n=599 fired set: gross residual (won − down_**mid**) = **+0.052, cluster-CI
  [+0.009,+0.095], p=0.008**, positive in all 6 coins; minus the half-spread → +0.037 (p≈0.05); minus the
  3.1pp taker fee → +0.024, cluster-CI [−0.074,+0.122], p=0.32 → gone. So the informed-dump Down edge exists
  but the **taker** cost eats it. The only specification that could legitimately flip it is a **fee-free
  maker-Down entry** (the gross-mid edge clears breakeven). Revisit at n_fired ≳ 1800 OR via maker-Down;
  params LOCKED, no re-tune.
- **Spike-gated fade — DEAD on the current thesis.** The +0.17 at z<−3 (n=18) has **no dose-response**:
  loosening z→2.5→2.0 turns resid **negative** in both drop columns (a real over-reaction effect would stay
  positive as more noise spikes are admitted). It also fails a falling-knife check (spike-dumps resolve Down
  33% vs 51% baseline = these 18 just happened to win). Binding constraint is intrinsic event-scarcity (z<−3
  is a ~0.1% tail → ~18 events across the whole archive); sub-second `price_ticks` sharpen *detection* but
  cannot add token windows. At most WAIT-FOR-DATA with a pre-committed kill (n_loss≥30 AND monotone resid).
- **Idiosyncratic-spike** — descriptive only; its sole consumer (spike-fade) is dead, so it has no live role.

### 1c. Conditional σ-lag (Thread A of the maker-component program) — 2026-06-27, second-mind reviewed

The "predict the maker's INPUTS not its OUTPUT" program (see `maker_behavior.md`) put the **σ component**
first: not the *average* σ-error (self-priced VRP, already dead) but a **conditional** one — does the maker's
σ go STALE for a beat after a fast vol-regime change, leaving the favorite under-priced for flip risk?
(`dead_ends/experiment_sigma_lag.py` + `_probe.py`.) It looked alive: a clean monotone dose-response (EV
+0.0064 → −0.0666 as `staleness=recent_vol/implied_σ` rises) and a joint ask-control PASS (`won ~ fav_ask +
staleness`: coef −0.41, **negative in 100% of cluster-refits, perm-p 0.003**, survives adding over_round,
LOCO-stable across all 6 coins, beats 200 placebos, deflates to ~0 at K=200).

A 3-angle independent second-mind **killed it on two grounds:**
1. **It IS the walled latency-lag, not a stale σ.** Decomposition: the signal is entirely the recent-vol
   *numerator*, the implied-σ *denominator* has the wrong sign — so "stale σ" is a misnomer; and `recent_vol`
   adds **nothing beyond raw |move|** (incremental coef −0.001). The clincher: re-measure the favorite ask
   **fresher** and the coef dies monotonically (ask@tl=30 −0.256/p=.04 → ask@tl=10 **+0.105/p=.66, sign flip**);
   the winner-vs-loser ask gap goes +0.002 @tl=30 → **+0.36 @tl=10** (the continuously-requoting maker has
   already marked losing favorites 0.96→0.61). You'd be buying at 0.96 a thing repriced to 0.61 seconds later
   = adverse selection. Plus the effect is a **3-second-wide spike at tl=30** (collapses at tl=33/35, flips
   positive at tl=50) — a frozen-quote-cadence artifact, not a smooth microstructure law.
2. **Loss-starved by construction.** The favorite-tail pool has only **32 losers**, so any gate selective
   enough to lift EV starves below n_loss=30 (all 21 sweep cells INSUFFICIENT; gated +0.0084 flips negative at
   +3 losers). Stacking with over-round is dead-on-arrival — the two cut the **same losers** (Jaccard 0.58–0.69),
   so the stack starves to 6 losers. **Durable meta-lesson:** *every loser-cutting filter on the favorite-tail
   base is INSUFFICIENT by construction until the loser pool grows past ~90–100 (months more data).* This is
   why over-round can't graduate either — stop testing filters of this shape on favorite-tail. Thread A CLOSED.

**Thread A-prime — mechanical σ roll-off (`dead_ends/experiment_sigma_rolloff.py`), 2026-06-27.** The one
"predict the maker's strings" corner that is *not* the latency-lag: predict the maker's NON-informational σ
update — a vol spike AGING OUT of its trailing window makes it mechanically re-rate the favorite up — and
pre-position before it re-quotes. **DEAD both ways, and the "mechanism" itself was mostly a confound.** (A)
Hold-to-resolution = the priced VRP **level** (`won ~ ask + over_charge` coef ≈ 0, perm-p 0.85; aging adds
nothing). (B) The headline "+1.73% mechanical re-rate" (favorite ask rises more in aging windows tl30→tl10) is
**~81% an outcome-mix (Simpson) artifact**: the ask-change is outcome-dominated (`corr(dask, won) = +0.65` —
winners' asks march to 1, losers' to 0), so any won-correlated regressor inherits a spurious excess;
**winners-only it collapses to +0.003** (CI spans 0) and aging carries no outcome info beyond ask (corr −0.055).
The genuine won-orthogonal piece is **~0.1¢/σ** — real but sub-economic — *and* uncapturable: the re-rate lives
on the **ask**, you exit at the **bid** (which doesn't follow), so every round-trip is negative at every exit
(clairvoyant best-exit still −0.0027/$1) and maker-rest-sell is adverse-selected (fills 99%-winners). **Reusable
guard:** in this product the favorite ask-change is outcome-dominated (corr 0.65) → *always control for `won` /
measure within-winners before reading any tl-window ask-rise as "mechanical".* This closes the "predict the
maker's σ string" corner entirely; only **Thread B (settlement feed), data-gated**, remains open.

### 1d. Conditional-skew model-FORM residual (the field-research program's one testable lead) — 2026-06-28, second-mind reviewed
The field-by-field deep-research program (`RESEARCH-EXTERNAL.md` "PHASE 1", 7 field briefs + synthesis) surfaced
**exactly one** new on-data candidate: the maker's quote `Φ(d)` is a **symmetric, driftless Gaussian**, and option
theory says the true digital = `Φ(d2) − vega·dσ/dK`, so a symmetric Φ **omits a 3rd-moment (skew) term**. Unlike
σ-level (which the maker re-fits → self-priced), a single σ *cannot* encode the 3rd moment, so a skew residual
*could* survive. Rough-vol (H≈0.1, ATM skew ∝ τ^−0.4) says it would be MAXIMAL at our 5-min horizon — the strongest
pro-argument. Built `dead_ends/experiment_skew_residual.py`: per-coin **causal trailing skewness** of the realized
5-min returns `ln(final/strike)` (the literal variable the digital bets on), joint-control (`won_up ~ up_mid +
trend + skew`), per-coin causal skew-tercile dose-response, and a pre-committed directional net-EV gate (buy Up in
the most-negative-skew tercile, Down in the most-positive — sign locked from theory, no in-sample flip).

**DEAD — the maker prices the skew.** This corner was NOT loss-starved (n_loss = 412 — a *real* verdict, the first
since favorite-tail). Under the literal **moment** skew (pre-committed primary) the skew coef is **+0.002** (negative
in 20% of refits, permutation p=0.52 → collapses given the mid), `corr(skew, won−mid) = −0.001`, and the net-EV gate
**FAILS** (win 52.1% vs 54.4% breakeven, mean −0.046, cluster-CI[−0.117,+0.025], deflated p=1.0). Under a **robust
Bowley** skew there is a *faint* theory-signed joint-control whiff (coef −0.156, perm p=0.003) — but it is
**BTC-concentrated and coin-INCOHERENT** (sol/xrp sign-reversed; LOCO halves it; un-deflated within-coin p=0.044 dies
under multiplicity), **non-monotone**, and **still fee-capped** (50.5% vs 53.9% breakeven). The **second mind** (hard
refutation attempt) confirmed: no look-ahead bug (`trailing_proxy` proven invariant to corrupting future returns); a
sign-flip is *worse* (= a no-signal problem, not a sign error); **0 of 40 deflated grid cells** (2 proxies × 4
trailing-windows × 5 moneyness bands) clear the fee; a sharper **intraday-spot** skew even has the **wrong sign**
(crypto's INVERSE leverage effect makes the realized→implied skew mapping regime-unstable — the make-or-break risk
the brief flagged); and the ATM maker route is the already-walled **−0.365** toxic zone. **This is the absorbable,
fee-capped half of the model-form story** — Grossman-Stiglitz "residual sized to the fee." With the skew lead dead,
the field-research program has **no remaining testable-now candidate**; the only on-market open thread is **Thread B
(settlement basis), data-gated**.

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

## 3. The one corner we could not settle (low prior) — and we tried

**Maker liquidity-provision in mid-price "noise" windows** is the only theoretically-open cell (fee-free
+ rebate). The quality audit correctly noted it's testable *in principle* — the `queue_ahead` fill-model
engine exists (`analysis/backtest.py`) and `book_events` carries the depth. So we built it
(`experiment_maker_noise.py`: rest a maker bid in p∈[0.35,0.65] low-toxicity windows, model the fill from
the real book + SELL prints, hold to 0/1, credit the rebate, no taker fee) and ran it through the gate.

**Result (CORRECTED 2026-06-25): the cell is NOT empty — it is DEAD by adverse selection.** The original
run reported "0 modeled fills," but that was a **gate bug** (§1b): the toxicity gate measured pre-entry flow
at window-open, where it is structurally `None`, so it dropped every candidate. With the broken gate removed
the cell populates (**2254 fills**) and prints **−0.365/$1** even fee-free + rebate (win 30.8% at fill 0.487)
— mechanical adverse selection, with the fill model itself optimistic (front-of-empty-queue), so that is an
upper bound. No causal toxicity proxy with data (book depth imbalance → −0.285 at best) rescues it. The
income ceiling is the ~0.4% rebate vs a ~15.7pp win deficit. **Verdict upgraded from "could not settle /
prior low" to settled DEAD on modeled data; live fills could only be worse.**

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

## 6. Past-experiment audit (all 25, second-mind reviewed)

A 4-expert panel graded every experiment for quality + whether its conclusion survives the rigor standard.
The one systemic defect: **only `analysis/stats.py`, `analysis/audit_candidates.py` and the basket import
the rigor module — every other experiment used the naive mean+Wilson+row-resampled placebo.** That inflated
the borderline positives. But the asymmetry saves us: **a negative/dead conclusion is robust** (deflation
only deepens a kill), so the 18 dead experiments stay dead. Of the claimed-positives, all were re-run and
**overturned in the safe direction**: favorite-tail (→ negative), peer-surge/after-recovery (→ negative),
B-component STEP-2 (→ NOT VALIDATED). The only "needs more data" item is spike-fade (n=18, prior LOW). The
real signals that *exist* (spot lead-lag r≈0.12, B STEP-1) are confirmed — they just don't survive translation
to net EV past the quote + fee.

## 7. Honest one-line verdict

> On this market, as it stands, there is **no demonstrable retail edge**: it is efficient-on-knowledge,
> fee-taxed exactly where the edge would be, and negatively-skewed; the few positive flickers were the
> best-of-N noise the deflated-Sharpe predicts, and they vanished under an honest test. A real cross-asset
> signal *is* present, but the quote already prices it and the verified 0.07·p·(1−p) fee + spread sink
> every translation net-negative — efficient on knowledge **and** walled on execution.

*Evidence (all committed): `analysis/stats.py` (the rigor module), `analysis/audit_candidates.py`,
`experiment_residual_basket.py`, `experiment_maker_noise.py`, `experiment_fear_dip_variants.py`,
`feeds.fetch_fee_schedule`; memory `program-walled-verdict`, `best-strategy-favorite-tail`,
`market-efficient-no-knowledge-edge`. Past-experiment audit: wf_08502ec3 (25 experiments graded).*

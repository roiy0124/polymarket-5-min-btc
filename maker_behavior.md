# maker_behavior — everything we know about the maker (living doc)

The canonical, plain-language reference on the counterparty we trade against in the Polymarket 5-min crypto
Up/Down markets. **Keep this updated as we learn.** Every claim is tagged **[VERIFIED]** (we ran the test),
**[STRONG INFERENCE]** (the data strongly implies it), or **[HYPOTHESIS]** (plausible, not yet pinned).
Chronological findings + scripts live in `MAKER-MODEL.md`; this is the consolidated "what we know."

---

## 0. THE STRATEGIC FRAME — "me vs the maker," predict his INPUTS not his OUTPUT (thesis, 2026-06-27)

The reframe that re-opens the program. Two different games, and we were stuck in the wrong one:

- **OLD game ("me vs others / me vs the market"):** predict the stock's price *movement*. We tried this for a
  whole program → WALLED. The market is efficient on knowledge.
- **NEW game ("me vs the maker"):** there is no faceless "market." There is **one fair-value bot** setting every
  price. So the real opponent is *that bot*. And here's the key distinction we kept missing:
  - Everything that looks **"unbeatable / smart / tight"** is the maker's **OUTPUT** — its finished quote, which
    is the *correct* answer to its own equation. Trying to out-predict the output = trying to out-compute a bot
    running the right model on the same data. Hopeless.
  - But the maker's quote is `Φ( (spot − strike) / (σ·√t) )` — a function of **INPUTS / COMPONENTS** (its
    "body parts" / the strings it pulls). **We don't have to beat the output; we have to beat ONE input.** If we
    estimate any single component *better than the maker does*, we compute a better fair value and we are now
    **playing its exact game, at its level — competing, not guessing.**

**The program this defines:** decompose the maker's equation into its components, and for EACH, ask
**where / when / how much the maker gets that component wrong**, and whether *we* can do better:

| component | can the maker be wrong on it? | our finding | open? |
|---|---|---|---|
| **time** `t` | no — deterministic, we both have it | no edge | closed |
| **strike** | fixed at open; both observe it (but on WHICH feed? see spot) | — | tied to spot |
| **σ** (volatility) | yes — its ONE estimated input | avg σ-error is **self-priced / EV-neutral** (VRP, dead). **Conditional σ-lag now TESTED (2026-06-27) → DEAD**: the "stale σ" signal decomposes to the recent-vol numerator (not the implied-σ denominator) and is the already-walled **latency-lag** — it vanishes/flips against a 15-20s-fresher ask (loser favorites already marked 0.96→0.61 by tl=10). Loss-starved too (32-loser pool). | **CLOSED** (Thread A killed) |
| **spot / settlement feed** | **YES — structurally, NOW CONFIRMED.** The maker prices off **BINANCE** (verified: maker-quote fit R²=0.75 vs Binance, 0.0007 vs Pyth; joint coef Binance +0.87 vs Pyth +0.01), but the market **SETTLES on Chainlink**. So its spot input is *systematically the wrong denomination/source* by the basis dynamics. | **the OPEN component** — maker=Binance CONFIRMED; build fair value on Chainlink (forward data) | **OPEN — highest priority** |

**Step 1 of the program DONE (2026-06-27):** *which feed does the maker price off?* → **BINANCE, decisively**
(R²=0.75 vs Pyth 0.0007, n=904k; experiment in `MAKER-MODEL.md`/chat). The market settles on Chainlink. So the
maker's fair-value model has a STRUCTURAL input-error (Binance/USDT vs Chainlink/USD). Pyth data looks
unreliable (Binance-Pyth log-ret corr only 0.019) → the decisive maker-vs-us comparison is Binance-vs-CHAINLINK,
which the new Chainlink layer enables once ~weeks of forward data accrue. The edge (if any) = compute fair value
on the TRUE oracle, trade the windows where it diverges from the maker's Binance quote, at the favorite (cheap
fee) + near-strike where a few-bps basis flips Up/Down. **[VERIFIED maker=Binance; edge HYPOTHESIS pending data]**

**The "string hierarchy" (play as high as you can):**
- *Level 0* — predict the OUTPUT (the quote). Walled.
- *Level 1* — compute the fair value yourself with a **better input** than the maker (e.g. the TRUE settlement
  feed it doesn't use). This is "playing at the maker's level."
- *Level 2+* — predict the **drivers of the components** before the maker incorporates them (e.g. a vol-regime
  shift before its σ catches up; a USDT/USD move before it hits the basis). Higher leverage if it exists.

**The cost gate (never forget):** a better fair value only PAYS if the mispricing it reveals exceeds the
trading cost. The taker fee is tiny at high p (the favorite) and brutal at p≈0.5. So a component-error edge
most plausibly lives **at the favorite (cheap fee) + the settlement-basis residual** — exactly where the new
Chainlink layer points.

**First experiment of this program:** *which feed does the maker actually price off?* Fit its historical quote
to Φ built on Binance vs Pyth (we have both); add Chainlink going forward. If it tracks a proxy but settles on
Chainlink, that gap is a structural component-error we can trade by computing fair value on the real oracle.

---

## 1. Who/what the maker IS

- **The market is a CLOB** (central limit order book), not an AMM. Every price is a resting limit order. The
  "maker" = whoever posts the resting bid/ask depth; the "taker" = whoever crosses the spread. **[VERIFIED]**
- **It is ONE algorithmic, synthetic-book market-maker per coin** — not a crowd. Evidence: the Up and Down
  order books are **exact mirrors (same prices + sizes, down = 1 − up) in 75–81% of snapshots.** A human/crowd
  can't produce that; one bot prices the Up token and *derives* the Down book by reflection. **[STRONG INFERENCE]**
- **It earns a maker rebate**; the reward function found in the wild (warproxxx/poly-maker) is roughly
  `S = ((v−s)/v)²·b` — paid most for resting *exactly at the mid*. That financial incentive is *why* its quote
  is pinned to fair value (deviations cost it rebate). **[STRONG INFERENCE]**

## 2. How it PRICES (its model — and why we can't out-predict it)

- **It is a digital-option fair-value bot:** `up_mid ≈ Φ(ln(spot/strike) / (σ·√t))` — fits at **R² = 0.91**
  (btc/eth/doge). Φ = normal CDF; t = time remaining. **[VERIFIED]**
- So it responds, overwhelmingly, to just three things: **spot − strike, time-decay, and σ.** The first two we
  can NEVER beat — it has the same spot feed and the same closed-form model. *This is why every directional /
  "predict the outcome" idea is walled: we'd be out-predicting a bot running the exact right model on the same
  data.* **[VERIFIED]**
- **σ is its one free parameter** — the only place it can be "wrong":
  - It tracks realized vol (`corr(implied σ, realized σ) ≈ +0.74`) — adaptive and competent. **[VERIFIED]**
  - It **pads vol ~15%** (median implied/realized ≈ 1.15) = a structural **Variance Risk Premium** (it charges
    for uncertainty, like any MM). **[VERIFIED]**
  - Its effective σ **varies ~2×** across windows (IQR ≈ 4.7e-5 → 1.0e-4 per √s ≈ 27%–58% annualized). **[VERIFIED]**

## 3. How it MANAGES RISK (its behavior)

- **The over-round (`up_ask + down_ask − 1`) is its spread = its self-reported confidence.** Baseline ~1–2%;
  it **widens when the outcome is genuinely uncertain** (`corr(over_round, |outcome − mid|) ≈ +0.17`). **[VERIFIED]**
- **It has a volatility circuit-breaker + hysteresis-cancel:** on fast moves it stops/freezes quoting (re-quotes
  only on a >0.5c move) and **lets one side thin** — our data confirms the footprint (one-sidedness rises with
  spot-move size, `corr +0.077`; a side goes near-empty 3.5% → 5.6% of the time in fast moves). **[VERIFIED]**
- **It steps away precisely when flow is INFORMED.** When the book goes one-sided during a spike, the price
  **continues** (signed forward mid +0.040 vs +0.005 baseline = 8×; only 28% revert). The bot is *defending
  itself against toxic flow* — it is being smart, not making a mistake. **[VERIFIED]**

## 4. What we PROVED about beating it (the walls — and WHY each is a wall)

| we tried to exploit… | result | the reason |
|---|---|---|
| **vol-confidence** (over-round / VRP / σ-error) | walled | the bot **self-prices its own confidence** → reading it is EV-neutral vs random (loss-rate p=0.013 but **EV p=0.30**), non-stationary |
| **circuit-breaker** (spike one-sidedness, provide the abandoned liquidity) | walled | the one-sided moment is **informed continuation** → providing liquidity = adverse selection |
| **inventory skew** (calm one-sidedness, expect it to unwind) | walled | calm one-sidedness is **priced momentum, not a reverting mistake** (`corr +0.093`, continues) |
| **directional / momentum / lead-lag** (predict the outcome) | walled | the mid already prices it (efficient-on-knowledge); a faster feed is fee-capped |

**The unifying truth:** *depth one-sidedness ALWAYS predicts continuation (spike +0.32, calm +0.09), NEVER
reversion → providing liquidity to the maker is adverse-selected at every condition tested.* The bot's quote
is fair value and its one-sidedness is *informed*. **It makes no exploitable mistakes.** This is exactly what
walled the two real public MM operators (adverse selection + queue-position opacity). **[VERIFIED]**

The ONE thing that came closest: the **over-round gate** — skip the favorite-tail when the bot's over-round is
wide (its revealed fear). The *signal* is real and independent of the ask (joint logistic **p=0.0006**) and
lifts favorite-tail from breakeven-negative to **+0.006/+0.009**, but it's **loss-light (INSUFFICIENT)** and
the gross edge barely clears the fee. It's a candidate, not a winner. **[VERIFIED]**

## 5. The COST structure (the other half of why it's hard)

- **Taker fee = `0.07·(1−p)` per stake** (verified live): **~0.2% at p=0.97** (cheap — favorite tail), **~3.5%
  at p=0.5** (brutal — mid). So directional edges only survive at high p; mid-price edges are fee-walled. **[VERIFIED]**
- **Maker = fee-free + a tiny capped rebate (~0.4%)** but **adverse-selected** — a resting bid fills when
  informed flow crosses it. The ONLY non-adverse maker fill we found is on the favorite in **over-round-tight
  (calm) windows** (fill-conditional residual −0.0007 ≈ fair), but it's only breakeven (you fill the weaker
  favorites). The mid-band maker is **−0.36** (catastrophic adverse selection). **[VERIFIED]**
- **The fee IS the price of the edge** (Grossman-Stiglitz): Polymarket introduced it to neutralize exactly the
  latency arb people keep re-finding. **[VERIFIED]**

## 6. METHODOLOGY facts about reading the maker (learned the hard way)

- **Polymarket's `side` (BUY/SELL) field is only ~59% accurate** vs on-chain ground truth (arXiv, 30B ticks;
  Lee-Ready is ~81% on real exchanges). **This is why every flow/CTAP signal we built came out ≈0** — we were
  feeding it a coin-flip. **Never sign flow by `side`; use price+size deltas or L2 reconstruction.** **[VERIFIED]**
- **Inventory/one-sidedness lives in the DEPTH, not the mid** ("prices for score, sizes for view") — measure
  `overall_ratio = bid_depth/(bid+ask)`, not a mid move. We built `analysis/book_reconstruct.py` (validated
  99.79% vs the feed's own best_bid/ask) to see it. **[VERIFIED]**

---

## 7. WHY we now collect the Chainlink data (the new layer)

**The single most important thing the maker and we were both blind to: the market does NOT settle on Binance.**

- **The market settles on the Chainlink `<coin>/USD` oracle** (price at T=0 vs T=300). We had been *proxying*
  it with Binance `BTCUSDT` and Pyth — neither is the settlement source. **[VERIFIED]**
- The Chainlink settlement feed turned out to be **public over WebSocket** (`wss://ws-live-data.polymarket.com`,
  topic `crypto_prices_chainlink`, ~1/s, no auth) — previously we thought it was auth-gated. We now **capture
  it** into `price_ticks(source='chainlink')` + durable per-window `windows.strike_chainlink`/`final_chainlink`. **[VERIFIED]**
- **First finding from the layer:** Binance(BTC**USDT**) vs Chainlink(BTC/**USD**) is a **near-constant ~16 bps
  (~$100) offset (std 3)** = the **USDT/USD denomination basis** (Tether trading ~0.16% rich), NOT a fluctuating
  price basis. **[VERIFIED]**

**Why this matters / what the Chainlink layer unlocks:**
1. **It explains why our Binance proxy mostly worked** (and why idea-D "Chainlink basis" was dead): a *constant*
   denomination basis **cancels in the outcome** (strike and final are both in the same denomination, so
   `final ≥ strike` is ~unaffected). **[STRONG INFERENCE]**
2. **The residual, non-cancelling part is the only un-measured corner** — when USDT/USD *moves within the
   5-min window*, or in **near-strike flips** where even a tiny basis decides Up vs Down. That residual is the
   one place the settlement basis could still pay, and **we could not see it until now.** **[HYPOTHESIS — to test
   on forward data]**
3. **Sharper favorite selection** — pick the favorite on the *true* settlement oracle, removing the ~3.6% of
   windows where Binance and Chainlink disagree on the winner. This noise currently dirties the over-round gate
   (our best candidate); cleaning it could matter for a loss-light edge. **[HYPOTHESIS — to test]**
4. **A clean convergence-lag re-test** — the settlement-lag idea died on the *basis*; on the real oracle that
   confound is removed. **[HYPOTHESIS — to test]**

We need ~weeks of forward Chainlink data before any of (2)–(4) can be tested honestly (we have no history; the
collector started logging it 2026-06-27).

---

## 8. What we still DON'T know (open questions)

- The bot's **exact σ estimator** and circuit-breaker thresholds (we measured behavior, not the recipe). **[unknown]**
- Whether it's truly **one** MM or a few coordinated (mirror evidence ⇒ ~one, not certain). **[unknown]**
- The **residual settlement basis** behavior — now measurable, needs forward data. **[unknown]**
- Whether the **over-round gate** survives on fresh data with ≥30 losers (pre-registered, loss-light today). **[unknown]**

## 9. THE SAVED PROGRAM PLAN — component-attack roadmap (saved 2026-06-27)

The plan from §0, written down because **we cannot test all of it now** (the decisive piece is data-gated).
This is the resume point: when forward Chainlink data has accrued, start at Thread B.

**The frame (recap):** the maker's quote `Φ((spot − strike)/(σ·√t))` is its OUTPUT — unbeatable. We attack its
**INPUTS**. We win if we estimate any ONE component better than the maker. String hierarchy: **L0** = predict the
output (walled) · **L1** = compute fair value with a *better input* than the maker · **L2** = predict a
component's *driver* before the maker incorporates it.

**Component-by-component attack status:**

| component | how we'd beat it | testable NOW? | status / thread |
|---|---|---|---|
| time `t` | — (deterministic) | — | **closed** |
| strike | — (frozen at open; = a spot read) | — | tied to the spot feed |
| σ — *average* | trade implied-vs-realized gap | — | **walled** (VRP, self-priced, EV-neutral) |
| σ — *conditional* | catch the moment its σ lags a regime shift, before it re-quotes | tested 2026-06-27 | **Thread A — CLOSED / DEAD** (priced latency-lag + loss-starved; see below) |
| spot / settlement feed | compute fair value on the TRUE Chainlink oracle vs its Binance quote | **harness BUILT; verdict needs forward Chainlink** | **Thread B — OPEN (the only one), data-gated** |

**Thread A — conditional-σ error. DONE 2026-06-27 → DEAD** (`dead_ends/experiment_sigma_lag.py` + `_probe.py`;
POSTMORTEM §1c). Built the causal realized-vol vs implied-σ divergence detector and conditioned favorite-tail
on it. It LOOKED alive (monotone dose-response; `won ~ fav_ask + staleness` coef −0.41, perm-p 0.003, survives
over_round, LOCO all-6, deflates at K=200) but the 3-angle second-mind killed it: **(1)** it decomposes to the
recent-vol numerator, NOT the implied-σ denominator (wrong sign), and IS the already-walled **latency-lag** —
the coef dies/flips against a 15-20s-fresher ask (the continuously-requoting maker has already marked losing
favorites 0.96→0.61 by tl=10; buying at 0.96 = adverse selection), a 3s-wide tl=30 spike, recent_vol adds
nothing beyond raw |move|. **(2)** Loss-starved: the favorite-tail pool has only ~32 losers, so any selective
filter starves below n_loss=30 and can't stack with over-round (Jaccard 0.58, cuts the same losers). **Durable
meta-lesson:** *every loser-cutting filter on the favorite-tail base is INSUFFICIENT by construction until the
loser pool grows past ~90-100 (months more data)* — this is why over-round can't graduate either; stop testing
filters of this shape on favorite-tail.

**Thread A-prime — mechanical σ roll-off, also DONE → DEAD** (`dead_ends/experiment_sigma_rolloff.py`). The one
"predict the maker's string" corner that is *not* the latency-lag: predict its NON-informational σ update (a vol
spike aging out of its trailing window → it re-rates the favorite up) and pre-position. DEAD both ways: (A) hold
= the priced VRP **level** (over_charge coef ≈ 0); (B) the "+1.73% mechanical re-rate" is **~81% an outcome-mix
(Simpson) confound** (`corr(dask, won)=+0.65`; winners-only it collapses to +0.003), the genuine won-orthogonal
piece is **~0.1¢/σ** (sub-economic) AND uncapturable (the re-rate is on the ASK, you exit at the BID; every
round-trip < spread, clairvoyant exit still −0.0027). **Reusable guard:** the favorite ask-change here is
outcome-dominated (corr 0.65) → always control for `won` / measure within-winners before calling a tl-window
ask-rise "mechanical." **The σ component is now FULLY closed** (avg = self-priced VRP; conditional-low = priced
latency-lag; conditional-high / roll-off = priced VRP + confound + exit-walled). The live program reduces to
**Thread B (settlement feed), data-gated.**

**Thread B — settlement-feed component (the ONLY open thread; HARNESS BUILT 2026-06-27, verdict data-gated).**
Step 1 DONE: the maker prices off **Binance** (R²=0.75 vs Pyth 0.0007) but the market settles on **Chainlink**.
**Harness BUILT + structurally validated: `experiment_settlement_basis.py`** (independent-review-hardened: strict
newest-before-decision causal pickers, near-strike gate scaled by causal remaining-move vol, mid dead-bands,
flip-label diagnostic, LOCKED pre-registration). What it confirms on the first ~131 Chainlink-stamped windows:
(1) Chainlink IS the settlement source (`final_cl≥strike_cl` matches official resolved **96.9%** vs Binance 94.7%);
(2) realized **basis-flip rate ~5.3%** (binance-favorite settles the other way on Chainlink) — and in those flips
resolved matched the Chainlink side **5/7**, the Binance side **2/7**, i.e. our captured final-Chainlink tick has
boundary timing-noise, so the LABEL is noisiest exactly where the edge must pay (a real caveat). The trade =
buy the Chainlink-implied side in **near-strike divergence** windows; NOTE it is the maker's **underdog** (ask
~0.35–0.55, fee ~3–4.5%), so it needs a high flip-hit-rate — hence the near-strike gate is essential.
**DATA-GATED:** only ~3 near-strike divergence trades so far → INSUFFICIENT by construction. *Do NOT forget this
thread* — it is the one structurally-open edge; re-run the harness as forward Chainlink accrues (months). The
LOCKED pre-registration + the pre-committed **KILL** (if resolved tracks Chainlink ≤ Binance in flips, or the
selected subset's net-EV CI includes 0 at n_loss≥30) live in the experiment file + memory `settlement-basis-wall`.

**Parked candidate that rides alongside:** the **over-round gate** (§4) — re-gate on fresh data once it has
**≥30 losers**; cleaning favorite-selection with the Chainlink oracle (Thread B step 3) may de-noise it.

**Discipline locked for every thread (no exceptions):** causal only; charge the live fee (`net_ev`); route
through `analysis/stats.assess` (deflated cluster-bootstrap on the net-EV stream, **n_loss ≥ 30**, CI excludes
0); run the **second-mind** adversarial refutation; self-normalize constants per-coin (`analysis/adaptive.py`),
never re-fit a free threshold; pre-register + LOCK params before the OOS read. A loss-light "pass" is noise.

**Map of this chain:** see `maker_chain.html` (open in a browser) — the interactive, editable hierarchy of the
whole Polymarket trading chain (what affects what; height = how upstream/causal; click a node for its role +
equation + our verdict). Edit the `NODES`/`EDGES` block at the top of that file to revise it.

## One-paragraph summary

We trade against a single, competent, automated fair-value market-maker per coin that prices each token as a
digital option `Φ(ln(spot/strike)/(σ√t))` (R²=0.91), pads its volatility ~15% (a variance risk premium),
widens its spread when genuinely uncertain, and defends itself against fast/informed flow by thinning one side
(a circuit-breaker). Every way we tried to exploit it is walled for a coherent reason: it self-prices its
confidence, its one-sidedness is *informed continuation* (never reversion, so providing liquidity is always
adverse-selected), and the taker fee taxes exactly the mid-prices where any edge would live. It makes no
exploitable mistakes. The one genuinely un-mined corner is **not the maker at all** — it's the **settlement
oracle**: the market settles on Chainlink/USD, we proxied with Binance/USDT, and the ~16 bps denomination basis
mostly cancels but leaves a residual (USDT moving intra-window, near-strike flips) we can only now measure with
the freshly-added Chainlink layer.

# Trade the maker, not the asset — what we know about the Polymarket 5-min MM (2026-06-27)

A reframe that emerged this session: every attempt to *predict the coin* is walled (the market is
calibrated). The ONE signal that survived everything (over-round) was not an outcome prediction — it was a
read on the **market-maker's behavior**. So the program pivots: **we are not trading BTC, we are trading a
market-making bot. Our only edges are its model's blind spots and constraints (its vol input, its inventory,
its spread), not information it already has.** "Choose our opponents wisely."

## Who the maker is (mechanics + reverse-engineered model)
- **Market structure:** Polymarket is a CLOB. Settlement = **Chainlink** price at T=0 vs T=300 (Up if end ≥
  start). Chainlink on-chain updates BTC ~every 10–30s / 0.5% deviation; settlement uses the exact-end
  Data-Stream snapshot. Makers earn a rebate. (Sources: Polymarket RTDS docs; CoinMarketCap; a Medium piece
  on 5-min bot strategies / last-second dynamics.)
- **It's ONE synthetic-book bot per coin:** the Up and Down books are exact mirrors (price+size) **75–81%**
  of snapshots → one operator prices the Up token and derives Down = 1−Up.
- **It's a fair-value bot:** `up_mid ≈ Φ(ln(spot/strike)/(σ·√t))` fits with **R² = 0.91** (btc/eth/doge).
  So it responds, overwhelmingly, to **spot−strike, time-decay, and its volatility input σ**. The first two
  we cannot beat (same spot feed, same model — this is *why* directional prediction is walled).

## The maker's two leak dimensions (both reads on the bot, NOT on the coin)
1. **Over-round** = `up_ask + down_ask − 1` = the spread/edge it charges = its **confidence**. Tight → it's
   sure the favorite holds (and it's right: the over-round-gate works, passes joint ask-control p=0.0006).
   Wide → it's nervous (sometimes info, sometimes noise). See `winning_strategies/overround-gate.md`.
2. **σ-error** = its implied σ (backed out of the quote) vs **realized** spot vol = its **model error**.
   - `corr(implied σ, realized σ) = +0.74` → adaptive & competent, but imperfect; it **pads vol ~15%**
     (median implied/realized = 1.15 — a structural risk premium).
   - **`corr(σ-error, over-round) = −0.03` → ORTHOGONAL.** This is the first stack-partner that is BOTH
     low-overlap with the over-round AND ask-independent (the two bars from the additivity-overlap lesson
     that margin/persistence/volume all failed).
   - **Directional, the right way:** when the bot is OVER-cautious (implied σ ≫ realized), it pulls its
     probability toward 0.5 and **under-prices the favorite** → favorite-tail wins more:

     | σ vs realized | n | losers | win% | fav-tail EV |
     |---|---:|---:|---:|---:|
     | over-cautious (1.4–2.2×) | 213 | 4 | 98.1% | **+0.0067** |
     | way over-cautious (>2.2×) | 60 | 1 | 98.3% | **+0.0115** |
     | matched | 444 | 12 | 97.3% | +0.0003 |

     (loss-light, wlb−be still negative; caveat: "realized vol" used window-so-far, a rough proxy for the
     REMAINING flip risk — tighten the vol window in the real test.)

## What this implies / open threads (pick up here)
- **TOP: stack over-round-tight × maker-over-cautious.** Two ORTHOGONAL maker-reads (corr −0.03), both lift
  the favorite-tail. The additivity lesson says a stack works iff the partner is low-overlap AND
  ask-independent — σ-error is the first to be both. This is the best shot at breaking the loss-light wall.
- **σ staleness:** is the bot's σ LAGGING a vol-regime change (predictably stale) so we know *in advance*
  when it's about to be wrong? (vs just measuring it contemporaneously.)
- **Inventory skew (the 9% residual):** R²=0.91 leaves 9% where the quote deviates from spot-fair-value —
  inventory + the ~1s lag + tick. Does net taker flow push the quote OFF fair value and then REVERT? That's
  the contrarian, maker-harvestable seam (idea #1 taught us makers anti-select CONTINUATION signals; only a
  CONTRARIAN/reversion signal is maker-fillable — inventory-skew reversion is exactly that shape).
- **Idea #1 result (fear-FOLLOW as maker) = FAILED, but taught the law:** a fee-free maker entry can only
  harvest a CONTRARIAN signal; fear-FOLLOW is informed-CONTINUATION, so the maker fill anti-selected it
  (taker win 59.4% → maker win 46.1%). See `experiment_fear_maker.py`.

## Cost map (always: pick the cheap corner of the bot)
Taker fee `0.07·(1−p)`: ~0.2% at p=0.97 (favorite tail — cheap), ~3.5% at p=0.5 (mid — brutal). Maker =
fee-free + capped rebate but adverse-selected EXCEPT in over-round-tight windows (the one non-adverse fill
found). So: directional edges live at HIGH p (cheap fee); reversion/inventory edges want the MAKER entry in
CALM windows.

Scripts: `experiment_fear_maker.py` (idea #1), the σ/fair-value reverse-engineering (one-off probes — fold
into an `analysis/maker_model.py` when we build the stack). Next deliverable: the over-round × σ-error stack.

## UPDATE 2026-06-27 — VRP audit, external research, circuit-breaker (all rigor-gated/second-mind validated)

**VRP / σ-error harvest — OVERFIT, mined out.** Built `experiment_vrp_harvest.py` (buy favorite when the bot
over-charges vol = implied σ ≫ trailing realized = a Variance Risk Premium harvest, a documented 0DTE edge).
Audit: non-stationary (works 1 of 3 time-folds), **EV-neutral vs random** (loss-rate p=0.013 but EV p=0.30 —
the bot prices its own confidence into the ask), loss-light, same latent as over-round (20 overlapping losers).
DEEP LESSON: **the bot self-prices its vol-confidence, so over-round/VRP/σ-error are ONE mined-out signal.**
The genuinely different opponent is INVENTORY/DEPTH, which needs L2.

**External research (workflow wf_0fbc5840, 13 agents) — we are STRICTLY AHEAD of the public frontier.** The
two traders (Patange, BenjaminCup) never reverse-engineered the maker (no fair-value model / hardcoded σ);
they quit from FATIGUE/optimism, not proof; two real MM operators got walled by adverse selection + queue
opacity. Gold findings: (1) **MM vol CIRCUIT-BREAKER + hysteresis-cancel** (warproxxx/poly-maker) — freezes/
goes one-sided ~10s on vol spikes; (2) **Chainlink settlement is PUBLIC over WS** `wss://ws-live-data.polymarket.com`
`crypto_prices_chainlink` (dissolves the Data-Streams-auth blocker!); (3) **Polymarket `side` field is only
~59% accurate** (arXiv 30B ticks) = why every flow/CTAP signal came out ~0 (rebuild flow from price+size
deltas, NOT `side`); (4) inventory skew is in **DEPTH asymmetry at ±1c (`overall_ratio`)**, not the mid.

**Vol circuit-breaker — TAKER leg fee-walled, MAKER leg deferred to L2** (`experiment_vol_circuit_breaker.py`,
second-mind a12112dc). Both taker directions die to the fee (momentum −0.060, contrarian −0.087); the freeze
is NOT visible at 1/s; BUT the 1/s up_book/down_book ladders show the footprint (favored-side depth ~halves,
ask/bid ratio 0.98→0.90 in the spike cell). The fee-free MAKER leg (rest the abandoned-side quote) is the
untested corner → needs the L2 build.

**Inventory-skew existence probe (n=48k):** flow (via `side`) does NOT push the mid off fair-value reverting
(coef ≈0) — but `side` is 59% noise AND inventory lives in DEPTH not mid, so the snapshot/side view is BLIND
to it. Confirms the L2 dimension is structurally necessary.

**NEXT (decided): build the L2 capture** — add depth one-sidedness (`overall_ratio`), the fair-value residual,
and the Chainlink settlement WS as LAYERS on the existing per-coin collectors/DBs (not separate DBs). Then
test the fee-free maker circuit-breaker + inventory-reversion on the accumulated L2 stream. See memory
`trade-the-maker`. Bottleneck reminder: everything is loss-light (~38 favorite-tail losers) — L2 capture also
accumulates the data we're starved on.

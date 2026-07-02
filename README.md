# Is there a retail edge in Polymarket's 5-minute crypto markets?

*A research program by **Roie Itzhakov***

**Answer, after a full research program: NO — and this repo is the honest proof.**

This is a complete, self-contained quant research program on Polymarket's *"Bitcoin (and ETH/SOL/XRP/DOGE/BNB) Up or Down — 5 minute"* markets: a purpose-built high-frequency data collector, ~40 experiment harnesses, a proper statistical rigor module, and the final verdict — **the market is walled for retail takers**. Every candidate edge fails an honest test once you charge the verified live fee, respect the −100%-on-miss binary payoff, deflate for the hundreds of configurations tried, and use the effective (clustered) sample size.

We are publishing the *negative* result on purpose. Almost nobody does, which is exactly why so many people keep re-losing money on the same ideas. If you are thinking about trading these markets — or building a bot for them — the tables below are the several months of work you don't have to repeat.

> **One-line verdict:** the product is a near-efficient casino with a built-in house edge, not a venue where prediction skill converts into profit. The signal is real; it is *pre-priced and fee-taxed* out of reach. Full argument: [`VERDICT.md`](VERDICT.md).

---

## The headline results

Every candidate, through the corrected statistical gate (`analysis/stats.assess`: fee-aware net EV, window-clustered bootstrap, multiplicity-deflated, ≥30 losers required):

| Candidate strategy | n | mean net-EV / $1 | deflated p | Verdict |
|---|---:|---:|---:|---|
| **Favorite-tail taker** (buy the ≥0.95 favorite, hold) | 1849 | −0.0029 | 1.00 | FAILS — looked "breakeven" for weeks; 4/6 coins negative |
| **Cross-asset (BTC-lead) risk filter** | 449 | −0.0019 | 1.00 | FALSIFIED — the alt's *own* momentum explains it entirely |
| **Token-fear FOLLOW** (buy Down on an informed dump) | 599 | +0.024 | 1.00 | Signal **real at the mid** (+0.052, p=0.008, all 6 coins) — killed by spread + fee |
| **Maker in noise windows** (fee-free + rebate) | 2254 | −0.365 | — | DEAD — mechanical adverse selection; your bid fills exactly when you're wrong |
| **Residual market-neutral basket** | 34 | −0.092 | 1.00 | FAILS — pays the taker fee twice |
| **Reversion (dip / peer-surge / spike-fade)** | — | ≤ 0 | 1.00 | DEAD — the "panic" was correct repricing, not fear |
| **σ-staleness / vol-lag / skew model-form** | — | ≤ 0 | 1.00 | DEAD — priced latency-lag + outcome-mix confounds |
| **Spot cross-asset lead-lag** (5.5 yrs, 575k windows/coin) | 575k | — | — | Predictor is REAL (r≈+0.12, 100% sign-stable) — and fully priced in the quote |

Full evidence trail with every number: [`POSTMORTEM.md`](POSTMORTEM.md). Full chronological lab log: [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).

## Why the market is unbeatable (for a retail taker)

Four structural walls, measured — not assumed:

1. **A fair-value market-maker is home.** One bot quotes both sides as a digital option `Φ(ln(spot/strike)/(σ√t))` off the public Binance feed at **R²=0.91**, requoting sub-second. The Up and Down books are one synthetic mirror (down ≈ 1−up in 75–81% of snapshots). Every public predictor — trend, momentum, cross-asset lead — is already in the price: the outcome is *predictable* (BTC's 15s move correlates ~+0.4 with the result) but the *residual* (outcome − price) is ~0. Predicting reality ≠ beating the price.
2. **The fee is calibrated to the edge.** The verified live taker fee `0.07·p·(1−p)` per share (~3.5% of stake at p≈0.5) was introduced by Polymarket *explicitly* to neutralize the latency arbitrage bots had been extracting. The one real inefficiency we measured — a ~1s quote lag worth ~+0.6%/$1 per second — lives exactly where the fee bites hardest. This is Grossman-Stiglitz efficiency in the wild: the residual is sized to the cost of harvesting it.
3. **The payoff is −100% binary.** Each market resolves 0 or 1 every 5 minutes (~288 spins/day/coin). The return stream is severely negatively skewed (favorite-tail skew −6.8), so the sample mean lies: a "+0.5% breakeven" is mildly negative once the tail is priced.
4. **The only non-taker role is a trap.** The maker rebate is capped ~0.4%/$1 and resting bids are adverse-selected by construction (Glosten-Milgrom): modeled fill-conditional EV was **−0.365/$1** — with an *optimistic* fill model.

The interesting nuance: this makes the product **skill-proofed, not skill-less** — the roulette analogy and where it breaks is worked through in [`VERDICT.md`](VERDICT.md).

## How we fooled ourselves (and got caught)

The difficulties were not data plumbing — they were statistical self-deceptions. Every one of these looked like a real edge at first:

| The mirage | What it really was |
|---|---|
| "+0.08 residual, 97.7% win, p=0.006" — the strongest result of the whole program | Loss-light sample + convergence + look-ahead. Died with more data. |
| Favorite-tail "breakeven, +0.005/$1" | <30 losers → degenerate CI. Regressed to −0.0029 as losers accrued. |
| B-filter "first real cross-asset signal, permutation p=0.002" | Best-of-N mining + a confound: the alt's own momentum gated strictly better than BTC's. |
| Maker corner "0 fills — cell empty" | A **gate bug** in our own harness. Fixed, the cell populated with 2254 fills at −0.365 — a *stronger* kill. |
| σ roll-off "+1.73% mechanical re-rate" | ~81% Simpson's-paradox outcome-mix: winners' asks march to 1 mechanically. Winners-only: +0.003. |
| "13 fills, +$1.18/fill, 92% win" | All bunched in ~40 minutes = one regime, ~4 effective observations. |
| Sign-flipping per-coin EV between runs | The Binance-vs-Chainlink settlement basis flips ~5% of boundary outcomes — label noise bigger than the candidate signals. |

The catalog of these traps — loss-light CIs, multiplicity, priced-variable confounds, adverse selection, outcome-conditioned exits, settlement-proxy noise — plus the checks that catch each one, is distilled in [`FIELD-NOTES.md`](FIELD-NOTES.md). If you read one file, read that one: it transfers to any data-driven, adversarial, cost-bearing decision problem, not just this market.

## The durable asset: the method

The negative result is not what this repo is for. The **method** is:

- **[`analysis/stats.py`](analysis/stats.py)** — the rigor gate every idea must pass: fee-aware net-EV residual test, window-clustered bootstrap CI, Šidák deflation for the honest program-wide trial count, PSR/DSR for the negative skew, and a hard `n_loss ≥ 30` floor (below it the verdict is INSUFFICIENT, never a pass).
- **The second-mind protocol** — every positive result gets an independent adversarial pass whose only job is to refute it. It killed candidates that survived p=0.002 permutation tests, and twice caught bugs in our own rigor tooling.
- **The fair-value-maker detector** — the single check that would have saved the whole year: regress the venue's mid on a public fair-value reference and time the requotes. R² > 0.85 + sub-second requoting = a maker is home = the venue is walled for you. Minutes to run, on free data, before building anything.
- **The two-stage validation split** — "does the signal EXIST" (testable deep and cheap on years of free spot data) vs "does it BEAT the quote + fee" (only scarce live capture answers). Never let stage 1 stand in for stage 2.

## Repository map

| Path | What's in it |
|---|---|
| [`VERDICT.md`](VERDICT.md) | **Start here.** The final verdict + the casino-structure analysis |
| [`POSTMORTEM.md`](POSTMORTEM.md) | Every candidate through the corrected gate, with numbers |
| [`FIELD-NOTES.md`](FIELD-NOTES.md) | The transferable principles (discovery, rigor, microstructure, process) |
| `collector.py`, `ws_collector.py`, `supervisor.py`, `storage.py`, `feeds.py`, `coins.py` | The **data collector**: hybrid WebSocket + REST capture of all 6 coins' order books, trades, and spot feeds into per-coin SQLite |
| `analysis/` | The rigor module (`stats.py`), fee-aware EV, calibration, fair-value, exit maps, the deep spot-history store, the lead-lag harness |
| `experiments/` | The on-market experiment harnesses (favorite-tail, maker-noise, over-round gate, settlement basis, …) |
| `dead_ends/` | Proven-dead experiments, archived with *why* they died |
| `ideas_old/` | Parked ideas — real-but-fee-capped, each with a written revisit trigger |
| `winning_strategies/` | The honest tiered roster (Tier 1 "deployable winner" = **empty**, by design) |
| `execution/` + `exec_engine/` | The gated executor (paper + live scaffolding). **Never armed** — no edge cleared validation |
| `side_quests/` | The same rigor applied elsewhere: Kalshi favorite-longshot scout, NQ/ES SMT break test, whale copy-trading tests (all dead too) |
| `docs/` | The full session logs: lab notebook, idea audits, external research sweeps, maker-model reverse-engineering |

## The collector (reusable even if you disagree with the verdict)

The capture infrastructure is solid, standalone, and still running daily. Stdlib-only REST collector + a `websockets`-based CLOB market-channel recorder, per coin, with auto-restart supervision:

```sh
pip install -r requirements.txt     # just `websockets`
python supervisor.py                # collector + ws_collector per enabled coin + live viewer
python peek.py --coin eth           # inspect a coin's DB
ANALYSIS_COIN=sol python -m analysis.fairvalue   # any analysis, scoped per coin
```

Each coin writes `data/<coin>/live.db` (SQLite): per-window strike/final/official-resolution rows, 1/s odds snapshots with top-10 depth, and the full order-book event stream (`book`/`price_change`/trade prints) plus Binance bookTicker ticks. The slug **is** the window-start timestamp, so market discovery is pure arithmetic — no scraping. Note the WS stream is high-volume (tens of GB/day/coin raw; 3-day retention on the bulky tables by default).

## What would change the verdict

Re-open only on a concrete trigger, never on a hunch:

1. **Materially lower fees**, or a demonstrably fee-free maker path that beats adverse selection.
2. **Months more data** — the binding constraint everywhere was the loser count (8–36). The pre-registered, params-locked candidates re-gate when losers ≥ 30–50; only a *deflated* pass counts.
3. **A Chainlink settlement adapter** (the markets settle on Chainlink; we captured Binance/Pyth proxies) — removes the boundary label-noise that currently swamps marginal signals.
4. **A different product** — the real path. A venue with a weak counterparty, an un-priced signal, a fee that doesn't tax the edge out, or a role other than "bettor against the house."

---

## Author & license

**© 2026 Roie Itzhakov.** I stand behind every claim in this repository — the measurements, the methodology, and the verdict.

This work (the research, documents, data-collection code, and experiment harnesses) is licensed under [**Creative Commons Attribution 4.0 International (CC BY 4.0)**](LICENSE): you are free to share, adapt, and build on it — including commercially — **provided you give appropriate credit to Roie Itzhakov**, link to the license, and indicate if changes were made.

*Built with Claude Code across ~40 experiments and several second-mind adversarial reviews. The edge may not exist — the discipline that tells you so, cheaply and honestly, is the thing worth keeping.*

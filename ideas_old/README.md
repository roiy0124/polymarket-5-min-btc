# ideas_old/ — explored & parked ideas (preserved, not thrown away)

Ideas we **tested to a conclusion** and shelved — kept here with their full verdict and the
code that produced it, so we never re-run them from scratch or forget *why* they were parked.

How this differs from the neighbours:
- **`../IDEAS.md`** — the *forward* backlog (ideas to try). This folder is the *backward* archive (ideas already tried).
- **`../dead_ends/`** — proven-**dead** experiment code (no signal / overfit artifacts).
- **`ideas_old/`** — ideas where there *was* something real but it didn't reach the deployment bar (usually fee/spread-capped). Worth revisiting if conditions change (fees drop, spreads tighten, more data).
- **`../winning_strategies/`** — the active roster (Tier 1–3).

Each idea = one `.md` (thesis + verdict + revisit-conditions) + its experiment script. Scripts add a
`sys.path` shim to the repo root so they still run in place: `python ideas_old/<script>.py`.

## Index
| Idea | Verdict | Revisit if |
|---|---|---|
| [Fear stock-sell (stock-vs-stock)](fear-stock-sell.md) — `experiment_token_fear.py` | Fade DEAD (dump is informed, not fear); FOLLOW real all-coin residual +0.055 but **fee-capped** (net +0.02, placebo p=0.19, Wilson<be) | fees drop / spreads tighten / a larger-residual subset survives OOS |
| [Open-imbalance overreaction fade](open-imbalance-fade.md) | DEAD — open price already calibrated at tl≈280 (slope 1.04, no overshoot); efficient 20s in | sub-second open-flow shows a transient overshoot that reverts + fee drop |
| [Whale / large-print follow-through](whale-followthrough.md) | DEAD — whale direction doesn't predict beyond the mid (signed resid −0.002); big flow priced like avg flow | sub-second data shows the whale print leads the mid by an uncaptured lag |
| [Spot-margin gate + favorite-tail STACK](spot-margin-stack.md) — `experiment_favtail_stack.py` | Margin is a REAL independent flip-predictor, but stacking on the over-round gate adds **zero** tradable EV (Δ+0.0005, P=0.52) — cuts the SAME losers (Jaccard 0.45) | a forward signal that cuts DIFFERENT losers (low Jaccard) than over-round appears |
| [Sub-second spot staleness](subsecond-staleness.md) | Real sub-second lead at the mid (resid +0.026, raw-p=0.05) but **fee-capped** (win 56.6% < be 57.3%); confirm-gate on favorite-tail also failed (−0.005) | fees drop materially (residual already clears a smaller cost) |
| [Favorite persistence gate](favorite-persistence.md) | DEAD-CONFOUND — looked like the low-Jaccard (0.48) stack partner but is a PROXY for the ask; fails joint ask-control (74%/p=0.21 vs over-round 98%/p=0.003); within-ask-bin sign-inconsistent | a persistence-like signal demonstrably orthogonal to the ask is built |
| [Favorite-longshot bias / full calibration](favorite-longshot-bias.md) | NO BIAS — market calibrated on the MID across the whole curve; every band realizes below its ask (half-spread); no +EV band | an uninformed longshot-buyer cohort appears (undetectable now) |
| [Dynamic loss-stop exit (over-round trigger)](dynamic-loss-stop-exit.md) | HURTS — over-round widening predicts flips (20% vs 3%) but 80% of stressed favorites RECOVER, so exiting locks losses on winners; Δ −0.021 vs hold (CI excl 0) | a >~50% conditional-flip trigger is found (e.g. sub-second strike cross) |
| [Settlement-convergence lag](settlement-lag.md) — `experiment_settlement_lag.py` | DEAD — looked +EV (CI excl 0) but is a margin cherry-pick (ungated −0.0015, deflated p=0.89) and BASIS-flip dominated: favorite on Binance, settles on Chainlink; Pyth disagrees 2.79% > the 1.24% the edge needs. Dual-oracle (Binance+Pyth-agree) fix ALSO DEAD: losers are Pyth-agreed CHAINLINK flips | a **Chainlink price adapter** replaces the proxy (a 2nd proxy can't fix a tail in the settlement oracle) |
| [Cross-window return momentum](cross-window-momentum.md) | DEAD — faint mean-reversion (corr −0.01..−0.04) already priced into the next window's open (residual ~0); too small vs the near-0.5 fee | a larger sign-stable residual emerges (unlikely) or fees drop |

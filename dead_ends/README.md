# dead_ends/ — proven-not-working experiments (archived record)

These experiments were measured and **killed**. They're kept as a record (so we don't re-try them
and so the verdicts stay reproducible), out of the main directory. Full write-ups live in
`../EXPERIMENTS.md` and agent memory. **Nothing here is part of the live strategy.**

The live strategy + its tooling stay in the repo root: `experiments/experiment_favorite_tail.py` (the chosen
breakeven strategy), `experiments/experiment_b_component.py` (the one live thread — the BTC-opposing risk-filter),
`net_ev.py` (fee-aware accounting), `experiments/validate_b_riskfilter.py` (the locked re-test).

## What's here and why it died
| script | what it tested | verdict |
|---|---|---|
| `experiment_walkforward.py` | passive resting-limit, walk-forward OOS, EV-scored signals refreshed 30min, real-trade-print fills (**shared lib**: `open_merged`/`replay_leg`/`generate_signals`) | **−0.31 EV/fill pooled across 6 coins** — adverse selection. Dead. |
| `experiment_combined.py` | two screens (exit-line AND gap-response) ANDed (**shared lib**: `load_full`) | ~breakeven; sometimes worse than parts. Dead. |
| `experiment_config_tod.py` | brute-force 20 configs (base/nest × lookback combos) × time-of-day + train/test holdout | every coin's best config **FAILS OOS**; nested "+0.02" was a guard artifact. Dead. |
| `experiment_lookback_sweep.py` | 3-lookback robustness gate, baseline vs nested | passive nested ≈ breakeven. Dead. |
| `experiment_trend_outcome.py` | does recent BTC trend predict the outcome **beyond the price**? residual test | trend predicts outcome but **residual ≈ 0** at all 15 cells — market efficient on knowledge. Dead. |
| `experiment_drift_fairvalue.py` | the PRINCIPLED version of "predict the future near-trend value vs the maker's driftless quote": a drift-augmented fair value `Φ(z + μ̂√t/σ)` vs `up_mid`, joint-control residual test (2026-06-28 user pivot) | **walled, robust across a 6-cell tl×drift-window grid**: corr(signal, won−mid) ≈ 0 (−0.033..+0.014); the drift coef **COLLAPSES given the mid** every cell (mid coef ~+2.1 carries all the info); directional trade **−0.02..−0.13/$1** (no edge AND it lives at ask≈0.5, peak-fee zone). The maker already prices the near-trend = efficient-on-knowledge. The maker's own quote BEAT our drift equation → use it as a tool (Outcome 2), don't fight it. Dead. |
| `experiment_lookahead_taker.py` | faster-feed taker; lead-lag + clairvoyant-Δ EV | BTC leads ~1s (real) but **net −0.002…−0.004 after the real 0.07·p·(1−p) fee**. Spread/fee-capped. Dead. |
| `experiment_xasset_smt.py` | cross-asset convergence existence (gap → forward return) | convergence corr ~0.02–0.03, single-coin (doge), CI≈0. Dead **as a convergence trade** (superseded by the risk-filter framing in `../experiment_b_component.py`). |
| `experiment_favtail_selectivity.py` | favorite-tail score selectivity (fair_P−ask terciles/margins) | HIGH vs LOW borderline; **fails OOS holdout** (3/6 coins invert). Dead. |
| `experiment_favtail_adaptive.py` | adaptive consistency-weighted score cutoff (walk-forward) | **+0.0038 ≈ baseline**; in-sample oracle +0.0133 = overfit/look-ahead. No improvement. Dead. |
| `experiment_sigma_lag.py` | conditional σ-lag: does the maker's σ go stale after a vol jump → favorite-tail filter? joint ask-control + adaptive + monitor (Thread A of the maker-component program) | signal real-at-mid (`won~ask+staleness` coef −0.41, perm-p 0.003, LOCO all-6, deflates at K=200) but it **IS the walled latency-lag** — coef dies/flips vs a 15-20s-fresher ask (loser favorites already marked 0.96→0.61 by tl=10), recent_vol adds nothing beyond raw \|move\|, 3s-wide tl=30 spike. Loss-starved (32 losers → can't reach n_loss≥30; can't stack w/ over-round, Jaccard 0.58). **Dead** (POSTMORTEM §1c). |
| `experiment_sigma_lag_probe.py` | adversarial decomposition of the above (recent-vol vs implied-σ; exclude-immediate-15s; LOCO; loss concentration) | showed the "stale σ" story is the recent-vol **numerator**, not the implied-σ denominator (wrong sign) ⇒ it's recent-vol continuation = priced. Refutation tool. |
| `experiment_sigma_rolloff.py` | mechanical σ roll-off: predict the maker's NON-informational σ update (a vol spike aging out of its window → it re-rates the favorite up) and pre-position | DEAD both ways. (A) hold = the priced VRP **level** (over_charge coef ~0). (B) the "+1.73% mechanical re-rate" is **81% an outcome-mix (Simpson) confound** — `corr(dask,won)=+0.65`; winners-only it collapses to +0.003 (CI spans 0); the genuine won-orthogonal piece is **~0.1¢/σ**, sub-economic AND uncapturable (re-rate lives on the ASK, you exit at the BID; every round-trip < spread, clairvoyant exit still −0.0027). Closes the "predict the maker's σ string" corner (POSTMORTEM §1c). |
| `experiment_skew_residual.py` | conditional-SKEW model-FORM residual — the ONE testable lead from the field-research program (Field A⊗B): true digital = Φ(d2) − vega·dσ/dK, so the symmetric Φ omits a 3rd-moment skew term; trade the per-coin causal trailing-skew terciles (buy Up in most-negative-skew, Down in most-positive) at tl=30, ATM band. joint-control + dose-response + net-EV gate + LOCO + second-mind | **DEAD — the maker prices the skew.** Moment skew (primary): coef +0.002, perm-p 0.52, corr(skew,resid) −0.001, net-EV **FAILS** (n=861, **n_loss=412** — a real verdict, win 52.1% vs 54.4% BE, deflated p=1.0). Robust(Bowley) skew: a faint theory-signed whiff (coef −0.156, perm-p 0.003) but **BTC-concentrated + coin-INCOHERENT** (sol/xrp sign-reversed, dies under multiplicity) and STILL fee-capped (50.5% vs 53.9% BE). Second-mind: **0/40 deflated grid cells survive**; sharper intraday-spot skew has the WRONG sign (crypto inverse-leverage); no look-ahead bug; flip is worse; ATM maker = the walled −0.365 toxic zone. The absorbable, fee-capped half = Grossman-Stiglitz "residual sized to the fee" (docs/RESEARCH-EXTERNAL.md "PHASE 1"; POSTMORTEM §1d). |

(The dead executors for the passive/nested idea — `../phase2.py`, `../phase2_nested.py`,
`../paper_trade.py` — stay in root because `menu.py` launches them; `execution/phase2_nested.py` bridges to the
shared libs here. The dead `analysis/` tools — `fair_vs_market.py`, `backtest.py`, `combo_ev.py`,
`reversion.py` — stay in the `analysis/` package since they share `panel.py`; their verdicts are in
`../EXPERIMENTS.md`.)

## Running an archived script (rarely needed — they're dead)
They import repo-root modules (`coins`, `analysis`, `exec_engine`) and some import each other, so run
from the repo root with both paths visible:
```sh
PYTHONPATH=.:dead_ends python dead_ends/experiment_config_tod.py --coin eth
```

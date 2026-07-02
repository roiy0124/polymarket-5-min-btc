# experiments/ — the on-market experiment harnesses

Each file is a self-contained, **causal** (no look-ahead) test of one candidate edge on the live-collected
token data, routed through the rigor gate (`analysis/stats.assess`) and charged the verified taker fee
(`net_ev.py`). Verdicts live in [`../POSTMORTEM.md`](../POSTMORTEM.md); the chronological story in
[`../docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md). Proven-dead ancestors are archived in
[`../dead_ends/`](../dead_ends/); parked real-but-fee-capped ideas in [`../ideas_old/`](../ideas_old/).

Run from anywhere — each script carries a repo-root `sys.path` shim: `python experiments/<script>.py`.

| Harness | Candidate | Verdict |
|---|---|---|
| `experiment_favorite_tail.py` | Buy the ≥0.95 favorite, hold to resolution | FAILS (−0.0029/$1; was "breakeven" loss-light) |
| `experiment_overround_gate.py` | Gate favorite-tail on tight over-round (makers' revealed calm) — **the template**: candidate + joint-control + adaptive + monitor | INSUFFICIENT (loss-light), pre-registered |
| `experiment_b_component.py` / `validate_b_riskfilter.py` | BTC-opposing cross-asset risk filter (locked validation harness) | FALSIFIED (own-momentum confound, CHECK 5) |
| `experiment_maker_noise.py` | Fee-free maker bid in mid-price noise windows | DEAD (−0.365/$1 adverse selection) |
| `experiment_maker_timemap.py` | Where in the window is maker-fill EV least bad | DEAD everywhere |
| `experiment_residual_basket.py` | Cross-coin market-neutral residual basket | FAILS (pays the fee twice) |
| `experiment_fear_dip.py` / `_variants.py` / `experiment_fear_maker.py` | Reversion after dips / peer-surge / maker-entry variant | DEAD (dump is informed) |
| `experiment_spike_fade.py` / `experiment_idio_spikes.py` | Fade lone idiosyncratic spot spikes | DEAD (no dose-response) |
| `experiment_hybrid.py` / `experiment_favtail_stack.py` | Stacking the surviving gates | Additivity fails (same losers, Jaccard 0.45+) |
| `experiment_settlement_basis.py` / `experiment_settlement_lag.py` | Binance-vs-Chainlink settlement basis / convergence lag | DEAD (margin cherry-pick; proxy disagreement > edge) |
| `experiment_vrp_harvest.py` | Harvest the maker's vol padding | DEAD (self-priced) |
| `experiment_vol_circuit_breaker.py` | Maker pulls quotes on vol spikes → gap | DEAD (one-sidedness predicts continuation) |
| `experiment_midround_exit.py` | Mid-window exit timing maps | No positive exit exists (hold dominates) |
| `phase0_fit.py` | Reverse-engineer the maker's Φ pricing model | R²=0.91 — the wall itself, quantified |
| `correlation_lab.py` | Cross-coin correlation structure (outputs `correlation_lab/`) | Descriptive (feeds Neff in the gate) |

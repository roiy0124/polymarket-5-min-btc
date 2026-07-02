# Data-Analysis Toolkit — How to Get Reliable Results (Not False Positives)

A cited, practical reference for validating any signal/strategy hypothesis on the
collected data **without fooling ourselves**. From a deep-research pass
(2026-06-19): 25/25 claims 3-vote verified, 0 refuted. Apply this to every study
in ANALYSIS.md / STRATEGY-MEAN-REVERSION.md.

## The one rule that matters most

**Track and report the number of strategy/feature variants you try (N).** A
backtest that hides its search "is worthless regardless of how excellent the
reported performance might be" [López de Prado/Bailey, SSRN 2460551]. The expected
*maximum* Sharpe across N independent noise trials grows with N **even when true
skill is zero** (the *False Strategy Theorem*) — so the best-looking config out of
many is usually luck. Every entry-price / exit-target / time-filter / toxicity
threshold we sweep counts toward N.

## 1. Significance & multiple testing
- A 95% test bounds false positives at 5% **for a single test**; run it many times
  and false positives become near-certain [SSRN 2326253].
- Single-test hurdle **t > 2.0 is wrong** after multiple testing; use **t > 3.0**
  as a defensible floor [Harvey-Liu-Zhu, NBER w20592]. *(Caveat: Chen et al. argue
  this is too conservative for a small search — so scale the hurdle to how many
  variants you actually tried, and always report N.)*
- Control error with **FWER** (prob. of ≥1 false discovery; strict) or **FDR /
  Benjamini-Hochberg** (expected proportion of false discoveries; more powerful).
  `statsmodels.stats.multitest.multipletests(pvals, method="fdr_bh")`.
- **Deflated Sharpe Ratio (DSR)** — deflates an observed SR using 5 inputs: skew,
  kurtosis, sample length T, variance of the SRs tested, and N trials [SSRN 2460551].
- **PBO (Probability of Backtest Overfitting)** via **CSCV** — the chance the
  in-sample-best config underperforms the median config out-of-sample.

## 2. Validation that doesn't leak (time-series data)
- **Never use iid k-fold** — it trains on the future and tests on the past, and
  leaks across autocorrelated/overlapping labels.
- **`sklearn.model_selection.TimeSeriesSplit(n_splits=k, gap=g)`** — expanding
  walk-forward; the **`gap`** excludes samples between train and test as a buffer
  (our labels span a 5-min window, so set a gap ≥ the label horizon).
- **CPCV (Combinatorial Purged CV)** — purges training rows whose label interval
  overlaps the test set, applies an **embargo**, and yields **many backtest paths**
  (not one), enabling PBO/DSR. Ref impl: `mlfinlab` `CombinatorialPurgedKFold`
  (now paid) → use the open **`skfolio` `CombinatorialPurgedCV`** instead.
- **Walk-forward across many independent OOS periods**, with realistic costs and
  strict information-set discipline (features use only past-available data)
  [arXiv 2512.12924].

## 3. Robust statistics & resampling (fat-tailed data)
- Mean & SD have a **0% breakdown point** (one outlier wrecks them); the **median /
  MAD** have a **50% breakdown point** — prefer them for location/dispersion and
  outlier flags [Leys 2013]. `scipy.stats.median_abs_deviation`.
- **Robust standard errors**: HC0–HC5 (heteroskedasticity) and **HAC/Newey-West**
  (serial correlation) change SE/CI/p-values but **not** point estimates — naive SEs
  give false significance on autocorrelated returns.
  `statsmodels` OLS `.fit(cov_type="HAC", cov_kwds={"maxlags": L})`.
- **Bootstraps for serially-correlated series** (the `arch` library):
  `arch.bootstrap.StationaryBootstrap` / `CircularBlock` / `MovingBlock`
  (+ `optimal_block_length`) for CIs; and **data-snooping tests** `SPA`
  (Reality Check), `StepM`, `MCS` when comparing many variants.

## 4. Calibration & probabilistic eval (binary Up/Down outcomes)
*(Sources found; verify APIs against installed versions.)*
- **Brier score** `sklearn.metrics.brier_score_loss`; **log-loss** `log_loss`.
- **Reliability diagram** `sklearn.calibration.calibration_curve` — predicted prob
  vs realized frequency (the core "is the market's Up price calibrated?" test).
- **Recalibrate** with `CalibratedClassifierCV` (Platt / isotonic).
- Calibration matters more than accuracy when you trade on the *probability* (we do).

## 5. The concrete toolchain (library → use)
| Need | Library / function |
|------|--------------------|
| dataframes, EDA | `pandas`, `numpy` |
| basic stats, MAD, bootstrap CIs | `scipy.stats` |
| OLS + robust/HAC SEs, ADF & variance-ratio stationarity, ACF/PACF | `statsmodels` |
| walk-forward CV | `sklearn.model_selection.TimeSeriesSplit(gap=...)` |
| purged/combinatorial CV (CPCV) | `skfolio` (open) / `mlfinlab` (paid ref) |
| block/stationary bootstrap, SPA/StepM/MCS | `arch.bootstrap` |
| GARCH / realized volatility | `arch` |
| calibration, Brier, reliability | `sklearn.calibration`, `sklearn.metrics` |
| multiple-testing correction | `statsmodels.stats.multitest` |
| plots/diagnostics | `matplotlib` (+ `plotly` optional) |
| reproducibility | fixed seeds, pinned versions, versioned data |

## 6. Honest end-to-end checklist
1. **Pre-register** the hypothesis and the exact entry/exit/filter rule before looking.
2. **EDA** on a *throwaway* slice; don't let it silently become your test set.
3. **Build features with no look-ahead** (only past-available data; beware
   resample/rolling functions that peek; align label horizon).
4. **Walk-forward / CPCV** with a gap ≥ label horizon; realistic fees, $5 min,
   0.01 tick, and the adverse-selection fill cost (see STRATEGY-MEAN-REVERSION.md).
5. **Count N** (every variant tried) and apply **DSR / PBO / FDR**; clear **t > 3**.
6. **Robust SEs** (HAC) and **block-bootstrap CIs**, not naive ones.
7. **Calibration** (reliability diagram, Brier) for the probability outputs.
8. **Robustness/sensitivity**: does the edge survive small parameter changes,
   different regimes (day/night), and higher costs? If it only works in one cell,
   it's overfit.
9. **Size** with fractional Kelly on the *deflated* edge; check risk of ruin.

## Open questions to resolve when building (from the research)
- Exact **embargo/purge length** for our 5-min overlapping labels, and the **N** to
  feed DSR.
- Calibration specifics (Platt vs isotonic; Brier decomposition into
  reliability/resolution/uncertainty).
- Which `statsmodels` stationarity tests (adfuller, variance-ratio) best fit tick data.

## Key sources
- Backtest overfitting / PBO / CSCV: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Deflated Sharpe / False Strategy Theorem: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- t>3.0 multiple-testing hurdle: https://www.nber.org/system/files/working_papers/w20592/w20592.pdf
- CPCV reference impl: https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/cross_validation/combinatorial.py
- TimeSeriesSplit (gap): https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- arch (bootstraps + SPA/StepM/MCS): https://github.com/bashtage/arch
- MAD / breakdown point: https://dipot.ulb.ac.be/dspace/bitstream/2013/139499/1/Leys_MAD_final-libre.pdf
- Walk-forward microstructure framework: https://arxiv.org/pdf/2512.12924
- sklearn calibration: https://scikit-learn.org/stable/modules/calibration.html

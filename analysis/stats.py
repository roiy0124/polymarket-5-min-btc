"""Rigor module — the lens every candidate must pass through (MOVE 1).

The program's #1 blind spot (quant-panel verdict 2026-06-25): we ran HUNDREDS of effective
trials and reported raw permutation-p / Wilson-LB as if k=1. Bailey & Lopez de Prado: the
expected max Sharpe of N zero-edge trials is ~sqrt(2 ln N) sigma, so a "p=0.002 mined from a
sweep" IS that order statistic. This module supplies the missing machinery:

  - psr(...)              Probabilistic Sharpe Ratio (penalizes the negative skew of -100%-on-miss bets)
  - expected_max_sharpe  E[max] of N null trials (the deflation benchmark)
  - deflated_sharpe(...)  DSR = PSR evaluated at E[max null]; <0.95 => indistinguishable from best-of-N noise
  - min_track_record_len  how many bets you'd need for significance
  - cluster_bootstrap_ci  resample WHOLE windows (our rows are cross-coin-correlated within a window)
  - purged_kfold          purged + embargoed CV that holds out whole windows (no leakage)
  - placebo_p / permutation_p   null comparisons that DON'T self-disable at small n
  - binary_bet_returns    (ask, won) -> net return per $1 (taker entry, hold-to-0/1) = our "return" stream
  - assess(...)           one call: Sharpe, PSR, DSR, skew/kurt, cluster-CI, verdict
  - TrialsLedger          record every (experiment, config) so DSR uses the HONEST N

Binary-market note: a "return" here is the per-$1 net P&L of one held-to-resolution bet, NOT an
annualized strategy return. Sharpe is per-bet (mean/std over the bet stream); n = number of bets.
The -100% tail makes the stream severely negatively skewed -> PSR is the right tool (mean EV lies).

Refs: Bailey & Lopez de Prado, "The Deflated Sharpe Ratio" (2014); AFML ch.7,12,14; skill ref 08/04.
"""
from __future__ import annotations
import json
import math
import os
import numpy as np
from scipy import stats as _ss

from net_ev import net_ev_per_dollar, breakeven_winrate, taker_fee_per_stake  # the cost authority

_EM = 0.5772156649015329          # Euler-Mascheroni
_PHI = _ss.norm.cdf
_PHIINV = _ss.norm.ppf


# ----------------------------------------------------------------- core Sharpe / PSR / DSR
def sharpe(returns) -> float:
    """Per-observation Sharpe of a return stream (NOT annualized). mean/std, ddof=1."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1))


def psr(returns, sr_star: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true Sharpe > sr_star) given the observed stream,
    correcting for sample length, skew and kurtosis (Bailey & LdP). For our bets the heavy
    NEGATIVE skew pushes PSR well below what the raw mean/Sharpe implies."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return float("nan")
    sr = sharpe(r)
    g3 = float(_ss.skew(r, bias=False))
    g4 = float(_ss.kurtosis(r, fisher=False, bias=False))      # non-excess (normal=3)
    radic = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr        # B5: don't clamp a domain violation
    if radic <= 0:
        return float("nan")                                    # Edgeworth expansion invalid here
    return float(_PHI((sr - sr_star) * math.sqrt(n - 1) / math.sqrt(radic)))


def expected_max_sharpe(n_trials: int, var_trial_sharpe: float) -> float:
    """E[max of N i.i.d. null Sharpes] (Bailey-LdP false-strategy theorem). var_trial_sharpe =
    cross-trial variance of the Sharpes you tried (or its null fallback ~ 1/(n_obs-1))."""
    if n_trials < 2 or var_trial_sharpe <= 0:
        return 0.0
    s = math.sqrt(var_trial_sharpe)
    return float(s * ((1 - _EM) * _PHIINV(1 - 1.0 / n_trials)
                      + _EM * _PHIINV(1 - 1.0 / (n_trials * math.e))))


def deflated_sharpe(returns, n_trials: int, var_trial_sharpe: float | None = None) -> dict:
    """DSR: PSR evaluated at the deflation benchmark E[max of N null Sharpes]. DSR<0.95 =>
    the result is statistically indistinguishable from the best of N noise draws -> do NOT believe it.
    var_trial_sharpe fallback = null variance of the Sharpe estimator ~ 1/(n_obs-1)."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return dict(dsr=float("nan"), sr0=float("nan"), sr=float("nan"), n=n, n_trials=n_trials, fallback=True)
    fallback = var_trial_sharpe is None
    if fallback:
        # B2: the 1/(n-1) sampling-var of ONE Sharpe UNDER-deflates 4-9x vs the cross-trial variance
        # Bailey-LdP's E[max] needs. Floor it and FLAG it; supply the real value via TrialsLedger.
        var_trial_sharpe = max(1.0 / (n - 1), 0.05)
    sr0 = expected_max_sharpe(n_trials, var_trial_sharpe)
    return dict(dsr=psr(r, sr0), sr0=sr0, sr=sharpe(r), n=n, n_trials=n_trials,
                skew=float(_ss.skew(r, bias=False)), fallback=fallback)


def min_track_record_len(returns, sr_star: float = 0.0, prob: float = 0.95) -> float:
    """Minimum #bets so PSR(sr_star) >= prob, at the observed Sharpe/skew/kurt."""
    r = np.asarray(returns, float); r = r[np.isfinite(r)]
    sr = sharpe(r)
    if not np.isfinite(sr) or sr <= sr_star:
        return float("inf")
    g3 = float(_ss.skew(r, bias=False)); g4 = float(_ss.kurtosis(r, fisher=False, bias=False))
    return float(1 + (1 - g3 * sr + ((g4 - 1) / 4) * sr * sr) * (_PHIINV(prob) / (sr - sr_star)) ** 2)


# ----------------------------------------------------------------- cluster-aware resampling
def cluster_bootstrap_ci(values, clusters, stat=np.mean, B: int = 5000, alpha: float = 0.05, seed: int = 1):
    """Bootstrap a statistic by resampling WHOLE clusters (e.g. window_start) with replacement —
    the honest CI when rows inside a cluster are correlated (cross-coin within a 5-min window)."""
    values = np.asarray(values, float); clusters = np.asarray(clusters)
    uniq = np.unique(clusters)
    idx_by = {c: np.where(clusters == c)[0] for c in uniq}
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    for b in range(B):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        rows = np.concatenate([idx_by[c] for c in pick])
        out[b] = stat(values[rows])
    return float(stat(values)), float(np.percentile(out, 100 * alpha / 2)), float(np.percentile(out, 100 * (1 - alpha / 2)))


def purged_kfold(window_ids, k: int = 5, embargo: int = 0):
    """Purged + embargoed K-fold over ORDERED unique windows. Holds out whole contiguous window
    blocks as test; purges train windows within `embargo` of the test block. Yields (train_idx,
    test_idx) into the row array. Our windows are serially ~independent (AC~0) so embargo can be 0,
    but blocking by window prevents same-window cross-coin leakage."""
    window_ids = np.asarray(window_ids)
    uniq = np.unique(window_ids)                      # sorted
    if len(uniq) < 2:                                 # B3: don't crash on thin subsets
        return
    k = max(1, min(k, len(uniq)))
    folds = [f for f in np.array_split(uniq, k) if f.size > 0]
    for f in folds:
        test_w = set(f.tolist())
        lo, hi = f.min(), f.max()
        embargoed = set(uniq[(uniq >= lo - embargo) & (uniq <= hi + embargo)].tolist())
        test_idx = np.where(np.isin(window_ids, list(test_w)))[0]
        train_idx = np.where(~np.isin(window_ids, list(embargoed)))[0]
        yield train_idx, test_idx


# ----------------------------------------------------------------- null-hypothesis tests
def placebo_p(observed: float, universe_values, k: int, B: int = 5000, side: str = "greater", seed: int = 7):
    """p = fraction of random size-k draws from `universe_values` whose mean beats `observed`.
    Unlike the old experiments this does NOT self-disable at small k (it just gets wide)."""
    u = np.asarray(universe_values, float); u = u[np.isfinite(u)]
    if len(u) <= k or k < 1:
        return float("nan")
    rng = np.random.default_rng(seed)
    draws = np.array([u[rng.choice(len(u), k, replace=False)].mean() for _ in range(B)])
    return float(np.mean(draws >= observed) if side == "greater" else np.mean(draws <= observed))


def permutation_p(stat_obs: float, x, y, stat_fn, B: int = 10000, seed: int = 0, side: str = "greater"):
    """Permutation p: shuffle y vs x, recompute stat_fn(x, y_perm)."""
    x = np.asarray(x); y = np.asarray(y); rng = np.random.default_rng(seed)
    null = np.array([stat_fn(x, rng.permutation(y)) for _ in range(B)])
    return float(np.mean(null >= stat_obs) if side == "greater" else np.mean(null <= stat_obs))


def pearson(x, y) -> float:
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3 or x[m].std() == 0 or y[m].std() == 0:
        return float("nan")
    return float(np.corrcoef(x[m], y[m])[0, 1])


# ----------------------------------------------------------------- binary-bet helpers
def binary_bet_returns(asks, wons, entry="taker", exit="hold"):
    """Per-$1 net return of each held-to-resolution bet (the 'return' stream for Sharpe/PSR/DSR)."""
    return np.array([net_ev_per_dollar(float(a), int(w), entry, exit) for a, w in zip(asks, wons)], float)


def wilson_lb(k: int, n: int, z: float = 1.96) -> float:
    """One-sided Wilson lower bound of a win-rate (re-export-compatible with net_ev's)."""
    if n == 0:
        return 0.0
    p = k / n
    return float((p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n))


# ----------------------------------------------------------------- THE PRIMARY (right) object
MIN_LOSS = 30          # below this, loss-light -> CI/Sharpe degenerate -> verdict = INSUFFICIENT
N_PROGRAM = 200        # committed program-level effective trial count (16 experiments x ideas A-H x
                       # 6 coins x sweep points ~ several hundred); override per call with the honest count


def neff(rho: float, m: int) -> float:
    """Effective independent count among m series with avg pairwise correlation rho (Neff=m/(1+(m-1)rho))."""
    if m <= 1:
        return float(m)
    return m / (1.0 + (m - 1) * rho)


def deflated_resid_p(values, clusters, n_trials: int = N_PROGRAM, B: int = 10000, seed: int = 11):
    """PRIMARY test (the economically correct object, per the rigor critique): one-sided
    cluster-bootstrap p that mean(values) > 0, then DEFLATED for n_trials via Sidak: p_def=1-(1-p)^N.
    `values` = per-position net EV (fee-aware) or residual (won-price). Cluster-resampling makes it
    Neff-aware for cross-coin within-window correlation, so we do NOT also pretend each row is i.i.d.
    Returns (mean, lo, hi, p_single, p_deflated)."""
    values = np.asarray(values, float); clusters = np.asarray(clusters)
    good = np.isfinite(values)
    values, clusters = values[good], clusters[good]
    uniq = np.unique(clusters)
    if len(uniq) < 5:
        m = float(values.mean()) if len(values) else float("nan")
        return m, float("nan"), float("nan"), float("nan"), float("nan")
    idx_by = {c: np.where(clusters == c)[0] for c in uniq}
    rng = np.random.default_rng(seed)
    boot = np.empty(B)
    for b in range(B):
        pick = rng.choice(uniq, len(uniq), replace=True)
        boot[b] = values[np.concatenate([idx_by[c] for c in pick])].mean()
    p_single = float(np.mean(boot <= 0.0))                       # one-sided P(mean <= 0)
    p_def = 1.0 - (1.0 - p_single) ** max(1, int(n_trials))      # Sidak deflation for best-of-N
    return float(values.mean()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)), p_single, float(p_def)


def assess(asks, wons, clusters, n_trials: int = N_PROGRAM, label: str = "", side_price=None) -> dict:
    """Honest verdict on a set of binary bets. PRIMARY gate = the deflated cluster-bootstrap p on the
    fee-aware net-EV stream (the right object) AND the cluster-CI excludes 0 AND n_loss>=MIN_LOSS.
    Sharpe / PSR / DSR are PRESENTATION only (per-bet Sharpe is a monotone function of win-rate, so it
    is the SAME test as Wilson-LB and must not be double-counted in the gate). n_trials = HONEST count."""
    asks = np.asarray(asks, float); wons = np.asarray(wons, float); clusters = np.asarray(clusters)
    r = binary_bet_returns(asks, wons)
    n = len(r); k = int(wons.sum()); n_loss = n - k
    mean_ev, lo, hi, p1, pdef = deflated_resid_p(r, clusters, n_trials)
    price = np.asarray(side_price, float) if side_price is not None else asks
    resid = float(wons.mean() - price.mean())
    ds = deflated_sharpe(r, n_trials)                            # presentation only
    wlb = wilson_lb(k, n); be = breakeven_winrate(float(asks.mean()))
    if n_loss < MIN_LOSS:                                        # B4: loss-light -> CI/PSR undefined
        verdict, survives = f"INSUFFICIENT (n_loss={n_loss}<{MIN_LOSS})", False
    else:
        survives = bool(np.isfinite(pdef) and pdef < 0.05 and lo > 0)
        verdict = "SURVIVES" if survives else "FAILS"
    return dict(label=label, n=n, n_loss=n_loss, win=k / n if n else float("nan"),
                mean_ev=mean_ev, ci=(lo, hi), resid=resid, p_single=p1, p_deflated=pdef,
                sharpe=ds["sr"], psr0=psr(r, 0.0), dsr=ds["dsr"], dsr_fallback=ds.get("fallback"),
                skew=ds.get("skew"), wlb=wlb, be=be, n_trials=n_trials, verdict=verdict, SURVIVES=survives)


def print_assess(a: dict):
    print(f"  [{a['label']}] n={a['n']} (loss {a['n_loss']})  win {100*a['win']:.1f}%  "
          f"mean net-EV {a['mean_ev']:+.4f}  cluster-CI[{a['ci'][0]:+.4f},{a['ci'][1]:+.4f}]  resid {a['resid']:+.3f}")
    fb = "  [DSR under-deflated: sampling-var fallback]" if a.get("dsr_fallback") else ""
    print(f"      PRIMARY: deflated cluster-bootstrap p (vs N={a['n_trials']}) = {a['p_deflated']:.3f}  "
          f"(raw one-sided p={a['p_single']:.3f})")
    print(f"      [presentation] Sharpe {a['sharpe']:+.3f} skew {a['skew']:+.2f}  PSR(>0) {a['psr0']:.3f}  "
          f"DSR {a['dsr']:.3f}{fb}  Wilson-LB(win) {a['wlb']:.3f} vs breakeven {a['be']:.3f}")
    print(f"      => {a['verdict']}   (gate: deflated p<0.05 AND cluster-CI>0 AND n_loss>={MIN_LOSS})")


# ----------------------------------------------------------------- trials ledger
class TrialsLedger:
    """Append-only record of every (experiment, config) tried, so DSR uses the HONEST N instead of
    pretending k=1. Persists to a JSONL so the count survives across sessions."""
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def record(self, experiment: str, config: dict, sharpe_val: float | None = None):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(experiment=experiment, config=config, sharpe=sharpe_val)) + "\n")

    def count(self, experiment: str | None = None) -> int:
        if not os.path.exists(self.path):
            return 0
        n = 0
        for line in open(self.path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if experiment is None or rec.get("experiment") == experiment:
                n += 1
        return n

    def trial_sharpe_var(self, experiment: str | None = None) -> float | None:
        vals = []
        if os.path.exists(self.path):
            for line in open(self.path, encoding="utf-8"):
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if (experiment is None or rec.get("experiment") == experiment) and rec.get("sharpe") is not None:
                    vals.append(rec["sharpe"])
        return float(np.var(vals, ddof=1)) if len(vals) >= 2 else None

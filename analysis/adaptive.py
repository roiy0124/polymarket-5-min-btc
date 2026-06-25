"""Adaptivity primitives — make a gate track the market WITHOUT adding a fitted parameter.

The project's hard rule (memory edge-is-regime-dependent / combination-gating-principle): RE-FITTING a
free threshold to recent data is the overfit trap that killed experiment_favtail_adaptive + config_tod
OOS. The SAFE form of adaptivity is SELF-NORMALIZING: express the gate as a position RELATIVE to the
signal's own recent distribution (a rolling percentile), so an absolute constant like `over_round<=0.012`
becomes `over_round below its trailing median`. That tracks regime drift (wider baseline spreads, vol
regimes) with ZERO new degrees of freedom — the percentile is fixed at the same fraction the constant
implied, only the reference level floats. The one knob is the lookback, and we DEFAULT it and test
sensitivity rather than optimize it.

  - rolling_pct_rank(vals, order, lookback)  causal percentile rank of each item among its trailing peers
  - rolling_ref(vals, order, q, lookback)     causal trailing q-quantile reference level
  - stability_by_bin(...)                      edge per time-third -> is the signal stationary or decaying?
"""
from __future__ import annotations
import numpy as np


def _rank_one(vals, order, lookback, min_obs):
    vals = np.asarray(vals, float); order = np.asarray(order)
    o = np.argsort(order, kind="stable")
    inv = np.empty_like(o); inv[o] = np.arange(len(o))
    sv = vals[o]
    out = np.full(len(sv), np.nan)
    for j in range(len(sv)):
        hist = sv[max(0, j - lookback):j]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= min_obs:
            out[j] = np.mean(hist < sv[j]) + 0.5 * np.mean(hist == sv[j])
    return out[inv]


def rolling_pct_rank(vals, order, lookback=200, min_obs=30, groups=None):
    """For each item i, the percentile rank in [0,1] of vals[i] among the PRIOR `lookback` items
    (strictly causal — excludes i and the future). NaN until min_obs history. A gate `rank <= 0.5` =
    'in the tight half of the RECENT regime' (self-normalizing).

    groups: PER-GROUP normalization (CRITICAL when a quantity's scale differs across groups, e.g.
    over_round is ~5x larger on BNB than BTC). Ranking each coin against its OWN trailing history makes
    the gate 'tight FOR ITS OWN COIN', not 'whichever coin has structurally tighter spreads'. Always pass
    groups=coin for cross-coin quantities — pooling silently gates on the group, not the regime."""
    vals = np.asarray(vals, float); order = np.asarray(order)
    if groups is None:
        return _rank_one(vals, order, lookback, min_obs)
    groups = np.asarray(groups); out = np.full(len(vals), np.nan)
    for g in np.unique(groups):
        m = groups == g
        out[m] = _rank_one(vals[m], order[m], lookback, min_obs)
    return out


def rolling_ref(vals, order, q=0.5, lookback=200, min_obs=30, groups=None):
    """Causal trailing q-quantile of `vals` (the self-normalizing reference LEVEL). NaN until min_obs.
    Pass groups for per-group normalization (see rolling_pct_rank)."""
    def _one(v, o):
        v = np.asarray(v, float); o = np.asarray(o)
        oi = np.argsort(o, kind="stable"); inv = np.empty_like(oi); inv[oi] = np.arange(len(oi))
        sv = v[oi]; out = np.full(len(sv), np.nan)
        for j in range(len(sv)):
            hist = sv[max(0, j - lookback):j]; hist = hist[np.isfinite(hist)]
            if len(hist) >= min_obs:
                out[j] = np.quantile(hist, q)
        return out[inv]
    vals = np.asarray(vals, float); order = np.asarray(order)
    if groups is None:
        return _one(vals, order)
    groups = np.asarray(groups); out = np.full(len(vals), np.nan)
    for g in np.unique(groups):
        m = groups == g
        out[m] = _one(vals[m], order[m])
    return out


def rolling_wilson_monitor(order, won, asks, gate_mask, window=150, z=1.96):
    """Drift monitor that is actually powered (the by-thirds split is a catastrophe-only smoke alarm).
    Slides a window of `window` gated bets; at each step reports Wilson-LB(win) minus the ask-implied
    breakeven. A sustained crossing below 0 = the edge has decayed below the fee wall — alert. Returns
    (latest_lb_minus_be, fraction_of_steps_below_0, n_steps)."""
    import math
    from net_ev import breakeven_winrate, wilson_lb
    order = np.asarray(order); won = np.asarray(won, float); asks = np.asarray(asks, float)
    idx = np.where(np.asarray(gate_mask, bool))[0]
    idx = idx[np.argsort(order[idx], kind="stable")]
    if len(idx) < window + 5:
        return None
    diffs = []
    for s in range(0, len(idx) - window + 1):
        sl = idx[s:s + window]; w = won[sl]
        lb = wilson_lb(int(w.sum()), len(w), z); be = breakeven_winrate(float(asks[sl].mean()))
        diffs.append(lb - be)
    diffs = np.array(diffs)
    return float(diffs[-1]), float(np.mean(diffs < 0)), len(diffs)


def stability_by_bin(order, won, gate_mask, bins=3):
    """Split the gated positions into `bins` contiguous time slices (by `order`) and report win-rate +
    loser count per slice. A stationary signal holds its win-rate across slices; a decaying one fades in
    the latest slice — the early warning that a fixed param is falling behind."""
    order = np.asarray(order); won = np.asarray(won, float); gate_mask = np.asarray(gate_mask, bool)
    idx = np.where(gate_mask)[0]
    if len(idx) < bins * 5:
        return []
    idx = idx[np.argsort(order[idx], kind="stable")]
    out = []
    for sl in np.array_split(idx, bins):
        w = won[sl]
        out.append(dict(n=len(sl), loss=int((w == 0).sum()), win=float(w.mean())))
    return out

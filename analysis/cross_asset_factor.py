"""Cross-asset factor model — the "proportionality formula" for the 6 coins.

Answers: how much does each coin move with the dominant coins (BTC/ETH), how much of
each coin is explained by them (vs idiosyncratic), WHO is dominant and whether that
shifts over time, and a standardized detector for UN-proportionate moves (the input the
fear/divergence idea needs). Built on the deep free spot store (analysis/spot_data.py,
all 6 coins back to 2021-01), so the structure is estimated over every regime.

Model (per coin i, on returns at INTERVAL seconds):
    r_i = alpha_i + beta_i,BTC * r_BTC + beta_i,ETH * r_ETH + eps_i
  -> beta      = proportionality coefficients (how much i moves per 1% major move)
  -> R^2       = fraction of i explained by the majors ("how proportion related")
  -> sigma(eps)= idiosyncratic vol (i's own move size)
  -> z_i = (r_i - r_hat_i) / sigma(eps_i)  = standardized UN-proportionate move (detector)
Dominance: PCA on the standardized return matrix -> PC1 = the market mode; its loadings
say who drives the system; |corr(coin, PC1)| ranks dominance; recomputed per year to
catch "a different dominant coin tomorrow".

Usage:  python -m analysis.cross_asset_factor [--interval 60] [--start 2021-01]
"""
from __future__ import annotations
import argparse, os, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from analysis import spot_data
from analysis.spot_data import SYMBOL, COINS

OUT = os.path.join(spot_data.REPO, "spot_leadlag")   # reuse the gitignored output dir
os.makedirs(OUT, exist_ok=True)
FACTORS = ["btc", "eth"]


def load_minute_returns(start: str, interval: int):
    """Memory-safe: load each coin's 1s closes, downsample to the bar `interval`, free,
    then align on common bars and return a (T x N) returns DataFrame."""
    series = {}
    for c in COINS:
        d = spot_data.load_range(SYMBOL[c], start)          # ~2.8GB peak for btc, then freed
        bar = d["sec"] // interval
        s = pd.Series(d["close"], index=bar)
        s = s[~s.index.duplicated(keep="last")]             # last close in each bar
        series[c] = s
        del d
        print(f"  loaded {c} ({len(s):,} bars)", file=sys.stderr)
    px = pd.DataFrame(series).dropna()                       # aligned on common bars
    ret = px.pct_change().dropna()
    yrs = pd.to_datetime(ret.index.values * interval, unit="s", utc=True).year
    return ret, np.asarray(yrs)


def factor_fit(ret: pd.DataFrame, alt: str):
    """OLS r_alt ~ r_btc + r_eth (+const). Returns betas, two-factor R^2, BTC-only R^2,
    idiosyncratic vol, and the residual series (for the z detector)."""
    y = ret[alt].values
    X = np.column_stack([ret[f].values for f in FACTORS] + [np.ones(len(y))])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / ss_tot
    r2_btc = np.corrcoef(y, ret["btc"].values)[0, 1] ** 2
    return dict(b_btc=coef[0], b_eth=coef[1], r2=r2, r2_btc=r2_btc,
                idio=resid.std(), resid=resid)


def pca_dominance(ret: pd.DataFrame):
    """PC1 variance share + loadings (standardized). Dominant coin = highest |loading|."""
    Z = (ret - ret.mean()) / ret.std()
    C = np.corrcoef(Z.values, rowvar=False)
    w, V = np.linalg.eigh(C)
    order = np.argsort(w)[::-1]
    w, V = w[order], V[:, order]
    pc1 = V[:, 0]
    if pc1[list(ret.columns).index("btc")] < 0:              # sign so majors load +
        pc1 = -pc1
    share = w[0] / w.sum()
    loadings = dict(zip(ret.columns, pc1))
    dom = max(loadings, key=lambda k: abs(loadings[k]))
    return share, loadings, dom


def report(ret: pd.DataFrame, yrs: np.ndarray, interval: int):
    alts = [c for c in COINS if c not in FACTORS]
    print("\n" + "=" * 84)
    print(f"CROSS-ASSET FACTOR MODEL   interval={interval}s   bars={len(ret):,}   "
          f"{ret.index.min()*interval and datetime.fromtimestamp(ret.index.min()*interval, timezone.utc).date()}"
          f" -> {datetime.fromtimestamp(ret.index.max()*interval, timezone.utc).date()}")
    print("model: r_i = a + b_BTC*r_BTC + b_ETH*r_ETH + eps_i   (returns at the bar above)")
    print("=" * 84)

    print("\n[FULL-SAMPLE proportionality]  (R2 = fraction of the coin explained by BTC+ETH)")
    print(f"{'coin':5} {'b_BTC':>7} {'b_ETH':>7} {'R2(2f)':>7} {'R2(BTC)':>8} {'idio/bar':>9}")
    fits = {}
    for a in alts:
        f = factor_fit(ret, a); fits[a] = f
        print(f"{a.upper():5} {f['b_btc']:>7.2f} {f['b_eth']:>7.2f} {f['r2']:>7.2f} "
              f"{f['r2_btc']:>8.2f} {f['idio']*100:>8.3f}%")

    print("\n[PER-YEAR: two-factor R2 (proportion explained) -- does the structure hold?]")
    years = sorted(set(yrs.tolist()))
    hdr = "coin " + "".join(f"{y:>7}" for y in years)
    print(hdr)
    for a in alts:
        row = f"{a.upper():5}"
        for y in years:
            m = yrs == y
            if m.sum() > 100:
                row += f"{factor_fit(ret[m], a)['r2']:>7.2f}"
            else:
                row += f"{'-':>7}"
        print(row)

    print("\n[PER-YEAR: beta to BTC -- proportionality coefficient drift]")
    print(hdr)
    for a in alts:
        row = f"{a.upper():5}"
        for y in years:
            m = yrs == y
            row += (f"{factor_fit(ret[m], a)['b_btc']:>7.2f}" if m.sum() > 100 else f"{'-':>7}")
        print(row)

    print("\n[DOMINANCE via PCA -- PC1 = the 'market mode'; loadings = who drives it]")
    share, load, dom = pca_dominance(ret)
    print(f"  FULL: PC1 explains {share:.0%} of total variance; dominant = {dom.upper()}")
    print("  loadings: " + "  ".join(f"{k.upper()}={v:+.2f}" for k, v in load.items()))
    print(f"  {'year':>6} {'PC1share':>9} {'dominant':>9}   loadings")
    for y in years:
        m = yrs == y
        if m.sum() < 100:
            continue
        sh, ld, dm = pca_dominance(ret[m])
        ls = " ".join(f"{k.upper()[:3]}{v:+.2f}" for k, v in ld.items())
        print(f"  {y:>6} {sh:>8.0%} {dm.upper():>9}   {ls}")

    print("\n[THE DETECTOR]  un-proportionate move of coin i at bar t:")
    print("    z_i = ( r_i - b_BTC*r_BTC - b_ETH*r_ETH - a ) / sigma(eps_i)")
    print("  |z|>2 = move the majors don't explain; large NEGATIVE z with BTC/ETH flat/up")
    print("  = the 'unjustified / fear' candidate. Per-coin idio/bar (sigma) above sets the scale.")
    print("=" * 84)
    return fits, years


def plot_rolling(ret: pd.DataFrame, interval: int, out=OUT):
    """Rolling (monthly) R2 to the majors and beta_BTC per alt — visual stability/drift."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    alts = [c for c in COINS if c not in FACTORS]
    month = pd.to_datetime(ret.index.values * interval, unit="s", utc=True).to_period("M")
    rows = {}
    for mp in pd.unique(month):
        m = month == mp
        if m.sum() < 200:
            continue
        sub = ret[m]
        rows[mp.to_timestamp()] = {a: factor_fit(sub, a) for a in alts}
    xs = sorted(rows)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), dpi=130, sharex=True)
    for a in alts:
        ax1.plot(xs, [rows[x][a]["r2"] for x in xs], "-o", ms=2, label=a.upper())
        ax2.plot(xs, [rows[x][a]["b_btc"] for x in xs], "-o", ms=2, label=a.upper())
    ax1.set_ylabel("R² explained by BTC+ETH"); ax1.set_title(
        f"Cross-asset proportionality over time (monthly, {interval}s returns)")
    ax1.grid(alpha=0.25); ax1.legend(fontsize=8, ncol=5); ax1.set_ylim(0, 1)
    ax2.set_ylabel("beta to BTC"); ax2.grid(alpha=0.25); ax2.axhline(0, color="k", lw=0.6)
    path = os.path.join(out, f"cross_asset_factor_{interval}s.png")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    print(f"plot -> {path}")


# =================================================================================
# ADAPTIVE (time-varying) betas — the SHARED TOOL. Fixed betas above are a snapshot of
# a moving target (per-year R2 ~doubles); these recalibrate every bar and never freeze.
# Mechanism = EWMA / forgetting-factor covariance (the same kappa device the TVP-VAR /
# Diebold-Yilmaz connectedness literature uses; RiskMetrics-style, ONE knob = half-life,
# so it is adaptive without the refit-the-best-combo overfit trap). Strictly causal:
# the z-score at bar t uses betas estimated only through t-1 (no look-ahead), so it is
# real-time implementable. Import these from any experiment; do NOT bake into a strategy.
# =================================================================================

def _ewm_cov(x, y, hl):
    """EWMA covariance of two aligned return series (forgetting factor via half-life).
    adjust=False = the recursive form, so the batch path matches the live streaming class."""
    mx = x.ewm(halflife=hl, adjust=False).mean(); my = y.ewm(halflife=hl, adjust=False).mean()
    return (x * y).ewm(halflife=hl, adjust=False).mean() - mx * my


def adaptive_betas(ret: pd.DataFrame, alt: str, hl: float, factors=FACTORS):
    """Time-varying betas of `alt` on the factors via EWMA covariances, the CAUSAL
    residual (predict r_alt(t) with betas known at t-1), and the adaptive detector
    z_t = resid_t / EWMA-sigma_{t-1}. Returns a DataFrame [b_<f1>, b_<f2>, resid, z].
    |z|>2 with the factors flat = a move the majors don't explain (un-proportionate)."""
    f1, f2 = factors
    S11 = _ewm_cov(ret[f1], ret[f1], hl); S22 = _ewm_cov(ret[f2], ret[f2], hl)
    S12 = _ewm_cov(ret[f1], ret[f2], hl)
    S1i = _ewm_cov(ret[f1], ret[alt], hl); S2i = _ewm_cov(ret[f2], ret[alt], hl)
    det = (S11 * S22 - S12 ** 2).replace(0.0, np.nan)
    b1 = (S22 * S1i - S12 * S2i) / det
    b2 = (S11 * S2i - S12 * S1i) / det
    pred = b1.shift(1) * ret[f1] + b2.shift(1) * ret[f2]    # causal: betas from t-1
    resid = ret[alt] - pred
    sig = np.sqrt((resid ** 2).ewm(halflife=hl, adjust=False).mean()).shift(1)
    z = resid / sig.replace(0.0, np.nan)
    out = pd.DataFrame({f"b_{f1}": b1, f"b_{f2}": b2, "resid": resid, "z": z})
    out.iloc[:int(2 * hl)] = np.nan          # mask EWMA warmup (variance not yet stable)
    return out


def adaptive_z_all(ret: pd.DataFrame, hl: float, factors=FACTORS):
    """Convenience: adaptive z-score series for every non-factor coin (the detector)."""
    alts = [c for c in ret.columns if c not in factors]
    return pd.DataFrame({a: adaptive_betas(ret, a, hl, factors)["z"] for a in alts})


class AdaptiveFactorModel:
    """LIVE incremental version of the above — feed one bar of returns, get each coin's
    time-varying betas + adaptive z (un-proportionate-move score). Correct real-time
    flow: z is scored from the PRE-update betas (causal), then state is updated. Shared
    tool for signal measurement / gating in any strategy; knows nothing about strategies."""
    def __init__(self, alts, hl=1440.0, factors=FACTORS):
        self.alts = list(alts); self.f1, self.f2 = factors
        self.alpha = 1.0 - 0.5 ** (1.0 / hl)
        self.warmup = int(2 * hl); self.t = 0
        self.m = {}            # EWMA means of vars + needed products
        self.b = {a: (0.0, 0.0) for a in self.alts}   # last betas (b_f1, b_f2)
        self.rv = {a: 0.0 for a in self.alts}          # EWMA residual variance
        self.ready = False

    def _keys(self):
        f1, f2, A = self.f1, self.f2, self.alts
        sing = [f1, f2] + A
        prod = [(f1, f1), (f2, f2), (f1, f2)] + [(f1, i) for i in A] + [(f2, i) for i in A]
        return sing, prod

    def update(self, r: dict):
        """r: {coin: return} for this bar. Returns {coin: z} scored causally, then learns."""
        f1, f2, a = self.f1, self.f2, self.alpha
        sing, prod = self._keys()
        self.t += 1
        if not self.ready:
            for k in sing: self.m[k] = r[k]
            for p in prod: self.m[p] = r[p[0]] * r[p[1]]
            self.ready = True
            return {i: 0.0 for i in self.alts}
        out = {}
        warm = self.t <= self.warmup                     # variance not yet stable
        for i in self.alts:                              # score with PRE-update betas
            b1, b2 = self.b[i]
            resid = r[i] - b1 * r[f1] - b2 * r[f2]
            out[i] = (resid / (self.rv[i] ** 0.5)) if (self.rv[i] > 0 and not warm) else 0.0
            self.rv[i] += a * (resid * resid - self.rv[i])
        for k in sing: self.m[k] += a * (r[k] - self.m[k])   # then learn
        for p in prod: self.m[p] += a * (r[p[0]] * r[p[1]] - self.m[p])
        S11 = self.m[(f1, f1)] - self.m[f1] ** 2
        S22 = self.m[(f2, f2)] - self.m[f2] ** 2
        S12 = self.m[(f1, f2)] - self.m[f1] * self.m[f2]
        det = S11 * S22 - S12 * S12
        if abs(det) > 1e-18:
            for i in self.alts:
                S1i = self.m[(f1, i)] - self.m[f1] * self.m[i]
                S2i = self.m[(f2, i)] - self.m[f2] * self.m[i]
                self.b[i] = ((S22 * S1i - S12 * S2i) / det, (S11 * S2i - S12 * S1i) / det)
        return out


def report_adaptive(ret: pd.DataFrame, hl: float, interval: int):
    alts = [c for c in COINS if c not in FACTORS]
    print("\n" + "=" * 84)
    print(f"ADAPTIVE (time-varying) FACTOR MODEL   halflife={hl:.0f} bars (~{hl*interval/3600:.1f}h)"
          f"   interval={interval}s   bars={len(ret):,}")
    print("model: r_i(t) = b_BTC(t)*r_BTC + b_ETH(t)*r_ETH + eps   (EWMA betas, causal z)")
    print("=" * 84)
    print(f"{'coin':5} {'b_BTC now':>10} {'b_BTC rng':>14} {'fixedR2':>8} {'adaptR2':>8} "
          f"{'residShrink':>12} {'|z|>2':>7} {'|z|>3':>7}")
    for a in alts:
        ab = adaptive_betas(ret, a, hl)
        fixed = factor_fit(ret, a)
        ar = ab.dropna()
        adapt_resid_var = ar["resid"].var()
        fixed_resid_var = fixed["idio"] ** 2
        shrink = 1.0 - adapt_resid_var / fixed_resid_var
        adapt_r2 = 1.0 - adapt_resid_var / ret[a].var()
        bb = ar[f"b_btc"]
        zt = ar["z"].abs()
        print(f"{a.upper():5} {bb.iloc[-1]:>10.2f} {f'[{bb.quantile(.05):.2f},{bb.quantile(.95):.2f}]':>14} "
              f"{fixed['r2']:>8.2f} {adapt_r2:>8.2f} {shrink*100:>11.1f}% "
              f"{(zt>2).mean()*100:>6.2f}% {(zt>3).mean()*100:>6.2f}%")
    print("\n  b_BTC rng = 5-95% range of the time-varying beta (proof it MOVES, vs the fixed snapshot).")
    print("  residShrink = how much the adaptive model shrinks residual variance vs fixed betas (>0 = adaptive wins).")
    print("  |z|>2/3 = tail frequency of the detector (Normal ref: 4.6% / 0.3%); excess = fat-tailed un-proportionate moves.")
    print("  DETECTOR (import): adaptive_z_all(ret, hl) or live AdaptiveFactorModel(alts, hl).update(r) -> {coin: z}")
    print("=" * 84)


def plot_adaptive(ret: pd.DataFrame, hl: float, interval: int, out=OUT):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    alts = [c for c in COINS if c not in FACTORS]
    idx = pd.to_datetime(ret.index.values * interval, unit="s", utc=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), dpi=130, sharex=True)
    for a in alts:
        b = adaptive_betas(ret, a, hl)[f"b_btc"]
        ax1.plot(idx, b.values, lw=0.8, label=a.upper())
    ax1.set_title(f"ADAPTIVE beta to BTC over time (EWMA, halflife {hl:.0f} bars) — betas MOVE, never frozen")
    ax1.set_ylabel("time-varying beta_BTC"); ax1.grid(alpha=0.25); ax1.legend(fontsize=8, ncol=5)
    ax1.axhline(0, color="k", lw=0.5); ax1.set_ylim(-0.5, 2.5)
    zexample = adaptive_betas(ret, alts[0], hl)["z"]
    ax2.plot(idx, zexample.values, lw=0.5, color="#d62728")
    ax2.axhline(2, color="k", lw=0.5, ls="--"); ax2.axhline(-2, color="k", lw=0.5, ls="--")
    ax2.set_ylabel(f"adaptive z  ({alts[0].upper()})"); ax2.grid(alpha=0.25); ax2.set_ylim(-10, 10)
    ax2.set_title("adaptive z-score detector (|z|>2 dashed = un-proportionate move)")
    path = os.path.join(out, f"adaptive_factor_{interval}s_hl{int(hl)}.png")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    print(f"plot -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60, help="return bar in seconds")
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--adaptive", action="store_true", help="time-varying (EWMA) betas + adaptive z detector")
    ap.add_argument("--halflife", type=float, default=1440.0, help="EWMA half-life in bars (default 1440 = 1 day @60s)")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args()
    print(f"loading 6 coins @ {a.interval}s bars from {a.start} ...", file=sys.stderr)
    ret, yrs = load_minute_returns(a.start, a.interval)
    if a.adaptive:
        report_adaptive(ret, a.halflife, a.interval)
        if not a.no_plot:
            plot_adaptive(ret, a.halflife, a.interval)
    else:
        report(ret, yrs, a.interval)
        if not a.no_plot:
            plot_rolling(ret, a.interval)


if __name__ == "__main__":
    main()

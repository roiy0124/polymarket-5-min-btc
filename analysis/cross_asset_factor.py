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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60, help="return bar in seconds")
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args()
    print(f"loading 6 coins @ {a.interval}s bars from {a.start} ...", file=sys.stderr)
    ret, yrs = load_minute_returns(a.start, a.interval)
    report(ret, yrs, a.interval)
    if not a.no_plot:
        plot_rolling(ret, a.interval)


if __name__ == "__main__":
    main()

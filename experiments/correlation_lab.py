"""CORRELATION LAB — cross-asset EDA across 6 crypto + 6 futures, to GENERATE hypotheses (not validate edges).

The user's idea: build correlation graphs across many scenarios to find candidate components for a predictive
overlay on top of the maker's (already-correct) fair-value formula. This tool does that DISCIPLINED — applying the
`data-detective` skill so the output is honest hypotheses, not p-hacked false positives.

GUARDRAILS (baked in — read before trusting any graph):
  1. RETURNS, not prices. Two trending price series always correlate (spurious). We correlate LOG-RETURNS.
  2. CAUSAL lead-lag. corr(A_t, B_{t+lag}) with lag>0 = "A leads B by lag" (A known before B moves = maybe
     tradeable). Contemporaneous corr (lag 0) is NOT tradeable — it's just co-movement.
  3. REGIME split. A correlation that isn't stable across sub-periods is not a law — report the split.
  4. The genuinely un-walled angle is CROSS-ASSET-CLASS (equities/commodities <-> crypto), NOT intra-crypto
     microstructure (that's HFT-walled). The lead-lag scan focuses there.
  5. A graph is a HYPOTHESIS, never an edge. Any candidate lead must then go through vet-idea -> the gate
     (residual after fee, deflated, n_loss>=30, joint-control) -> second-mind. A high R^2 here proves nothing tradeable.

ASSETS: crypto BTC/ETH/SOL/XRP/DOGE/BNB (Binance 1s spot -> 1-min) + futures NQ/ES/YM/RTY/CL/GC (1-min, back-adjusted).
Aligned on common 1-min timestamps (the intersection = US-futures-session minutes, since crypto is 24/7).

    python correlation_lab.py [--start 2026-01] [--horizon 1]    # builds panel cache + all graphs into correlation_lab/

Outputs (correlation_lab/, gitignored): heatmap_contemporaneous_<h>min.png, leadlag_crossclass.png,
regime_stability.png, scatter_top.png, and a printed lead-lag summary table.
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
from analysis import spot_data as SP

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT = "correlation_lab"
STOCKS = "C:/Users/roiy0/Desktop/stocks"
CRYPTO = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
FUT = ["NQ", "ES", "YM", "RTY", "CL", "GC"]   # equities + commodities
GAP_S = 95   # drop a 1-min return if the prior bar is >this many seconds back (session gaps / holes)


def _crypto_1min(coin, start):
    """Last close per UTC minute from the 1s store (fast numpy resample)."""
    d = SP.load_range(SP.SYMBOL[coin], start, fields=("sec", "close"))
    sec, close = d["sec"], d["close"]
    m = sec // 60
    last = np.where(np.diff(m, append=m[-1] + 1) != 0)[0]   # last index of each minute
    return pd.Series(close[last], index=pd.to_datetime(m[last] * 60, unit="s", utc=True), name=coin.upper())


def _fut_1min(sym, start):
    f = glob.glob(f"{STOCKS}/{sym}/{sym}_continuous_back_adjusted_*1min.csv")
    if not f:
        f = glob.glob(f"{STOCKS}/{sym}/{sym}_continuous_2022*1min.csv") or glob.glob(f"{STOCKS}/{sym}/{sym}_continuous_*1min.csv")
    df = pd.read_csv(sorted(f)[0], parse_dates=["Datetime"]).set_index("Datetime")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    s = df["Close"]
    s = s[s.index >= pd.Timestamp(start + "-01", tz="UTC")]
    s.name = sym
    return s[~s.index.duplicated(keep="last")]


def load_panel(start):
    cache = f"{OUT}/panel_{start}.parquet"
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(cache):
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass
    cols = {}
    for c in CRYPTO:
        try:
            cols[c.upper()] = _crypto_1min(c, start); print(f"  loaded crypto {c}")
        except SystemExit as e:
            print(f"  skip {c}: {e}")
    for s in FUT:
        try:
            cols[s] = _fut_1min(s, start); print(f"  loaded futures {s}")
        except Exception as e:
            print(f"  skip {s}: {type(e).__name__}")
    panel = pd.DataFrame(cols).sort_index()
    try:
        panel.to_parquet(cache)
    except Exception:
        pass
    return panel


def returns(panel, horizon):
    """log returns over `horizon` minutes, with session-gap returns masked (NaN)."""
    lp = np.log(panel)
    r = lp.diff(horizon)
    # mask returns spanning a gap (> horizon*60 + slack) using the index spacing
    dt = panel.index.to_series().diff(horizon).dt.total_seconds().values
    bad = dt > horizon * 60 + GAP_S
    r.iloc[bad] = np.nan
    return r


def heatmap(corr, title, path):
    order = list(corr.columns)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(order))); ax.set_xticklabels(order, rotation=90, fontsize=8)
    ax.set_yticks(range(len(order))); ax.set_yticklabels(order, fontsize=8)
    for i in range(len(order)):
        for j in range(len(order)):
            v = corr.values[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6,
                        color="white" if abs(v) > 0.5 else "black")
    ax.set_title(title, fontsize=10); fig.colorbar(im, fraction=0.046)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def leadlag(r, lags, path):
    """For each (futures, crypto) cross-class pair: corr(fut_t, crypto_{t+lag}). Peak lag>0 = futures LEADS crypto."""
    rows = []
    fig, ax = plt.subplots(figsize=(10, 6))
    for f in [x for x in FUT if x in r.columns]:
        for c in [x.upper() for x in CRYPTO if x.upper() in r.columns]:
            cc = [r[f].corr(r[c].shift(-lag)) for lag in lags]
            cc = np.array(cc)
            k = int(np.nanargmax(np.abs(cc)))
            peak_lag, peak = lags[k], cc[k]
            rows.append((f, c, lags[np.nanargmax(cc)], float(np.nanmax(cc)), peak_lag, float(peak), float(cc[lags.index(0)])))
            if abs(peak) > 0.04 and peak_lag != 0:   # only plot pairs with a non-trivial LEAD
                ax.plot(lags, cc, marker=".", ms=3, label=f"{f}->{c} (peak {peak:+.3f}@{peak_lag:+d}m)")
    ax.axvline(0, color="k", lw=0.6); ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("lag (min): >0 = futures LEADS crypto"); ax.set_ylabel("corr(fut_t, crypto_{t+lag})")
    ax.set_title("Cross-class lead-lag (returns) — a LEAD (peak at lag>0) is a candidate; lag 0 = just co-movement")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=6, ncol=2)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)
    return pd.DataFrame(rows, columns=["fut", "crypto", "argmax_lag", "max_corr", "peak_lag", "peak_corr", "contemp_corr"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01", help="YYYY-MM; earlier = more data, slower (v1 default recent)")
    ap.add_argument("--horizon", type=int, default=1, help="return horizon in minutes")
    args = ap.parse_args()
    print(f"building 12-asset 1-min panel from {args.start} ...")
    panel = load_panel(args.start)
    print(f"panel: {panel.shape[0]:,} minutes x {panel.shape[1]} assets  "
          f"{panel.index[0]} -> {panel.index[-1]}  (assets: {list(panel.columns)})")

    for h in sorted(set([args.horizon, 5])):
        r = returns(panel, h)
        corr = r.corr()
        heatmap(corr, f"Contemporaneous return correlation ({h}-min) — co-movement, NOT tradeable",
                f"{OUT}/heatmap_contemporaneous_{h}min.png")
        print(f"  [{h}min] heatmap saved; mean cross-class |corr| = "
              f"{np.nanmean(np.abs(corr.loc[FUT, [c.upper() for c in CRYPTO]].values)):.3f}")

    r = returns(panel, args.horizon)
    lags = list(range(-10, 11))
    tbl = leadlag(r, lags, f"{OUT}/leadlag_crossclass.png")
    print("\n  CROSS-CLASS LEAD-LAG (top by |peak corr|, peak_lag>0 = futures leads crypto):")
    print("    fut  crypto  peak_lag(min)  peak_corr  contemp_corr")
    for _, x in tbl.reindex(tbl.peak_corr.abs().sort_values(ascending=False).index).head(10).iterrows():
        flag = "  <- LEAD (candidate)" if x.peak_lag > 0 and abs(x.peak_corr) > 0.04 else ""
        print(f"    {x.fut:<4} {x.crypto:<5}  {int(x.peak_lag):+4d}          {x.peak_corr:+.3f}     {x.contemp_corr:+.3f}{flag}")

    # regime stability on the strongest cross-class pair
    best = tbl.reindex(tbl.peak_corr.abs().sort_values(ascending=False).index).iloc[0]
    f, c = best.fut, best.crypto
    half = len(panel) // 2
    fig, ax = plt.subplots(figsize=(9, 5))
    for lab, sl in [("first half", slice(0, half)), ("second half", slice(half, None))]:
        rr = returns(panel.iloc[sl], args.horizon)
        cc = [rr[f].corr(rr[c].shift(-lag)) for lag in lags]
        ax.plot(lags, cc, marker=".", label=lab)
    ax.axvline(0, color="k", lw=0.6); ax.axhline(0, color="k", lw=0.6)
    ax.set_title(f"Regime stability of {f}->{c} lead-lag (is the relationship the SAME across sub-periods?)")
    ax.set_xlabel("lag (min): >0 = futures leads"); ax.set_ylabel("corr"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{OUT}/regime_stability.png", dpi=130); plt.close(fig)

    # scatter + regression for the strongest LEAD (causal): fut_t vs crypto_{t+peak_lag}
    lag = int(best.peak_lag) if best.peak_lag != 0 else 1
    x = r[f].values; y = r[c].shift(-lag).values
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) > 100:
        b1, b0 = np.polyfit(x, y, 1); rr2 = np.corrcoef(x, y)[0, 1] ** 2
        fig, ax = plt.subplots(figsize=(6, 6))
        idx = np.random.default_rng(0).choice(len(x), min(20000, len(x)), replace=False)
        ax.scatter(x[idx] * 1e4, y[idx] * 1e4, s=2, alpha=0.2)
        xs = np.array([x.min(), x.max()])
        ax.plot(xs * 1e4, (b0 + b1 * xs) * 1e4, "r", lw=1.5, label=f"slope {b1:+.3f}  R^2 {rr2:.4f}")
        ax.set_xlabel(f"{f} return at t (bps)"); ax.set_ylabel(f"{c} return at t+{lag}min (bps)")
        ax.set_title(f"Strongest cross-class LEAD: {f}_t -> {c}_(t+{lag}m)   R^2={rr2:.4f}")
        ax.legend(); fig.tight_layout(); fig.savefig(f"{OUT}/scatter_top.png", dpi=130); plt.close(fig)
        print(f"\n  strongest LEAD {f}->{c} @ +{lag}m: slope {b1:+.3f}, R^2 {rr2:.4f}, n {len(x):,}")

    print("\n  READ (data-detective): these are CO-MOVEMENT + candidate LEADS, i.e. HYPOTHESES — NOT edges.")
    print("  A lead with peak_lag>0 and stable across regimes is worth ONE pre-registered test: does fut_t predict")
    print("  crypto's FUTURE RETURN beyond what's priced, net of cost? Route via vet-idea -> the gate -> second-mind.")
    print("  Most cross-class corr is contemporaneous (lag 0) = the global risk factor, not a tradeable lead.")


if __name__ == "__main__":
    main()

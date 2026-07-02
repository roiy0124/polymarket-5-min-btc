"""SMT ASYMMETRIC-BREAK fade — backtest of the user's unfinished smt_indicator on 4yr NQ/ES 1-min futures.

THE IDEA (from C:\\Users\\roiy0\\Desktop\\smt_indicator\\README.md): two highly-correlated futures (NQ & ES) break
recent 15-min levels TOGETHER ~95% of the time. The 5% where EXACTLY ONE breaks (XOR) is an "asymmetric break"; the
ICT thesis is that asymmetric breaks MEAN-REVERT (the breaker overshot, the disagreement resolves) more than
synchronized breaks. The trade: FADE THE BREAKER (high-break -> short it; low-break -> long it), hold 5-30 min.

WHY THIS IS WORTH TESTING (vs the walled published stuff): the CONCEPT is public ICT lore (LOW prior, generally
unsupported), but THIS specific real-time asymmetric-break rule is UNTESTED on our data and nobody has published a
clean kill of it. We measure it honestly with the project rigor stack and the README's own control (asymmetric vs
synchronized), on a tradeable instrument where we can compute REAL fade P&L (not a prediction-market residual).

CAUSAL CONSTRUCTION (no look-ahead): resample 1-min -> 15-min; a candle's (high,low) become a LEVEL PAIR active for
the next LOOKBACK_H hours. Scanning forward 1-min bars, find the FIRST bar where one instrument's bar-high breaks its
level while the other has NOT yet broken its matching level = asymmetric break, breaker = the one that broke first.
ENTER at the NEXT 1-min close (models a conservative ~1-min execution lag vs the README's sub-second goal); EXIT H
minutes later. Charge a futures round-trip cost. Cluster by trading day; gate via analysis.stats deflated
cluster-bootstrap on the per-trade return stream (n_loss>=30, deflated for the horizon/side grid).

THE CONTROL (decisive): the SAME fade applied to SYNCHRONIZED breaks (both instruments break ~together) and to ALL
breaks. The thesis is real only if the ASYMMETRIC fade reverts MORE than the synchronized one — i.e. the asymmetry,
not just "a level broke," carries the signal. If asymmetric ~ synchronized ~ 0, it's ICT noise.

    python experiment_smt_break.py [--swing] [--rth] [--horizons 5,15,30]

LOCKED defaults are pre-registered; report a small grid and DEFLATE for it. Low prior — expect noise; find out cheap.

VERDICT (2026-06-28, 4yr NQ/ES 1-min, 1.41M aligned bars) — DEAD, well-powered (NOT loss-light: 60k-80k losers).
The asymmetric-break thesis does not hold in ANY form tested:
  - FADE single-leg: ASYM −0.46 bps @5min (win 43%), deflated-p 1.000 = no-edge; the breaker does NOT revert
    (gross reversion ~+0.14 bps = noise, sub-cost). SYNC the same.
  - PAIR convergence (short breaker/long holder): ASYM −1.06 bps @5min (win 24%), deflated-p 1.000 = no-edge; the
    NQ-ES SPREAD does not revert either (mildly continues). Loses 2-leg cost.
  - DECISIVE CONTROL: ASYM ≈ SYNC at every horizon (diff ±0.02-0.27 bps inside huge CIs) → the ASYMMETRY adds NO
    information beyond "a level broke." Same null in the README's high-conviction --swing --rth mode (CIs straddle 0).
  After a level break (asym or sync), NQ/ES is ~a random walk; the ICT/SMT divergence thesis is empirically
  unsupported here. A clean, fast, well-powered kill of the user's own untested idea on the user's own data.
"""
import argparse
import glob
import sys

import numpy as np
import pandas as pd

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
from analysis import stats as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STOCKS = "C:/Users/roiy0/Desktop/stocks"
NQ_CSV = STOCKS + "/NQ/NQ_continuous_2022-05-03_to_2026-05-02_1min.csv"

# ---- LOCKED pre-registered constants ----
LEVEL_TF = "15min"
LOOKBACK_H = 4            # a level pair is active for this many hours
SWING_K = 2              # fractal-pivot half-width for --swing mode (causal: confirmed K candles later)
# futures round-trip cost in PRICE TICKS of slippage + commission, as a fraction of notional (conservative)
COST_FRAC = 0.00006      # ~1 tick/side slippage + commission on NQ/ES ~ 0.006% round trip


def _parse_nt(f):
    d = pd.read_csv(f, sep=";", header=None, names=["Datetime", "Open", "High", "Low", "Close", "Volume"],
                    dtype={"Datetime": str})
    d["Datetime"] = pd.to_datetime(d["Datetime"], format="%Y%m%d %H%M%S", errors="coerce", utc=True)
    return d.dropna(subset=["Datetime"]).set_index("Datetime")


def load_pair():
    nq = pd.read_csv(NQ_CSV, parse_dates=["Datetime"]).set_index("Datetime")
    if nq.index.tz is None:
        nq.index = nq.index.tz_localize("UTC")
    es = pd.concat([_parse_nt(f) for f in sorted(glob.glob(STOCKS + "/ES/ES *.txt"))])
    es = es.sort_values("Volume", ascending=False)
    es = es[~es.index.duplicated(keep="first")].sort_index()
    common = nq.index.intersection(es.index)
    nq, es = nq.loc[common], es.loc[common]
    return nq, es


def levels_15m(df, swing):
    """Per 15-min candle: (close_ts, high, low). With swing=True keep only fractal-pivot candles, CAUSALLY
    confirmed SWING_K candles after the pivot (the level becomes tradeable only at confirmation time)."""
    g = df.resample(LEVEL_TF, label="right", closed="right").agg(High=("High", "max"), Low=("Low", "min"))
    g = g.dropna()
    if not swing:
        return g.index.values, g["High"].values, g["Low"].values, g.index.values
    H, L = g["High"].values, g["Low"].values
    n = len(g); is_sh = np.zeros(n, bool); is_sl = np.zeros(n, bool)
    for i in range(SWING_K, n - SWING_K):
        if H[i] == max(H[i - SWING_K:i + SWING_K + 1]):
            is_sh[i] = True
        if L[i] == min(L[i - SWING_K:i + SWING_K + 1]):
            is_sl[i] = True
    # confirmation time = SWING_K candles later (causal); tradeable from then
    conf = g.index.values.copy()
    conf = np.array([g.index.values[min(i + SWING_K, n - 1)] for i in range(n)])
    return g.index.values, H, L, conf, is_sh, is_sl


def first_breach(bar_hi_or_lo, level, start_idx, win_bars, side):
    """First 1-min bar index in (start_idx, start_idx+win] where price breaks `level` (high: bar_high>level;
    low: bar_low<level). Returns the index or a large sentinel."""
    lo = start_idx + 1
    hi = min(start_idx + win_bars + 1, len(bar_hi_or_lo))
    if lo >= hi:
        return 10**9
    seg = bar_hi_or_lo[lo:hi]
    hit = (seg > level) if side == "high" else (seg < level)
    if not hit.any():
        return 10**9
    return lo + int(np.argmax(hit))


def run(nq, es, swing, rth, horizons):
    ts = nq.index.values
    nqH, nqL, nqC = nq["High"].values, nq["Low"].values, nq["Close"].values
    esH, esL, esC = es["High"].values, es["Low"].values, es["Close"].values
    win_bars = LOOKBACK_H * 60
    maxH = max(horizons)

    lv = levels_15m(nq, swing); lv_es = levels_15m(es, swing)
    lt, nqHi, nqLo, conf = lv[0], lv[1], lv[2], lv[3]
    _, esHi, esLo = lv_es[0], lv_es[1], lv_es[2]
    sh = lv[4] if swing else np.ones(len(lt), bool)
    sl = lv[5] if swing else np.ones(len(lt), bool)

    # map each level's confirmation timestamp to a 1-min bar index
    conf_idx = np.searchsorted(ts, conf)

    # RTH mask (rough US cash session 13:30-20:00 UTC; covers EST/EDT 9:30-16:00 core)
    def in_rth(idx):
        if not rth:
            return True
        h = pd.Timestamp(ts[idx]).hour + pd.Timestamp(ts[idx]).minute / 60.0
        return 13.5 <= h <= 20.0

    rows = []   # (kind, side, breaker, entry_idx, fade_rets[by horizon])
    for k in range(len(lt)):
        ci = conf_idx[k]
        if ci <= 0 or ci >= len(ts) - maxH - 1:
            continue
        for side, nq_lv, es_lv, ok in (("high", nqHi[k], esHi[k], sh[k]), ("low", nqLo[k], esLo[k], sl[k])):
            if not ok:
                continue
            bnq = first_breach(nqH if side == "high" else nqL, nq_lv, ci, win_bars, side)
            bes = first_breach(esH if side == "high" else esL, es_lv, ci, win_bars, side)
            if bnq == 10**9 and bes == 10**9:
                continue
            # asymmetric = exactly one breaks strictly before the other (or other never breaks in-window)
            if bnq < bes:
                kind, breaker, bbar = "ASYM", "NQ", bnq
            elif bes < bnq:
                kind, breaker, bbar = "ASYM", "ES", bes
            else:
                kind, breaker, bbar = "SYNC", "NQ", bnq   # same bar = synchronized
            ent = bbar + 1
            if ent + maxH >= len(ts) or not in_rth(ent):
                continue
            C = nqC if breaker == "NQ" else esC      # breaker close
            Ch = esC if breaker == "NQ" else nqC     # holder close
            p0, ph0 = C[ent], Ch[ent]
            if p0 <= 0 or ph0 <= 0:
                continue
            sgn = -1.0 if side == "high" else 1.0     # high-break -> short the breaker (fade up-overshoot)
            fade, conv = {}, {}
            for h in horizons:
                br = (C[ent + h] - p0) / p0           # breaker forward return
                hr = (Ch[ent + h] - ph0) / ph0        # holder forward return
                fade[h] = sgn * br - COST_FRAC                       # single-leg fade (README's literal trade)
                conv[h] = sgn * (br - hr) - 2 * COST_FRAC            # beta-1 PAIR: fade breaker vs holder, 2 legs
            day = str(pd.Timestamp(ts[ent]).date())
            rows.append((kind, side, breaker, day, fade, conv))
    return rows


def report(rows, horizons, label):
    print(f"\n{'='*96}\n  {label}   (total events: {len(rows)})\n{'='*96}")
    # idx 4 = fade (single-leg), idx 5 = conv (beta-1 pair)
    for trade_name, trade_idx in (("FADE single-leg", 4), ("PAIR conv (short breaker/long holder)", 5)):
        print(f"\n  ###### {trade_name} ######")
        for kind in ("ASYM", "SYNC"):
            sub = [r for r in rows if r[0] == kind]
            if not sub:
                continue
            days = np.array([r[3] for r in sub])
            print(f"  --- {kind}: n={len(sub)}, {len(np.unique(days))} days ---")
            for h in horizons:
                v = np.array([r[trade_idx][h] for r in sub], float)
                mean, lo, hi, p1, pdef = S.deflated_resid_p(v, days, n_trials=len(horizons) * 8)
                nloss = int((v <= 0).sum())
                verdict = ("SURVIVES" if (np.isfinite(pdef) and pdef < 0.05 and lo > 0 and nloss >= 30)
                           else (f"INSUFFICIENT(loss={nloss})" if nloss < 30 else "no-edge"))
                print(f"      @ {h:>2}min:  mean {mean*1e4:+6.2f} bps  CI[{lo*1e4:+.2f},{hi*1e4:+.2f}]bps  "
                      f"win {100*np.mean(v>0):.1f}%  deflated-p {pdef:.3f}  n_loss {nloss}  -> {verdict}")
        asym = [r for r in rows if r[0] == "ASYM"]; sync = [r for r in rows if r[0] == "SYNC"]
        if asym and sync:
            print(f"    CONTROL (ASYM - SYNC, does asymmetry add edge?):")
            for h in horizons:
                a = np.array([r[trade_idx][h] for r in asym]); s = np.array([r[trade_idx][h] for r in sync])
                print(f"      @ {h:>2}min:  ASYM {a.mean()*1e4:+.2f}  SYNC {s.mean()*1e4:+.2f}  "
                      f"=> diff {(a.mean()-s.mean())*1e4:+.2f} bps {'(asym>sync)' if a.mean()>s.mean() else '(no asym edge)'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swing", action="store_true", help="only fractal-pivot (swing) levels — fewer, higher-conviction")
    ap.add_argument("--rth", action="store_true", help="restrict entries to ~US cash session (13:30-20:00 UTC)")
    ap.add_argument("--horizons", default="5,15,30")
    args = ap.parse_args()
    horizons = [int(x) for x in args.horizons.split(",")]

    print("loading NQ + ES (4yr, 1-min, aligned)...")
    nq, es = load_pair()
    print(f"  {len(nq):,} aligned bars  {nq.index[0]} -> {nq.index[-1]}")
    rows = run(nq, es, args.swing, args.rth, horizons)
    lab = f"SMT asymmetric-break FADE  levels={'SWING' if args.swing else 'ALL-15m'}  " \
          f"{'RTH-only' if args.rth else 'all-hours'}  lookback={LOOKBACK_H}h  cost={COST_FRAC*1e4:.1f}bps"
    report(rows, horizons, lab)
    print("\n  READ: the thesis is REAL only if ASYM fade SURVIVES the deflated gate (n_loss>=30) AND reverts")
    print("  MORE than SYNC (the decisive control). ASYM~SYNC~0 = ICT noise. Cost charged; entry lags 1 bar.")


if __name__ == "__main__":
    main()

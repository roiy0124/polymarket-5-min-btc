"""Apply the rigor module (analysis/stats.py) to the REAL fired positions of each candidate.

Multiplicity-corrected verdict (deflated-Sharpe / PSR) on the live data, not synthetic. DSR is
shown across a range of HONEST trial counts N (we searched many configs/coins/thresholds), so the
sensitivity is explicit. A candidate that needs N=1 to look real was never real.

    python -m analysis.audit_candidates
"""
from __future__ import annotations
import numpy as np

import coins
from analysis import stats as S
from experiment_favorite_tail import load as ft_load


def report(label, asks, wons, wsids):
    asks = np.asarray(asks, float); wons = np.asarray(wons, float); wsids = np.asarray(wsids)
    print(f"\n--- {label}  (n={len(asks)}) ---")
    r = S.binary_bet_returns(asks, wons)
    ev, lo, hi = S.cluster_bootstrap_ci(r, wsids)
    print(f"  win {100*wons.mean():.1f}%  mean EV/$1 {ev:+.4f}  cluster-CI[{lo:+.4f},{hi:+.4f}]  "
          f"Sharpe {S.sharpe(r):+.3f}  skew {float(__import__('scipy.stats',fromlist=['skew']).skew(r)):+.2f}  "
          f"PSR(>0) {S.psr(r):.3f}")
    print(f"  DSR by honest trial count N:  " +
          "   ".join(f"N={N}:{S.deflated_sharpe(r, N)['dsr']:.3f}" for N in (1, 10, 30, 100)))
    k = int(wons.sum())
    print(f"  Wilson-LB(win) {S.wilson_lb(k, len(wons)):.3f} vs breakeven {0.0 if len(asks)==0 else __import__('net_ev').breakeven_winrate(asks.mean()):.3f}")


def audit_favorite_tail():
    print("=" * 80); print("FAVORITE-TAIL  (the base every other candidate sits on)  tl=30 ask>=0.95")
    print("=" * 80)
    allrows = []
    for c in coins.ENABLED:
        rows = ft_load(c, 30.0, 0.95, 12.0)
        allrows += [(c, ws, ask, won) for (ws, ask, won) in rows]
        if rows:
            a = np.array([x[1] for x in rows]); w = np.array([x[2] for x in rows]); ws = np.array([x[0] for x in rows])
            report(f"{c}", a, w, ws)
    if allrows:
        a = np.array([x[2] for x in allrows]); w = np.array([x[3] for x in allrows]); ws = np.array([x[1] for x in allrows])
        report("POOLED (all coins)", a, w, ws)
        print("\n  NOTE: pooled cluster-CI clusters by window_start (cross-coin within a window are correlated).")


def audit_spike_fade():
    print("\n" + "=" * 80); print("SPIKE-GATED FADE  (the newest candidate)  token drop<=-0.05 & spot z<-3")
    print("=" * 80)
    try:
        from experiment_fear_dip import load_all
        from experiment_spike_fade import spot_z_lookups, scan
        data, meta = load_all(coins.ENABLED)
        lk = spot_z_lookups("2026-06", 300.0)
        _, spike_dumps, _ = scan(data, meta, lk, 0.05, 3.0, (0.20, 0.85))
        if spike_dumps:
            a = np.array([r[4] for r in spike_dumps]); w = np.array([r[5] for r in spike_dumps])
            ws = np.array([r[1] for r in spike_dumps])
            report("spike-gated dumps (fade Up)", a, w, ws)
        else:
            print("  no spike-gated dumps")
    except Exception as e:
        print(f"  (skipped: {type(e).__name__}: {e})")


if __name__ == "__main__":
    audit_favorite_tail()
    audit_spike_fade()
    print("\n" + "=" * 80)
    print("READ: a candidate SURVIVES only if DSR>=0.95 at an HONEST N, the cluster-CI excludes 0,")
    print("and Wilson-LB(win)>breakeven with n>=30 losers. PSR<<1 even at N=1 means the negative")
    print("skew (-100% tail) already makes the mean-EV unreliable, before multiplicity.")
    print("=" * 80)

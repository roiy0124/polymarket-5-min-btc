"""FAVORITE-TAIL CONFIDENCE STACK — two independent forward loser-cutters (NEW candidate, 2026-06-26).

The favorite-tail dies only to its rare FLIPS. This stacks TWO independent, causal, forward signals that
each predict a flip BEYOND the favorite's own ask:
  1. OVER-ROUND tight (`up_ask+down_ask-1` low) = makers calm = the makers' revealed confidence
     ([[overround-gate-candidate]]). Self-normalized per coin.
  2. SPOT MARGIN large (`|price_binance - strike| / strike`, bps) = the favorite is physically FAR from the
     boundary, so a late spot wiggle is less likely to flip it. Self-normalized per coin (bps scales w/ vol).

Both are independent of the ask AND of each other (3-way joint logistic: ask +0.07 weak, over_round -0.31,
margin +0.37 — the two gates dominate the price). Stacking them ~DOUBLES the EV vs either alone:
  baseline ask[0.95,0.99)  -0.0068 (31 loss) | over_round +0.0065 (13) | margin +0.0046 (10) | STACK +0.0126 (5)

STATUS: the strongest favorite-tail edge found, and the additivity is real (two orthogonal forward signals).
BUT stacking cuts to ~5 losers => deeply loss-light => INSUFFICIENT by the gate, MORE power-starved than
either single gate. So: PROFITABLE-LOOKING but NOT yet validated. Keep the single over-round gate as the
robust primary; this stack is the EV-max variant pending more losers. Params LOCKED, do NOT re-tune.

    python experiment_favtail_stack.py [--adaptive]   (self-normalizing per-coin gates)
"""
import argparse
import sqlite3

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from analysis import stats as S
from analysis.adaptive import rolling_pct_rank, rolling_wilson_monitor


def load(coin, tl=30.0, ask_lo=0.95, ask_hi=0.99, tol=12.0):
    """Per resolved window: (ws, fav_ask, won, over_round, margin_bps) for favorites in [ask_lo,ask_hi)."""
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = conn.execute(
                "SELECT window_start, strike_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            conn.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen:
                continue
            seen.add(ws)
            r = conn.execute(
                "SELECT time_left, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_ask IS NOT NULL AND down_ask IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY ABS(time_left-?) LIMIT 1", (ws, tl)).fetchone()
            if not r:
                continue
            t_l, ua, da, px = r
            if abs(t_l - tl) > tol or not strike:
                continue
            fav_up = px >= strike
            fa = ua if fav_up else da
            if fa < ask_lo or fa >= ask_hi:
                continue
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fa, won, ua + da - 1.0, abs(px - strike) / strike * 1e4))
        conn.close()
    return out


def _z(x):
    x = np.asarray(x, float); return (x - x.mean()) / (x.std() + 1e-12)


def joint3(A, W, OR, MG, ws, B=300, seed=5):
    """3-way joint logistic won ~ ask + over_round + margin, with cluster-robust sign stability on the
    two gate coefs (1 random row per window). Confirms each gate is INDEPENDENT of the ask AND each other."""
    y = W.astype(float)
    def fit(rows):
        X = np.column_stack([np.ones(len(rows)), _z(A[rows]), _z(OR[rows]), _z(MG[rows])]); beta = np.zeros(4)
        for _ in range(80):
            p = 1 / (1 + np.exp(-X @ beta)); Wd = np.clip(p * (1 - p), 1e-6, None)
            g = X.T @ (y[rows] - p) - 1e-3 * beta; H = X.T @ (X * Wd[:, None]) + 1e-3 * np.eye(4)
            s = np.linalg.solve(H, g); beta += s
            if np.abs(s).max() < 1e-9:
                break
        return beta
    beta = fit(np.arange(len(A)))
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); orn = []; mgn = []
    for _ in range(B):
        pick = np.array([rng.choice(idx_by[c]) for c in uniq]); b = fit(pick); orn.append(b[2]); mgn.append(b[3])
    print(f"\n  3-WAY JOINT CONTROL  won ~ ask + over_round + margin (z):")
    print(f"      ask {beta[1]:+.3f}   over_round {beta[2]:+.3f} (neg<-win, neg in {100*np.mean(np.array(orn)<0):.0f}% refits)"
          f"   margin {beta[3]:+.3f} (pos<-win, pos in {100*np.mean(np.array(mgn)>0):.0f}% refits)")
    print(f"      => both gates {'INDEPENDENT of ask & each other (stack)' if (np.mean(np.array(orn)<0)>0.95 and np.mean(np.array(mgn)>0)>0.95) else 'one collapses under control'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adaptive", action="store_true", help="self-normalizing per-coin gates (recommended)")
    ap.add_argument("--lookback", type=int, default=200)
    args = ap.parse_args()
    rows = []
    for c in coins.ENABLED:
        for r in load(c):
            rows.append((c,) + r)
    co = np.array([r[0] for r in rows]); ws = np.array([r[1] for r in rows]); A = np.array([r[2] for r in rows])
    W = np.array([r[3] for r in rows]); OR = np.array([r[4] for r in rows]); MG = np.array([r[5] for r in rows])
    print(f"FAVORITE-TAIL CONFIDENCE STACK  ask[0.95,0.99)  n={len(rows)} losers={int((W==0).sum())}  "
          f"({'adaptive per-coin' if args.adaptive else 'fixed median'} gates)")
    print("=" * 84)
    print(f"  spot margin (bps): winners {MG[W==1].mean():.1f} vs LOSERS {MG[W==0].mean():.1f}  "
          f"| over_round: winners {OR[W==1].mean():+.4f} vs LOSERS {OR[W==0].mean():+.4f}")

    if args.adaptive:
        or_tight = rolling_pct_rank(OR, ws, lookback=args.lookback, groups=co) <= 0.5
        mg_large = rolling_pct_rank(MG, ws, lookback=args.lookback, groups=co) >= 0.5
        or_tight = np.where(np.isnan(or_tight), False, or_tight).astype(bool)
        mg_large = np.where(np.isnan(mg_large), False, mg_large).astype(bool)
    else:
        or_tight = OR <= np.median(OR); mg_large = MG >= np.median(MG)
    stacked = or_tight & mg_large
    for lbl, m in [("baseline", np.ones(len(A), bool)), ("tight over_round", or_tight),
                   ("large margin", mg_large), ("STACK (both)", stacked)]:
        if m.sum() < 10:
            print(f"  [{lbl}] n={int(m.sum())} too few"); continue
        a = S.assess(A[m], W[m], ws[m], n_trials=20, label=lbl)
        S.print_assess(a)
    joint3(A, W, OR, MG, ws)
    mon = rolling_wilson_monitor(ws, W, A, stacked, window=120)
    if mon:
        print(f"\n  DRIFT MONITOR (stack, rolling Wilson-LB - breakeven, w=120): latest {mon[0]:+.4f}, "
              f"frac<0 {mon[1]:.2f} ({mon[2]} steps)")
    print("\n  READ: two INDEPENDENT forward loser-cutters (maker confidence + distance-to-strike) STACK to ~2x")
    print("  the EV, but cut to ~5 losers => INSUFFICIENT (loss-light). Keep the single over-round gate as the")
    print("  robust primary; this stack is the EV-max variant pending >=30 stacked losers. Params LOCKED.")


if __name__ == "__main__":
    main()

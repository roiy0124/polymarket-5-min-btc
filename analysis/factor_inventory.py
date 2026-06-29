"""Factor inventory — measure each candidate microstructure factor's UNPRICED residual.

Generated from the 2026-06-25 trader-lens idea sweep (5 second-mind agents). The bar is NOT
"predicts the outcome" (the mid does too) — it is "predicts (resolved_outcome - up_mid) AFTER the
taker fee", window-clustered and deflated (analysis/stats). Each factor is computed CAUSALLY at a
decision time_left from data strictly before that instant.

Factors tested here (the non-degenerate, cheap ones — see header notes for what was pre-killed):
  - CTAP   cross-token net aggressor pressure (buyUp$ - buyDn$)/sum over trailing W  [corrected flow]
  - DEPTHA deep bid-depth imbalance Up vs Down (only ~18% of snaps are non-mirror -> mostly degenerate)
  - OVERND over-round (up_ask+down_ask-1) as a REGIME gate, not a trade (pays 2 fees if traded)
  - MICDIV micro-price complementarity divergence up_micro-(1-down_micro) (sub-cent, ~18% nonzero)

PRE-KILLED before coding (this session): two-token depth/micro factors are LARGELY DEGENERATE — the
Up and Down books are exact mirrors (price+size) in 81% of snapshots, so cross-token differencing is
mostly identically zero. Reported anyway on the ~18% independent subset for completeness.

    python -m analysis.factor_inventory [--tl 60] [--window 30]
"""
from __future__ import annotations
import argparse
import json
import sqlite3

import numpy as np

import coins
from analysis import stats as S


def _book_depth_imb(ub, db, mid_u, mid_d, reach=0.05):
    """Deep bid-depth imbalance: cum Up-bid size within `reach` of up_mid vs Down-bid size within
    reach of down_mid. Returns (imb, independent?) — independent=False if the two books mirror."""
    try:
        u = json.loads(ub); d = json.loads(db)
        ubids = u["bids"]; dbids = d["bids"]; uasks = u["asks"]; dasks = d["asks"]
        if not (ubids and dbids and uasks and dasks):
            return None, False
    except Exception:
        return None, False
    # mirror test on best level
    mirror = (abs(ubids[0][0] - (1 - dasks[0][0])) < 1e-9 and abs(ubids[0][1] - dasks[0][1]) < 1e-6
              and abs(uasks[0][0] - (1 - dbids[0][0])) < 1e-9 and abs(uasks[0][1] - dbids[0][1]) < 1e-6)
    up_d = sum(s for p, s in ubids if p >= mid_u - reach)
    dn_d = sum(s for p, s in dbids if p >= mid_d - reach)
    tot = up_d + dn_d
    return ((up_d - dn_d) / tot if tot > 0 else None), (not mirror)


def _micro(ub, db):
    """up_micro - (1 - down_micro): cross-book micro-price divergence (size-weighted best)."""
    try:
        u = json.loads(ub); d = json.loads(db)
        if not (u["bids"] and u["asks"] and d["bids"] and d["asks"]):
            return None
        ub0, ua0 = u["bids"][0], u["asks"][0]; db0, da0 = d["bids"][0], d["asks"][0]
        umic = (ub0[0] * ua0[1] + ua0[0] * ub0[1]) / (ub0[1] + ua0[1])
        dmic = (db0[0] * da0[1] + da0[0] * db0[1]) / (db0[1] + da0[1])
        return umic - (1 - dmic)
    except Exception:
        return None


def load_window_factors(coin, tl_target, window, tol=8.0):
    """Per resolved window: causal factor values at time_left~tl_target + outcome. Returns list of
    dicts with up_mid/up_ask/down_ask, ctap, deptha (+independent), micdiv, overrnd, won."""
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = conn.execute(
                "SELECT window_start, token_up, token_down, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down')").fetchall()
        except sqlite3.OperationalError:
            conn.close(); continue
        for ws, tok_up, tok_down, outcome in wins:
            if ws in seen:
                continue
            seen.add(ws)
            row = conn.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, up_book, down_book, down_mid FROM snapshots "
                "WHERE window_start=? AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND down_ask IS NOT NULL "
                "ORDER BY ABS(time_left-?) LIMIT 1", (ws, tl_target)).fetchone()
            if not row:
                continue
            tl, up_mid, up_ask, down_ask, ub, dbk, down_mid = row
            if abs(tl - tl_target) > tol:
                continue
            t_dec = ws + (300 - tl)            # decision instant (unix)
            # CTAP: cross-token net BUY pressure over trailing window
            bu = conn.execute("SELECT COALESCE(SUM(size),0) FROM trades WHERE asset_id=? AND side='BUY' "
                              "AND recv_ts>? AND recv_ts<=?", (tok_up, t_dec - window, t_dec)).fetchone()[0]
            bd = conn.execute("SELECT COALESCE(SUM(size),0) FROM trades WHERE asset_id=? AND side='BUY' "
                              "AND recv_ts>? AND recv_ts<=?", (tok_down, t_dec - window, t_dec)).fetchone()[0]
            ctap = (bu - bd) / (bu + bd) if (bu + bd) > 0 else None
            deptha, indep = (None, False)
            micdiv = None
            if ub and dbk:
                deptha, indep = _book_depth_imb(ub, dbk, up_mid, down_mid if down_mid else 1 - up_mid)
                micdiv = _micro(ub, dbk)
            out.append(dict(ws=ws, up_mid=up_mid, up_ask=up_ask, down_ask=down_ask,
                            ctap=ctap, deptha=deptha, indep=indep, micdiv=micdiv,
                            overrnd=up_ask + down_ask - 1.0, won=1 if outcome == "Up" else 0))
        conn.close()
    return out


def factor_residual(rows, key, label, indep_only=False):
    """Pearson(factor, residual=won-up_mid) with window-clustered bootstrap CI on the correlation,
    + the directional net-EV through stats.assess (bet sign(factor) side at its ask)."""
    R = [r for r in rows if r[key] is not None and (not indep_only or r["indep"])]
    if len(R) < 50:
        print(f"  [{label}] n={len(R)} too few"); return
    f = np.array([r[key] for r in R]); won = np.array([r["won"] for r in R], float)
    mid = np.array([r["up_mid"] for r in R]); ws = np.array([r["ws"] for r in R])
    resid = won - mid
    rho = S.pearson(f, resid)
    # window-clustered bootstrap CI on the correlation
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(3); boot = []
    for _ in range(2000):
        pick = rng.choice(uniq, len(uniq), replace=True)
        ri = np.concatenate([idx_by[c] for c in pick])
        boot.append(S.pearson(f[ri], resid[ri]))
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    print(f"  [{label}] n={len(R)}  corr(factor, won-mid) = {rho:+.4f}  cluster-CI[{lo:+.4f},{hi:+.4f}]"
          f"  {'**CI excludes 0**' if (lo > 0 or hi < 0) else '(spans 0)'}")
    # directional net-EV: bet the side the factor points to, at that side's ask
    side_up = f > 0
    asks = np.where(side_up, [r["up_ask"] for r in R], [r["down_ask"] for r in R])
    wons = np.where(side_up, won, 1 - won)
    nz = f != 0
    if nz.sum() >= 50:
        a = S.assess(asks[nz], wons[nz], ws[nz], n_trials=40, label=f"{label} directional taker")
        S.print_assess(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=60.0)
    ap.add_argument("--window", type=float, default=30.0, help="CTAP trailing trade window (s)")
    args = ap.parse_args()
    allrows = []
    for c in coins.ENABLED:
        rows = load_window_factors(c, args.tl, args.window)
        for r in rows:
            r["coin"] = c
        allrows += rows
        print(f"  loaded {c}: {len(rows)} windows @ tl~{args.tl:g}")
    print(f"\nFACTOR INVENTORY  tl~{args.tl:g}s  CTAP-window={args.window:g}s  (residual = won - up_mid; "
          f"gate = deflated cluster-bootstrap)")
    print("=" * 84)
    mir = np.mean([1 - r["indep"] for r in allrows if r["deptha"] is not None])
    print(f"  (book mirror-degeneracy: {100*mir:.0f}% of snaps are exact Up/Down mirrors)")
    factor_residual(allrows, "ctap", "CTAP cross-token aggressor")
    factor_residual(allrows, "deptha", "DEPTHA depth-imb (independent-book subset)", indep_only=True)
    factor_residual(allrows, "micdiv", "MICDIV micro-divergence")
    # over-round as a REGIME diagnostic: does wide over-round mark high-uncertainty windows?
    R = [r for r in allrows if r["overrnd"] is not None]
    orr = np.array([r["overrnd"] for r in R]); unc = np.abs(np.array([r["won"] - r["up_mid"] for r in R]))
    print(f"\n  [OVERND regime] corr(over_round, |won-mid|) = {S.pearson(orr, unc):+.4f}  "
          f"(>0 = wide over-round marks uncertain windows -> usable as a confidence gate)")
    print("=" * 84)


if __name__ == "__main__":
    main()

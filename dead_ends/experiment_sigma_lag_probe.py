"""Adversarial decomposition of the sigma-lag signal — is it the maker's STALE sigma, or just
recent-vol continuation (priced)? Run the decisive controls before believing the positive.

Decomposes staleness = realized_recent / implied_sigma and asks:
  (1) Does the RATIO beat its parts? won ~ ask + recent + implied  (do BOTH matter = mismatch story)
  (2) EXCLUDE the immediate 15s pre-decision move: realized over [45,90] (recent but not the last 15s).
      If the signal VANISHES, it was 'the flip is already underway' (continuation), not a stale sigma.
  (3) LOCO: does the joint-control sign hold leave-one-coin-out?
  (4) Loss concentration: are the high-staleness losers a few windows/coins (fragile) or spread?
"""
import sqlite3
import numpy as np
from scipy import stats as ss

import coins
PHIINV = ss.norm.ppf


def realized(path, lo, hi):
    tw = [(300.0 - r[0], r[4]) for r in path if lo <= r[0] <= hi and r[4] and r[4] > 0]
    if len(tw) < 10:
        return None
    tw.sort()
    t = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
    lr = np.diff(np.log(sp)); dt = np.diff(t); ok = dt > 0
    if ok.sum() < 8:
        return None
    rv = np.sqrt(np.mean(lr[ok] ** 2 / dt[ok]))
    return rv if (np.isfinite(rv) and rv > 0) else None


def load(coin, tl=30.0, ask_lo=0.95, ask_hi=0.99, tol=10.0):
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute("SELECT window_start, strike_binance, resolved_outcome FROM windows "
                               "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen or not strike or strike <= 0:
                continue
            seen.add(ws)
            path = con.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND down_ask IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY time_left DESC", (ws,)).fetchall()
            if len(path) < 30:
                continue
            dec = min(path, key=lambda r: abs(r[0] - tl))
            t_l, um, ua, da, px = dec
            if abs(t_l - tl) > tol or not (0.02 < um < 0.98) or px <= 0:
                continue
            fav_up = px >= strike; fav_ask = ua if fav_up else da
            if fav_ask < ask_lo or fav_ask >= ask_hi:
                continue
            z = PHIINV(um)
            if abs(z) < 0.3:
                continue
            implied = abs(np.log(px / strike) / np.sqrt(t_l) / z)
            r_imm    = realized(path, tl, tl + 15.0)       # last 15s before decision
            r_recent = realized(path, tl, tl + 45.0)       # last 45s
            r_early  = realized(path, tl + 15.0, tl + 60.0)  # 45s window EXCLUDING the immediate 15s
            r_trail  = realized(path, tl + 45.0, tl + 170.0)
            if None in (implied, r_imm, r_recent, r_early, r_trail) or implied <= 0:
                continue
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fav_ask, won, ua + da - 1.0, implied, r_imm, r_recent, r_early, r_trail))
        con.close()
    return out


def fit(X, y, ridge=1e-3):
    Xb = np.column_stack([np.ones(len(y)), X]); b = np.zeros(Xb.shape[1])
    for _ in range(60):
        p = 1 / (1 + np.exp(-Xb @ b)); Wd = np.clip(p * (1 - p), 1e-6, None)
        g = Xb.T @ (y - p) - ridge * b; H = Xb.T @ (Xb * Wd[:, None]) + ridge * np.eye(Xb.shape[1])
        s = np.linalg.solve(H, g); b += s
        if np.abs(s).max() < 1e-9:
            break
    return b


def zc(v):
    v = np.asarray(v, float); return (v - v.mean()) / (v.std() + 1e-12)


def joint(asks, wons, ws, cols, names, target_idx, B=300, seed=5):
    """Logistic won ~ [cols]; report coef + cluster-robust neg-fraction + perm p for cols[target_idx]."""
    y = wons.astype(float); X = np.column_stack([zc(c) for c in cols])
    pos = target_idx + 1
    b = fit(X, y)
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); co = []
    for _ in range(B):
        pick = np.array([rng.choice(idx_by[c]) for c in uniq])
        co.append(fit(X[pick], y[pick])[pos])
    co = np.array(co); neg = float(np.mean(co < 0))
    null = []
    for _ in range(B):
        Xp = X.copy(); Xp[:, target_idx] = rng.permutation(X[:, target_idx]); null.append(fit(Xp, y)[pos])
    pperm = float(np.mean(np.array(null) <= b[pos]))
    tgt = names[target_idx]
    print(f"    won ~ {' + '.join(names)}:  {tgt} coef {b[pos]:+.3f}  neg {100*neg:.0f}%  perm-p {pperm:.3f}"
          f"   {'PASS' if (neg>0.95 and pperm<0.05) else 'fail'}")
    return b[pos], neg, pperm


def main():
    rows = []
    for c in coins.ENABLED:
        rows += [(c,) + x for x in load(c)]
    coin = np.array([r[0] for r in rows]); ws = np.array([r[1] for r in rows], float)
    asks = np.array([r[2] for r in rows], float); wons = np.array([r[3] for r in rows], float)
    imp = np.array([r[5] for r in rows], float); r_imm = np.array([r[6] for r in rows], float)
    r_rec = np.array([r[7] for r in rows], float); r_early = np.array([r[8] for r in rows], float)
    r_tr = np.array([r[9] for r in rows], float)
    stale = r_rec / imp; stale_early = r_early / imp
    print(f"n={len(rows)} losers={int((wons==0).sum())}\n")

    print("(1) DECOMPOSITION — is it the RATIO (mismatch) or just one part?")
    joint(asks, wons, ws, [asks, stale],            ["ask", "staleness"],          1)
    joint(asks, wons, ws, [asks, r_rec],            ["ask", "recent_vol"],         1)
    joint(asks, wons, ws, [asks, imp],              ["ask", "implied_sigma"],      1)
    joint(asks, wons, ws, [asks, r_rec, imp],       ["ask", "recent_vol", "implied_sigma"], 1)
    joint(asks, wons, ws, [asks, r_rec, imp],       ["ask", "recent_vol", "implied_sigma"], 2)

    print("\n(2) EXCLUDE the immediate 15s — staleness from realized[45,90] only (drop the last 15s):")
    print("    If this VANISHES, the signal was 'flip already underway' (continuation), not stale sigma.")
    joint(asks, wons, ws, [asks, stale_early],      ["ask", "staleness_excl_15s"], 1)
    joint(asks, wons, ws, [asks, r_imm],            ["ask", "immediate_15s_vol"],  1)

    print("\n(3) LOCO — does won~ask+staleness keep staleness NEGATIVE leaving each coin out?")
    for c in coins.ENABLED:
        m = coin != c
        if m.sum() < 50 or len(np.unique(ws[m])) < 10:
            continue
        b, neg, p = joint(asks[m], wons[m], ws[m], [asks[m], stale[m]], ["ask", f"stale(no-{c})"], 1)

    print("\n(4) LOSS CONCENTRATION — high-staleness losers by coin (fragile if one coin/few windows):")
    hi = stale >= np.quantile(stale, 0.75)
    losers = hi & (wons == 0)
    from collections import Counter
    print("    high-staleness losers per coin:", dict(Counter(coin[losers].tolist())))
    print(f"    total high-staleness losers: {int(losers.sum())} across "
          f"{len(np.unique(ws[losers]))} distinct windows")


if __name__ == "__main__":
    main()

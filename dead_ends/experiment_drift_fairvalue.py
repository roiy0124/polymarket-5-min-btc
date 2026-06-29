"""DRIFT-AUGMENTED FAIR VALUE — predict the FUTURE value (near-trend drift) vs the maker's DRIFTLESS quote.

User pivot 2026-06-28: a quant equation that predicts not the current value but the FUTURE value of the near
trend, traded against the maker. The maker prices a MARTINGALE: up_mid = Phi(moneyness_now / (sigma*sqrt(t))),
with NO drift term. If the near-future has a predictable drift mu the maker ignores, the TRUE prob is
Phi((moneyness_now + mu*t)/(sigma*sqrt(t))) and we trade the gap.

  back out the maker's own sigma from its quote: z = Phi^-1(up_mid),  implied = moneyness_now/(sqrt(t)*z)
  causal near-trend drift mu_hat = mean per-second log-return of spot over a trailing window (strictly before t)
  drift-augmented forecast: P_up = Phi( z + mu_hat*sqrt(t)/implied )        [exactly up_mid shifted by the drift]
  signal = P_up - up_mid   (our future-value forecast minus the maker's current driftless quote)

THE DECISIVE TEST (the program's residual lens): does `signal` predict the UNPRICED residual won - up_mid,
i.e. does the drift survive controlling for the maker's mid in a joint logistic? If the maker already prices the
trend (our prior: experiment_trend_outcome.py found residual ~0), the drift coef COLLAPSES -> walled. If it keeps
a significant coef AND the directional trade clears the fee -> a real edge (would be large). Honest prior: walled
+ fee-capped (drift flips outcomes near p=0.5 where the fee peaks). Gate through stats.assess; second-mind any positive.

    python experiment_drift_fairvalue.py [--tl 30] [--win 120] [--thresh 0.03]
"""
import argparse
import sqlite3

import numpy as np
from scipy import stats as ss

import coins
from analysis import stats as S
from net_ev import net_ev_per_dollar

PHI = ss.norm.cdf
PHIINV = ss.norm.ppf


def load(coin, tl, win, tol=10.0):
    """(ws, up_ask, down_ask, up_mid, won_up, signal, mu_shift) at decision tl, with a causal trailing-drift signal."""
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
            before = [r for r in path if r[0] >= tl - 0.5]
            ent = min(before, key=lambda r: r[0] - tl) if before else None
            if not ent or ent[0] - tl > tol:
                continue
            t_l, um, ua, da, px = ent
            if not (0.02 < um < 0.98) or px <= 0:
                continue
            money = np.log(px / strike)
            z = PHIINV(um)
            if abs(z) < 1e-6:
                continue
            implied = abs(money / (np.sqrt(t_l) * z))
            if not (implied > 0 and np.isfinite(implied)):
                continue
            # causal near-trend drift: per-second mean log-return over the trailing `win` seconds BEFORE decision
            tw = [(300.0 - r[0], r[4]) for r in path if t_l <= r[0] <= t_l + win and r[4] and r[4] > 0]
            if len(tw) < 10:
                continue
            tw.sort()
            tt = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
            lr = np.diff(np.log(sp)); dt = np.diff(tt); ok = dt > 0
            if ok.sum() < 8:
                continue
            mu = np.sum(lr[ok]) / np.sum(dt[ok])                      # per-second drift
            shift = mu * np.sqrt(t_l) / implied                       # z-units shift from drift over remaining t
            p_up = float(PHI(z + shift))
            signal = p_up - um
            won_up = 1 if outcome == "Up" else 0
            out.append((ws, ua, da, um, won_up, signal, shift))
        con.close()
    return out


def fit_logit(X, y, ridge=1e-3):
    Xb = np.column_stack([np.ones(len(y)), X]); b = np.zeros(Xb.shape[1])
    for _ in range(60):
        p = 1 / (1 + np.exp(-np.clip(Xb @ b, -30, 30))); Wd = np.clip(p * (1 - p), 1e-6, None)
        g = Xb.T @ (y - p) - ridge * b; H = Xb.T @ (Xb * Wd[:, None]) + ridge * np.eye(Xb.shape[1])
        b += np.linalg.solve(H, g)
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--win", type=float, default=120.0, help="trailing seconds for the drift estimate")
    ap.add_argument("--thresh", type=float, default=0.03, help="|signal| needed to take the directional trade")
    args = ap.parse_args()

    rows = []
    for c in coins.ENABLED:
        rows += [(c,) + x for x in load(c, args.tl, args.win)]
    if len(rows) < 50:
        print("  too few rows."); return
    ws = np.array([r[1] for r in rows], float)
    ua = np.array([r[2] for r in rows], float); da = np.array([r[3] for r in rows], float)
    mid = np.array([r[4] for r in rows], float); won = np.array([r[5] for r in rows], float)
    sig = np.array([r[6] for r in rows], float)

    resid = won - mid                                        # the UNPRICED part (what we must predict)
    print(f"DRIFT-AUGMENTED FAIR VALUE  tl~{args.tl:g}  drift-win {args.win:g}s  |signal|>= {args.thresh:g}  n={len(rows)}")
    print("=" * 90)
    print(f"  signal = drift-forecast P_up - maker mid:  mean {sig.mean():+.4f}  sd {sig.std():.4f}  "
          f"|signal|>=thresh in {100*np.mean(np.abs(sig)>=args.thresh):.1f}% of windows")
    print(f"  corr(signal, residual won-mid) = {np.corrcoef(sig, resid)[0,1]:+.4f}  "
          f"(want >0 = our drift predicts the UNPRICED part)")

    # ---- THE DECISIVE TEST: does the drift signal predict won BEYOND the maker's mid? ----
    def z(v): return (v - v.mean()) / (v.std() + 1e-12)
    X = np.column_stack([z(mid), z(sig)])
    b = fit_logit(X, won)
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(3); coefs = []
    for _ in range(300):
        pick = np.array([rng.choice(idx_by[c]) for c in uniq]); coefs.append(fit_logit(X[pick], won[pick])[2])
    coefs = np.array(coefs); pos = float(np.mean(coefs > 0))
    null = []
    for _ in range(300):
        Xp = X.copy(); Xp[:, 1] = rng.permutation(X[:, 1]); null.append(fit_logit(Xp, won)[2])
    pperm = float(np.mean(np.array(null) >= b[2]))
    print(f"\n  JOINT CONTROL  won ~ maker_mid + drift_signal (z-scored):")
    print(f"      mid coef {b[1]:+.3f}   drift_signal coef {b[2]:+.3f}  (want drift POSITIVE & significant "
          f"BEYOND the mid)")
    print(f"      cluster-robust: drift coef POSITIVE in {100*pos:.0f}% of refits   permutation p={pperm:.3f}")
    print(f"      => {'drift adds info BEYOND the price' if (pos>0.95 and pperm<0.05) else 'COLLAPSES given the mid (maker already prices the trend = walled)'}")

    # ---- the directional trade: buy the side the drift favors when |signal| is large ----
    take = np.abs(sig) >= args.thresh
    buy_up = take & (sig > 0)
    buy_dn = take & (sig < 0)
    asks = np.where(buy_up, ua, np.where(buy_dn, da, np.nan))
    wons = np.where(buy_up, won, np.where(buy_dn, 1 - won, np.nan))
    m = take & np.isfinite(asks)
    print(f"\n  DIRECTIONAL TRADE (buy the drift side when |signal|>= {args.thresh:g}):  n={int(m.sum())} "
          f"(Up {int(buy_up.sum())}, Down {int(buy_dn.sum())})")
    if m.sum() >= 20:
        print(f"      mean entry ask {asks[m].mean():.3f} (near 0.5 = peak fee zone {0.07* (asks[m].mean())*(1-asks[m].mean())*100:.2f}%/share)")
        a = S.assess(asks[m], wons[m], ws[m], n_trials=S.N_PROGRAM, label="drift-directional trade")
        S.print_assess(a)
    else:
        print(f"      too few trades at this threshold.")
    print("\n  READ: real ONLY if (a) corr(signal,residual)>0, (b) the drift coef stays POSITIVE & significant")
    print("  beyond the mid in the joint control, AND (c) the directional trade clears the fee net. If the drift")
    print("  coef collapses given the mid, the maker already prices the near-trend (efficient-on-knowledge) = the")
    print("  walled directional game, now closed with the principled drift-augmented formulation.")


if __name__ == "__main__":
    main()

"""CONDITIONAL SIGMA-LAG — the maker's vol input is STALE, not just padded (Thread A, 2026-06-27).

Story (the factor). The maker is a digital-option bot quoting up_mid = Phi(ln(spot/strike)/(sigma*sqrt(t)))
off a TRAILING-window sigma. The favorite-tail dies only to FLIPS — a fast adverse spot move in the last
seconds. The AVERAGE sigma-error is self-priced/EV-neutral (VRP harvest, dead: experiment_vrp_harvest.py).
The conditional thread is DIFFERENT: when recent realized vol has just ACCELERATED past what the maker is
charging (realized_recent >> implied_sigma), the maker's sigma is transiently TOO LOW — it under-prices the
flip risk for a beat before its estimator catches up. In those "stale-low" windows the favorite is more
flip-prone than its price implies, so SKIP them; keep the calm/decaying-vol windows where the favorite is
genuinely safe. This is a FILTER on favorite-tail, like the over-round gate but on an orthogonal signal:
the spot's own recent-vs-charged vol mismatch, not the makers' revealed spread.

  staleness   = realized_recent / implied_sigma   (>1 = recent vol exceeds what the maker charges = stale-low)
  vol_accel   = realized_recent / realized_trailing (>1 = vol regime accelerating; the lag trigger)
  vrp_level   = implied_sigma / realized_trailing (the OLD/priced level signal — control, expect dead)

THE DECISIVE TEST (the one the dead B-filter failed, the over-round gate passed): the JOINT logistic
won ~ fav_ask + staleness. The maker prices off Binance (R2=0.75) and re-quotes ~continuously, so a recent
spot MOVE is already in fav_ask. Staleness only survives if the maker's sigma (the SHAPE) lags even though
its spot (the LOCATION) is current — a 2nd-order effect that may well be priced. If the staleness coef
collapses once fav_ask is in the model, it is priced -> DEAD (an honest kill is a real result). If it keeps a
significant NEGATIVE coef (stale -> losing) independent of price AND of over_round, it is a real unpriced lag.

    python experiment_sigma_lag.py [--tl 30] [--ask-lo 0.95] [--ask-hi 0.99] [--pct 0.5] [--lookback 200]
"""
import argparse
import sqlite3

import numpy as np
from scipy import stats as ss

import coins
from analysis import stats as S
from analysis.adaptive import rolling_pct_rank, stability_by_bin, rolling_wilson_monitor
from net_ev import net_ev_per_dollar, wilson_lb, breakeven_winrate

PHIINV = ss.norm.ppf


def _realized(path_rows, tl_lo, tl_hi):
    """Per-sqrt-second realized vol of spot over the causal time-left band [tl_lo, tl_hi]
    (tl_hi is the OLDER edge, tl_lo the more recent). Returns None if too few clean ticks."""
    tw = [(300.0 - r[0], r[4]) for r in path_rows if tl_lo <= r[0] <= tl_hi and r[4] and r[4] > 0]
    if len(tw) < 12:
        return None
    tw.sort()                                            # by elapsed (ascending time)
    t = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
    lr = np.diff(np.log(sp)); dt = np.diff(t); ok = dt > 0
    if ok.sum() < 10:
        return None
    rv = np.sqrt(np.mean(lr[ok] ** 2 / dt[ok]))
    return rv if (np.isfinite(rv) and rv > 0) else None


def load(coin, tl, ask_lo, ask_hi, tol=10.0):
    """Per resolved favorite-tail window at time_left~tl:
       (ws, fav_ask, won, over_round, implied_sigma, realized_recent, realized_trailing)."""
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute(
                "SELECT window_start, strike_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, strike, outcome in wins:
            if ws in seen or not strike or strike <= 0:
                continue
            seen.add(ws)
            path = con.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, price_binance FROM snapshots "
                "WHERE window_start=? AND up_mid IS NOT NULL AND up_ask IS NOT NULL "
                "AND down_ask IS NOT NULL AND price_binance IS NOT NULL ORDER BY time_left DESC",
                (ws,)).fetchall()
            if len(path) < 30:
                continue
            dec = min(path, key=lambda r: abs(r[0] - tl))
            t_l, um, ua, da, px = dec
            if abs(t_l - tl) > tol or not (0.02 < um < 0.98) or px <= 0:
                continue
            fav_up = px >= strike
            fav_ask = ua if fav_up else da
            if fav_ask < ask_lo or fav_ask >= ask_hi:
                continue
            z = PHIINV(um)
            if abs(z) < 0.3:                              # favorites -> z large -> implied sigma stable
                continue
            implied = abs(np.log(px / strike) / np.sqrt(t_l) / z)
            if not (implied > 0 and np.isfinite(implied)):
                continue
            r_recent = _realized(path, tl, tl + 45.0)         # the ~45s just before decision
            r_trail  = _realized(path, tl + 45.0, tl + 170.0)  # the older ~2 min (what its sigma reflects)
            if r_recent is None or r_trail is None:
                continue
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fav_ask, won, ua + da - 1.0, implied, r_recent, r_trail))
        con.close()
    return out


def _fit_logistic(X, y, ridge=1e-3):
    """Ridge-stabilised logistic via IRLS (no sklearn). X already z-scored; returns beta incl intercept."""
    Xb = np.column_stack([np.ones(len(y)), X]); beta = np.zeros(Xb.shape[1])
    for _ in range(60):
        p = 1 / (1 + np.exp(-Xb @ beta)); Wd = np.clip(p * (1 - p), 1e-6, None)
        g = Xb.T @ (y - p) - ridge * beta
        H = Xb.T @ (Xb * Wd[:, None]) + ridge * np.eye(Xb.shape[1])
        step = np.linalg.solve(H, g); beta += step
        if np.abs(step).max() < 1e-9:
            break
    return beta


def joint_control(asks, wons, sig, ws, sig_name, extra=None, extra_name=None, B=300, seed=5):
    """won ~ fav_ask + sig  (+ optional extra covariate). Want `sig` to keep a NEGATIVE coef after
    fav_ask (high signal -> losing, independent of the priced favorite price). Cluster-robust sign
    stability (1 random row/window/refit) + permutation p on the sig coefficient."""
    y = wons.astype(float)
    def zc(v): return (v - v.mean()) / (v.std() + 1e-12)
    a, s = zc(asks), zc(sig)
    cols = [a, s]; sig_pos = 2
    if extra is not None:
        cols = [a, zc(extra), s]; sig_pos = 3
    X = np.column_stack(cols)
    beta = _fit_logistic(X, y)
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); coefs = []
    for _ in range(B):
        pick = np.array([rng.choice(idx_by[c]) for c in uniq])
        coefs.append(_fit_logistic(X[pick], y[pick])[sig_pos])
    coefs = np.array(coefs); neg = float(np.mean(coefs < 0))
    null = []
    scol = X[:, sig_pos - 1]
    for _ in range(B):
        Xp = X.copy(); Xp[:, sig_pos - 1] = rng.permutation(scol)
        null.append(_fit_logistic(Xp, y)[sig_pos])
    pperm = float(np.mean(np.array(null) <= beta[sig_pos]))
    extra_txt = f" + {extra_name}" if extra is not None else ""
    print(f"\n  JOINT CONTROL  won ~ fav_ask{extra_txt} + {sig_name}  (z-scored):")
    print(f"      fav_ask coef {beta[1]:+.3f}   {sig_name} coef {beta[sig_pos]:+.3f}  "
          f"(want {sig_name} NEGATIVE = stale->losing, independent of price)")
    print(f"      cluster-robust: {sig_name} coef NEGATIVE in {100*neg:.0f}% of refits   permutation p={pperm:.3f}")
    real = (neg > 0.95 and pperm < 0.05)
    print(f"      => {'SIGNAL real & ask-independent' if real else 'collapses under control (priced / dead)'}")
    return real


def ev_row(A, W):
    if len(A) < 8:
        return None
    per = [net_ev_per_dollar(a, w, "taker", "hold") for a, w in zip(A, W)]
    return len(A), int((W == 0).sum()), 100 * W.mean(), float(np.mean(per)), \
        wilson_lb(int(W.sum()), len(W)) - breakeven_winrate(A.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--ask-lo", type=float, default=0.95, dest="ask_lo")
    ap.add_argument("--ask-hi", type=float, default=0.99, dest="ask_hi")
    ap.add_argument("--pct", type=float, default=0.5, help="adaptive: keep staleness rolling-pct-rank <= this (low=safe)")
    ap.add_argument("--lookback", type=int, default=200)
    args = ap.parse_args()

    rows = []
    for c in coins.ENABLED:
        r = load(c, args.tl, args.ask_lo, args.ask_hi)
        rows += [(c,) + x for x in r]
        print(f"  loaded {c}: {len(r)} favorite-tail windows")
    if len(rows) < 50:
        print("  too few rows — need more data."); return
    coin = np.array([r[0] for r in rows])
    ws   = np.array([r[1] for r in rows], float)
    asks = np.array([r[2] for r in rows], float)
    wons = np.array([r[3] for r in rows], float)
    orr  = np.array([r[4] for r in rows], float)
    imp  = np.array([r[5] for r in rows], float)
    rrec = np.array([r[6] for r in rows], float)
    rtr  = np.array([r[7] for r in rows], float)

    staleness = rrec / imp                 # >1 = recent vol exceeds charged sigma = maker stale-low
    vol_accel = rrec / rtr                 # >1 = vol regime accelerating
    vrp_level = imp / rtr                  # the OLD (priced) level signal -- control

    print(f"\nCONDITIONAL SIGMA-LAG  favorite-tail ask[{args.ask_lo},{args.ask_hi}) tl~{args.tl:g}  "
          f"n={len(rows)} losers={int((wons==0).sum())}")
    print("=" * 90)
    print(f"  median staleness(recent/implied)={np.median(staleness):.2f}  "
          f"median vol_accel(recent/trail)={np.median(vol_accel):.2f}")
    print(f"  staleness on WINNERS {staleness[wons==1].mean():.3f}  vs LOSERS {staleness[wons==0].mean():.3f}  "
          f"(losers HIGHER = stale-low -> flip)")
    print(f"  corr(staleness, over_round)={np.corrcoef(staleness, orr)[0,1]:+.3f}  "
          f"corr(staleness, fav_ask)={np.corrcoef(staleness, asks)[0,1]:+.3f}  (orthogonal stack-partners?)")

    # ---- EV by staleness bucket (does the edge sort monotone with the lag?) ----
    print(f"\n  {'staleness bucket':>22} {'n':>5} {'loss':>4} {'win%':>6} {'EV':>9} {'wlb-be':>8}")
    qs = np.quantile(staleness, [0, 0.5, 0.75, 0.9, 1.0])
    for i in range(len(qs) - 1):
        hi = (staleness <= qs[i + 1]) if i == len(qs) - 2 else (staleness < qs[i + 1])
        m = (staleness >= qs[i]) & hi
        e = ev_row(asks[m], wons[m])
        if e:
            print(f"  {f'[{qs[i]:.2f},{qs[i+1]:.2f})':>22} {e[0]:>5} {e[1]:>4} {e[2]:>5.1f}% {e[3]:>+9.4f} {e[4]:>+8.4f}")

    # ---- baseline vs the staleness FILTER (keep low-staleness) ----
    print()
    a0 = S.assess(asks, wons, ws, n_trials=S.N_PROGRAM, label="baseline favorite-tail (ungated)")
    S.print_assess(a0)

    # SELF-NORMALIZING gate (PRIMARY), per coin: keep windows whose staleness is in the LOW half of the
    # coin's OWN trailing distribution (maker NOT stale). No fitted const; tracks drift, zero new DOF.
    rank = rolling_pct_rank(staleness, ws, lookback=args.lookback, groups=coin)
    g_adp = np.isfinite(rank) & (rank <= args.pct)
    print(f"\n  --- ADAPTIVE per-coin gate: keep staleness rolling-pct-rank <= {args.pct:g} "
          f"(lookback {args.lookback}) ---")
    a_adp = S.assess(asks[g_adp], wons[g_adp], ws[g_adp], n_trials=S.N_PROGRAM,
                     label="GATED keep-low-staleness (adaptive per-coin)")
    S.print_assess(a_adp)

    # ---- THE DECISIVE CONTROLS ----
    real1 = joint_control(asks, wons, staleness, ws, "staleness")
    real2 = joint_control(asks, wons, staleness, ws, "staleness", extra=orr, extra_name="over_round")
    # control: the OLD level signal (expect priced/dead)
    joint_control(asks, wons, vrp_level, ws, "vrp_level(control)")

    # ---- drift monitor + by-thirds ----
    mon = rolling_wilson_monitor(ws, wons, asks, g_adp, window=150)
    print(f"\n  DRIFT MONITOR (rolling Wilson-LB(win) - breakeven, window=150 gated bets):")
    if mon:
        print(f"      latest LB-breakeven = {mon[0]:+.4f}   fraction below 0 = {mon[1]:.2f}  ({mon[2]} steps)")
    else:
        print(f"      (not enough gated bets yet for a 150-window monitor)")
    print(f"  by-thirds smoke-alarm:")
    for i, b in enumerate(stability_by_bin(ws, wons, g_adp, bins=3)):
        print(f"      third {i+1}: n={b['n']:>4} loss={b['loss']:>3} win={100*b['win']:.1f}%")

    print("\n  READ: real iff (a) losers concentrate at HIGH staleness (EV sorts monotone down), (b) the gated")
    print("  keep-low set lifts EV with a non-trivial loss count, AND (c) the joint control keeps staleness")
    print("  NEGATIVE & significant after fav_ask AND over_round. If the coef collapses, the maker already")
    print("  prices the lag (its Binance quote is current) -> DEAD, and that is a clean, honest kill.")
    print(f"\n  SUMMARY: joint(ask) {'PASS' if real1 else 'fail'} | joint(ask+over_round) "
          f"{'PASS' if real2 else 'fail'}")


if __name__ == "__main__":
    main()

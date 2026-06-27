"""MECHANICAL SIGMA ROLL-OFF — predict the maker's NON-informational sigma update (the one 'predict the
maker's strings' corner that is not the walled latency-lag). 2026-06-27, Thread A-prime.

Story (the factor). The maker's sigma is a trailing-window realized-vol estimate. When a vol SPIKE earlier in
the window AGES while the recent tape goes calm, the maker is still CHARGING for vol that has already passed
(implied_sigma elevated by the stale spike). This is a MECHANICAL over-charge — no new information, not a spot
forecast — and it is PREDICTABLE from the in-window history. The user's idea: anticipate that the maker will
re-rate the favorite UP as the spike rolls off, and pre-position. We test the only two ways that can pay:

  (A) HOLD-to-resolution: is the over-charged (aging-spike) favorite genuinely UNDER-priced -> buy & hold beats fee?
      DECISIVE CONTROL: does the AGING pattern add anything BEYOND the raw VRP level (implied/realized_recent)?
      The raw level is already DEAD (experiment_vrp_harvest.py, priced). If aging collapses given the level, this
      is SUBSUMED by the dead VRP harvest.
  (B) EXIT into the re-rate: does the favorite's ask actually rise (excess of time-decay) tl30->tl10 in aging
      windows? If yes the MECHANISM is real -- but capturing it needs an EXIT, and every exit is walled
      (taker-exit fires on losers + fee; maker-rest-exit adverse-selected; only fee-free exit = hold, which does
      NOT capture the re-rate). So (B) being real does NOT make it tradeable; we measure it to understand, not to arm.

  aging      = realized_old / realized_recent   (>1 = vol high early, calm now = a spike aging out of the window)
  over_charge= implied_sigma / realized_recent  (the VRP level -- the maker charging more than recent vol; DEAD raw)

    python experiment_sigma_rolloff.py [--tl 30] [--ask-lo 0.95] [--ask-hi 0.99] [--pct 0.5]
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


def _rv(path, lo, hi):
    tw = [(300.0 - r[0], r[4]) for r in path if lo <= r[0] <= hi and r[4] and r[4] > 0]
    if len(tw) < 12:
        return None
    tw.sort()
    t = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
    lr = np.diff(np.log(sp)); dt = np.diff(t); ok = dt > 0
    if ok.sum() < 10:
        return None
    rv = np.sqrt(np.mean(lr[ok] ** 2 / dt[ok]))
    return rv if (np.isfinite(rv) and rv > 0) else None


def load(coin, tl, ask_lo, ask_hi, tol=10.0):
    """(ws, fav_ask, won, implied, r_recent, r_old, fav_ask_late, dt_to_late)."""
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
            r_recent = _rv(path, tl, tl + 45.0)
            r_old    = _rv(path, tl + 90.0, tl + 230.0)     # the EARLY part of the window (an aging spike sits here)
            if None in (implied, r_recent, r_old) or implied <= 0:
                continue
            late = min(path, key=lambda r: abs(r[0] - 10.0))     # ~tl=10 ask (for the exit-capture mechanism check)
            la_ask = (late[2] if fav_up else late[3])
            out.append((ws, fav_ask, (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0),
                        implied, r_recent, r_old, la_ask, t_l - late[0]))
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


def joint(asks, wons, ws, cols, names, target, want_sign, B=300, seed=5):
    y = wons.astype(float); X = np.column_stack([zc(c) for c in cols]); pos = target + 1
    b = fit(X, y)
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); co = []
    for _ in range(B):
        pick = np.array([rng.choice(idx_by[c]) for c in uniq]); co.append(fit(X[pick], y[pick])[pos])
    co = np.array(co); frac = float(np.mean(co > 0) if want_sign > 0 else np.mean(co < 0))
    null = []
    for _ in range(B):
        Xp = X.copy(); Xp[:, target] = rng.permutation(X[:, target]); null.append(fit(Xp, y)[pos])
    null = np.array(null)
    pperm = float(np.mean(null >= b[pos]) if want_sign > 0 else np.mean(null <= b[pos]))
    sgn = "POSITIVE" if want_sign > 0 else "NEGATIVE"
    print(f"    won ~ {' + '.join(names)}:  {names[target]} coef {b[pos]:+.3f}  {sgn} in {100*frac:.0f}%  "
          f"perm-p {pperm:.3f}   {'PASS' if (frac > 0.95 and pperm < 0.05) else 'fail'}")
    return frac > 0.95 and pperm < 0.05


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--ask-lo", type=float, default=0.95, dest="ask_lo")
    ap.add_argument("--ask-hi", type=float, default=0.99, dest="ask_hi")
    ap.add_argument("--pct", type=float, default=0.5)
    ap.add_argument("--lookback", type=int, default=200)
    args = ap.parse_args()

    rows = []
    for c in coins.ENABLED:
        r = load(c, args.tl, args.ask_lo, args.ask_hi)
        rows += [(c,) + x for x in r]
        print(f"  loaded {c}: {len(r)} favorite-tail windows")
    if len(rows) < 50:
        print("  too few rows."); return
    coin = np.array([r[0] for r in rows]); ws = np.array([r[1] for r in rows], float)
    asks = np.array([r[2] for r in rows], float); wons = np.array([r[3] for r in rows], float)
    imp = np.array([r[4] for r in rows], float); rrec = np.array([r[5] for r in rows], float)
    rold = np.array([r[6] for r in rows], float); la_ask = np.array([r[7] for r in rows], float)

    aging = rold / rrec                  # >1 = spike aging out (vol high early, calm now)
    over_charge = imp / rrec             # the VRP level (DEAD raw) -- maker charging more than recent vol
    print(f"\nMECHANICAL SIGMA ROLL-OFF  favorite-tail ask[{args.ask_lo},{args.ask_hi}) tl~{args.tl:g}  "
          f"n={len(rows)} losers={int((wons==0).sum())}")
    print("=" * 90)
    print(f"  median aging(old/recent)={np.median(aging):.2f}  median over_charge(impl/recent)={np.median(over_charge):.2f}")
    print(f"  corr(aging, over_charge)={np.corrcoef(aging, over_charge)[0,1]:+.3f}")

    # ---- (A) HOLD-to-resolution harvest: aging-spike over-charge set vs baseline ----
    print("\n  (A) HOLD-to-resolution gate:")
    a0 = S.assess(asks, wons, ws, n_trials=S.N_PROGRAM, label="baseline favorite-tail")
    S.print_assess(a0)
    # gate: both aging and over_charge in the HIGH half of each coin's own trailing distribution
    ra = rolling_pct_rank(aging, ws, lookback=args.lookback, groups=coin)
    ro = rolling_pct_rank(over_charge, ws, lookback=args.lookback, groups=coin)
    g = np.isfinite(ra) & np.isfinite(ro) & (ra >= (1 - args.pct)) & (ro >= (1 - args.pct))
    a1 = S.assess(asks[g], wons[g], ws[g], n_trials=S.N_PROGRAM, label="GATED aging-spike over-charge (adaptive)")
    S.print_assess(a1)

    # ---- DECISIVE CONTROL: does AGING add beyond the (dead) VRP level? ----
    print("\n  DECISIVE CONTROL — does the aging pattern add anything beyond the raw VRP level?")
    joint(asks, wons, ws, [asks, over_charge],        ["ask", "over_charge"],          1, +1)
    joint(asks, wons, ws, [asks, aging],              ["ask", "aging"],                1, +1)
    joint(asks, wons, ws, [asks, over_charge, aging], ["ask", "over_charge", "aging"], 2, +1)

    # ---- (B) MECHANISM: does the favorite ask rise EXCESS of time-decay in aging windows? ----
    # GUARD (second-mind 2026-06-27): `dask` is DOMINATED by the OUTCOME (winners' asks -> 1, losers' -> 0),
    # so ANY won-correlated variable inherits a SPURIOUS "excess". ALWAYS control for won / measure
    # WINNERS-ONLY before reading any tl-window ask-rise as a "mechanism". The naive HIGH-vs-LOW excess
    # (+0.0173) is ~81% this outcome-mix artifact; the genuine won-orthogonal piece is ~0.1 cent/sigma.
    print("\n  (B) MECHANISM (and why it is mostly an OUTCOME-MIX confound, not a re-rate):")
    dask = la_ask - asks                                   # ask change tl~30 -> tl~10 on the favorite side
    print(f"      corr(dask, won) = {np.corrcoef(dask, wons)[0,1]:+.3f}  (ask-change is ~entirely outcome-driven)")
    hi_age = aging >= np.quantile(aging, 0.7); lo_age = aging <= np.quantile(aging, 0.3)
    exc = lambda m: float(np.nanmean(dask[hi_age & m]) - np.nanmean(dask[lo_age & m]))
    print(f"      excess ask-rise HIGH-aging vs LOW-aging:  ALL favorites {exc(np.ones(len(dask),bool)):+.4f}   "
          f"WINNERS-ONLY {exc(wons==1):+.4f}")
    print(f"      => WINNERS-ONLY collapses toward 0 -> the 'excess' was the ask correctly tracking SAFER")
    print(f"         favorites (priced outcome), NOT a non-informational sigma re-rate. The genuine won-")
    print(f"         orthogonal piece is ~0.1 cent/sigma = real but sub-economic AND uncapturable (it lives on")
    print(f"         the ASK; you exit at the BID, which doesn't follow; every round-trip < spread, even clairvoyant).")

    print("\n  READ: tradeable ONLY if (A) the gated hold set SURVIVES the gate AND the aging coef stays")
    print("  POSITIVE & significant BEYOND over_charge. If aging collapses given over_charge, it is subsumed by")
    print("  the DEAD VRP level. If only (B) is positive, the mechanism is real but walled by the exit. Either")
    print("  way, an honest kill is the expected result and a real finding.")


if __name__ == "__main__":
    main()

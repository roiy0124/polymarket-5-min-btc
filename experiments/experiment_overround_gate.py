"""OVER-ROUND-GATED FAVORITE-TAIL — the makers' revealed-fear gate (NEW candidate, 2026-06-25).

Story (the factor): the favorite-tail buys a near-certain favorite (ask>=0.95) and dies only to its
rare FLIPS. When a 0.96 favorite is about to flip, the market-makers — who see the order flow — turn
DEFENSIVE and WIDEN the pair, so the over-round `up_ask + down_ask - 1` rises. The over-round is the
makers' revealed confidence, and it is a DIFFERENT object from the favorite's own price (the price is
the level; the over-round is the spread/liquidity). So gating favorite-tail to TIGHT-over-round
(calm makers) windows cuts the flip-losers on a FORWARD signal the favorite ask hasn't fully priced.

Evidence that it is NOT just "buy higher-ask favorites" (ask-controlled, in-sample):
  ask 0.95-0.97: tight over-round win 97.2% (EV +0.014) vs wide 93.3% (EV -0.026)  [loss 2.8% vs 6.7%]
  ask 0.97-0.99: tight        win 98.0% (EV +0.002) vs wide 94.8% (EV -0.032)  [loss 2.0% vs 5.2%]
  ask 0.99-1.00: NO effect (already certain -> over-round adds nothing)
The loss-rate halving holds WITHIN ask buckets and LOCO-robust across all 6 coins. The edge lives in
the MODERATE-favorite band (0.95-0.99) where the favorite is genuinely not a sure thing.

STATUS: breakeven-tier CANDIDATE, pre-registerable. Pooled it flips favorite-tail from -0.0026 to
positive, but it is still LOSS-LIGHT (gated losers < 30) so the deflated gate reads INSUFFICIENT, not
SURVIVES. Needs OOS / more losers before it can graduate. Do NOT re-tune the threshold on this data.

    python experiment_overround_gate.py [--tl 30] [--ask-lo 0.95] [--ask-hi 0.99] [--or-thresh 0.012]
"""
import argparse
import sqlite3

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from analysis import stats as S
from analysis.adaptive import rolling_pct_rank, stability_by_bin, rolling_wilson_monitor


def joint_control(asks, wons, orr, ws, B=300, seed=5):
    """THE decisive anti-confound test (the one the dead B-filter failed): regress won on
    [fav_ask, over_round] JOINTLY. If over_round keeps a significant NEGATIVE coefficient after
    fav_ask is in the model, the gate is a REAL signal independent of the favorite's own price (tight
    over_round -> winning); if its coefficient collapses, it just re-derived the priced ask. Reported
    with cluster-robust sign stability (1 random row per window per refit) + a permutation p."""
    try:
        from scipy import stats as _ss
    except Exception:
        return
    a = (asks - asks.mean()) / asks.std(); o = (orr - orr.mean()) / orr.std(); y = wons.astype(float)
    def fit(X, yy):
        # ridge-stabilised logistic via IRLS (no sklearn dep)
        Xb = np.column_stack([np.ones(len(yy)), X]); beta = np.zeros(Xb.shape[1])
        for _ in range(50):
            p = 1 / (1 + np.exp(-Xb @ beta)); Wd = np.clip(p * (1 - p), 1e-6, None)
            g = Xb.T @ (yy - p) - 1e-3 * beta; H = Xb.T @ (Xb * Wd[:, None]) + 1e-3 * np.eye(Xb.shape[1])
            step = np.linalg.solve(H, g); beta += step
            if np.abs(step).max() < 1e-8:
                break
        return beta
    beta = fit(np.column_stack([a, o]), y)
    # cluster-robust: 1 random row per window, refit, track over_round coef sign
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); coefs = []
    for _ in range(B):
        pick = [rng.choice(idx_by[c]) for c in uniq]
        coefs.append(fit(np.column_stack([a[pick], o[pick]]), y[pick])[2])
    coefs = np.array(coefs); neg = float(np.mean(coefs < 0))
    # permutation p on the over_round coef (shuffle over_round)
    null = []
    for _ in range(B):
        op = rng.permutation(o); null.append(fit(np.column_stack([a, op]), y)[2])
    pperm = float(np.mean(np.array(null) <= beta[2]))
    print(f"\n  JOINT CONTROL  won ~ fav_ask + over_round (z-scored, the anti-confound test):")
    print(f"      fav_ask coef {beta[1]:+.3f}   over_round coef {beta[2]:+.3f}  "
          f"(want over_round NEGATIVE = tight->winning, independent of price)")
    print(f"      cluster-robust: over_round coef NEGATIVE in {100*neg:.0f}% of refits   permutation p={pperm:.3f}")
    print(f"      => {'SIGNAL real & ask-independent' if (neg>0.95 and pperm<0.05) else 'collapses under control (priced)'}")


def load(coin, tl, ask_lo, ask_hi, tol=12.0):
    """Per resolved window at time_left~tl: (ws, fav_ask, won, over_round) for favorites in [ask_lo,ask_hi)."""
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
            if abs(t_l - tl) > tol:
                continue
            fav_up = px >= strike
            fav_ask = ua if fav_up else da
            if fav_ask < ask_lo or fav_ask >= ask_hi:
                continue
            won = (1 if outcome == "Up" else 0) if fav_up else (1 if outcome == "Down" else 0)
            out.append((ws, fav_ask, won, ua + da - 1.0))
        conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--ask-lo", type=float, default=0.95, dest="ask_lo")
    ap.add_argument("--ask-hi", type=float, default=0.99, dest="ask_hi",
                    help="upper ask bound — the gate adds nothing at 0.99+ (already certain), so cap there")
    ap.add_argument("--or-thresh", type=float, default=0.012, dest="or_thresh",
                    help="FIXED tight over-round threshold (keep up_ask+down_ask-1 <= this)")
    ap.add_argument("--adaptive", action="store_true",
                    help="SELF-NORMALIZING gate: keep windows whose over_round is in the tight half of its "
                         "own trailing distribution (rolling percentile <= --pct), instead of the fixed const. "
                         "Tracks regime drift with NO new fitted param.")
    ap.add_argument("--pct", type=float, default=0.5, help="adaptive: keep rolling-percentile-rank <= this")
    ap.add_argument("--lookback", type=int, default=200, help="adaptive: trailing windows for the percentile")
    args = ap.parse_args()

    allrows = []
    for c in coins.ENABLED:
        rows = load(c, args.tl, args.ask_lo, args.ask_hi)
        allrows += [(c,) + r for r in rows]
        print(f"  loaded {c}: {len(rows)} favorite-tail windows in ask[{args.ask_lo},{args.ask_hi})")
    coin = np.array([r[0] for r in allrows]); asks = np.array([r[2] for r in allrows])
    wons = np.array([r[3] for r in allrows]); ws = np.array([r[1] for r in allrows])
    orr = np.array([r[4] for r in allrows])
    print(f"\nOVER-ROUND-GATED FAVORITE-TAIL  tl~{args.tl:g}  ask[{args.ask_lo},{args.ask_hi})  "
          f"TIGHT over_round <= {args.or_thresh:g}")
    print("=" * 84)
    print(f"  over_round on WINNERS {orr[wons==1].mean():+.4f}  vs LOSERS {orr[wons==0].mean():+.4f}  "
          f"(losers wider = makers' revealed fear)")
    a = S.assess(asks, wons, ws, n_trials=20, label="baseline favorite-tail (ask<0.99)")
    S.print_assess(a)

    g_fix = orr <= args.or_thresh
    a = S.assess(asks[g_fix], wons[g_fix], ws[g_fix], n_trials=20, label="GATED fixed over-round<=%.3f" % args.or_thresh)
    S.print_assess(a)

    # SELF-NORMALIZING gate (PRIMARY): over_round in the tight half of its OWN trailing distribution,
    # normalized PER COIN (over_round scale is ~5x larger on BNB than BTC — pooling would gate on the coin,
    # not the regime). No fitted const; tracks drift with zero new DOF.
    rank = rolling_pct_rank(orr, ws, lookback=args.lookback, groups=coin)
    g_adp = np.isfinite(rank) & (rank <= args.pct)
    print(f"\n  --- ADAPTIVE (self-normalizing, PER-COIN) gate: over_round rolling-pct-rank <= {args.pct:g} "
          f"(lookback {args.lookback}) — the recommended primary ---")
    a_adp = S.assess(asks[g_adp], wons[g_adp], ws[g_adp], n_trials=20,
                     label="GATED adaptive per-coin (rolling percentile)")
    S.print_assess(a_adp)
    joint_control(asks, wons, orr, ws)

    # DRIFT MONITOR: rolling Wilson-LB(win) vs breakeven (the by-thirds split is too underpowered to be a
    # monitor — blind below ~8pp). This slides a window of gated bets and flags when the edge decays below
    # the fee wall. ALSO shown: the by-thirds smoke-alarm for reference.
    gate = g_adp if args.adaptive else g_fix
    mon = rolling_wilson_monitor(ws, wons, asks, gate, window=150)
    print(f"\n  DRIFT MONITOR (rolling Wilson-LB(win) - breakeven, window=150 gated bets):")
    if mon:
        print(f"      latest LB-breakeven = {mon[0]:+.4f}   fraction of windows below 0 = {mon[1]:.2f}   "
              f"({mon[2]} steps)")
        print(f"      (< 0 sustained = edge decayed below the fee wall -> stop; > 0 = still clearing cost)")
    else:
        print(f"      (not enough gated bets yet for a 150-window monitor — needs more data)")
    print(f"  by-thirds smoke-alarm (underpowered, catastrophe-only):")
    for i, b in enumerate(stability_by_bin(ws, wons, gate, bins=3)):
        print(f"      third {i+1}: n={b['n']:>4} loss={b['loss']:>3} win={100*b['win']:.1f}%")
    print("\n  READ: per-coin ADAPTIVE is the recommended primary (drift-robust by construction, no fitted")
    print("  param). Still loss-light (<30 gated losers) -> INSUFFICIENT not SURVIVES; pre-registered. The")
    print("  lookback is the only knob — keep it fixed, do NOT tune. Monitor edge with the rolling Wilson-LB.")


if __name__ == "__main__":
    main()

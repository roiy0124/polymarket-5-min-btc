"""Stage-1 signal-existence test on DEEP FREE spot history (no Polymarket data).

Question this answers (and the only one it CAN answer): does a leader coin's recent
short-horizon move predict an alt's next-5-min UP/DOWN *outcome* (alt final >= alt
strike), with a STABLE sign across regimes -- measured far deeper than our ~5-day
Polymarket DB. It deliberately does NOT touch the token price / spread / fee; those
live only in the live collector (that is Stage 2). See memory
`spot-history-two-stage-validation`.

Data: free Binance public 1s klines from data.binance.vision (no login/rate-limit).
We reconstruct the exact 5-min window grid (t0 = floor(ts/300)*300, same slug clock
the market uses), the strike (price at t0), the final (price at t0+300), a strictly
CAUSAL predictor (leader return over [t_d-H, t_d], decided at t_d = t0+d), and the
binary outcome. Then we run a ROLLING-window analysis so we can SEE whether the
relationship is stable, regime-fragile, or already dead -- and estimate its
relevance half-life, instead of pooling years into one misleading number.

Predictors reported (signed; +r = co-move/positive-lead, -r = reversal/seesaw):
  leader : leader's trailing-H return                  (idea B: cross-asset lead)
  gap    : leader return - alt return                  (idea B: BTC-confirmation gap)
  altown : alt's OWN trailing-H return                 (reversion / momentum of self)

Outcome label robustness (v1): the spot outcome is a PROXY for Chainlink settlement.
We report the headline label plus boundary-perturbation + near-boundary-exclusion
variants. A true second-venue (Pyth/Coinbase) cross-check is the v2 hardening.

Usage:
  python -m analysis.spot_leadlag --leader btc --alt sol --start 2025-07 --decision 30
"""
from __future__ import annotations
import argparse, csv, os, sys, math
from datetime import datetime, timezone
import numpy as np
from analysis import spot_data
from analysis.spot_data import SYMBOL

WIN = 300            # 5-min market window
OUT = os.path.join(spot_data.REPO, "spot_leadlag")   # results live with the project
os.makedirs(OUT, exist_ok=True)


# ------------------------------------------------------------------- price@time
class PriceAt:
    """Backward-fill lookup: price at the most recent 1s bar with start <= query,
    matching the live collector's bisect_right-1 semantics. Returns NaN if the
    nearest prior bar is staler than `max_stale` seconds (data gap)."""
    def __init__(self, secs, price, max_stale=90):
        self.s = secs; self.p = price; self.max_stale = max_stale

    def __call__(self, q):
        q = np.asarray(q, dtype=np.int64)
        idx = np.searchsorted(self.s, q, side="right") - 1
        bad = idx < 0
        idx_clip = np.clip(idx, 0, len(self.s) - 1)
        out = self.p[idx_clip].astype(np.float64)
        stale = (q - self.s[idx_clip]) > self.max_stale
        out[bad | stale] = np.nan
        return out


# ------------------------------------------------------------------- build rows
def build_rows(leader, alt, start, decision, horizon, leader_series=None):
    if leader_series is None:
        print(f"loading {SYMBOL[leader]} ...", file=sys.stderr)
        dl = spot_data.load_range(SYMBOL[leader], start)
        leader_series = (dl["sec"], dl["close"])
    ls, lp = leader_series
    print(f"loading {SYMBOL[alt]} ...", file=sys.stderr)
    da = spot_data.load_range(SYMBOL[alt], start)
    as_, ap = da["sec"], da["close"]
    L = PriceAt(ls, lp); A = PriceAt(as_, ap)

    lo = max(ls[0], as_[0]); hi = min(ls[-1], as_[-1])
    t0 = (int(lo) // WIN + 1) * WIN          # first full window start
    last = (int(hi) // WIN) * WIN - WIN      # last window whose +300 close exists
    starts = np.arange(t0, last + 1, WIN, dtype=np.int64)

    td = starts + decision                    # decision instant
    # causal predictor legs (only data <= td used)
    l_now = L(td); l_pre = L(td - horizon)
    a_now = A(td); a_pre = A(td - horizon)
    # strike / final (alt) -- and a leader copy for reference
    a_strike = A(starts); a_final = A(starts + WIN)
    # boundary-perturbation final: mean of last 3 one-sec prices before close
    a_final_p = np.nanmean(np.vstack([A(starts + WIN - k) for k in (0, 1, 2)]), axis=0)

    ret_lead = l_now / l_pre - 1.0
    ret_alt = a_now / a_pre - 1.0
    gap = ret_lead - ret_alt

    good = np.isfinite(ret_lead) & np.isfinite(ret_alt) & np.isfinite(a_strike) \
        & np.isfinite(a_final) & np.isfinite(a_final_p)
    y = (a_final >= a_strike).astype(np.float64)
    y_p = (a_final_p >= a_strike).astype(np.float64)
    margin = (a_final - a_strike) / a_strike  # for near-boundary exclusion

    cols = dict(t0=starts, ret_lead=ret_lead, ret_alt=ret_alt, gap=gap,
                y=y, y_p=y_p, margin=margin, good=good)
    return {k: v[good] for k, v in cols.items()}


# --------------------------------------------------------------------- stats
def signed_r(x, y):
    """Pearson r between predictor x and the signed outcome (2y-1). +ve => x>0
    predicts UP (co-move); -ve => reversal."""
    s = 2.0 * y - 1.0
    if len(x) < 8 or np.std(x) == 0 or np.std(s) == 0:
        return np.nan
    return float(np.corrcoef(x, s)[0, 1])


def hit_edge(x, y):
    """Directional hit-rate above 0.5 when you bet the side x points to."""
    m = x != 0
    if m.sum() < 8:
        return np.nan
    call = np.sign(x[m])
    truth = np.sign(2.0 * y[m] - 1.0)
    return float(np.mean(call == truth) - 0.5)


def fisher_ci(r, n, z=1.96):
    if not np.isfinite(r) or n < 5 or abs(r) >= 1:
        return (np.nan, np.nan)
    zr = np.arctanh(r); se = 1.0 / math.sqrt(n - 3)
    return (math.tanh(zr - z * se), math.tanh(zr + z * se))


def boot_ci(x, y, fn, n_boot=2000, seed=0):
    rng = np.random.default_rng(seed)
    n = len(x); stats = np.empty(n_boot)
    for b in range(n_boot):
        i = rng.integers(0, n, n)
        stats[b] = fn(x[i], y[i])
    stats = stats[np.isfinite(stats)]
    if len(stats) < 50:
        return (np.nan, np.nan)
    return (float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5)))


def ar1_halflife(series):
    """Half-life (in buckets) of the rolling-coefficient series via AR(1)."""
    s = np.asarray([v for v in series if np.isfinite(v)], dtype=np.float64)
    if len(s) < 6:
        return np.nan, np.nan
    a, b = s[:-1], s[1:]
    if np.std(a) == 0:
        return np.nan, np.nan
    beta = np.polyfit(a, b, 1)[0]
    if not (0 < beta < 1):
        return beta, np.inf if beta >= 1 else 0.0
    return beta, -math.log(2) / math.log(beta)


def rolling(rows, pred_key, roll_days, step_days, label="y"):
    t0 = rows["t0"]; x = rows[pred_key]; y = rows[label]
    rw = roll_days * 86400; st = step_days * 86400
    lo, hi = int(t0.min()), int(t0.max())
    centers, rs, los, his, ns, edges = [], [], [], [], [], []
    start = lo
    while start + rw <= hi + st:
        a, b = start, start + rw
        m = (t0 >= a) & (t0 < b)
        n = int(m.sum())
        if n >= 30:
            r = signed_r(x[m], y[m]); cl, ch = fisher_ci(r, n)
            centers.append((a + b) // 2); rs.append(r); los.append(cl); his.append(ch)
            ns.append(n); edges.append(hit_edge(x[m], y[m]))
        start += st
    return dict(center=np.array(centers), r=np.array(rs), lo=np.array(los),
                hi=np.array(his), n=np.array(ns), edge=np.array(edges))


def dt(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------- report
def analyze(leader, alt, start, decision, horizon, roll_days, step_days, leader_series=None):
    rows = build_rows(leader, alt, start, decision, horizon, leader_series=leader_series)
    n = len(rows["t0"])
    span = f"{dt(rows['t0'].min())} -> {dt(rows['t0'].max())}"
    base_rate = float(rows["y"].mean())
    print("\n" + "=" * 78)
    print(f"STAGE-1 SPOT LEAD-LAG  leader={leader.upper()}  alt={alt.upper()}  "
          f"decision=t0+{decision}s  horizon={horizon}s")
    print(f"windows={n:,}  span={span}  alt UP base-rate={base_rate:.3f}")
    print("=" * 78)

    summary = {}
    for key in ("ret_lead", "gap", "ret_alt"):
        r = signed_r(rows[key], rows["y"])
        bcl, bch = boot_ci(rows[key], rows["y"], signed_r)
        edge = hit_edge(rows[key], rows["y"])
        roll = rolling(rows, key, roll_days, step_days)
        sign_full = np.sign(r) if np.isfinite(r) else 0
        valid = roll["r"][np.isfinite(roll["r"])]
        stab = float(np.mean(np.sign(valid) == sign_full)) if len(valid) else np.nan
        beta, hl = ar1_halflife(roll["r"])
        # recent vs old halves of the rolling series
        half = len(valid) // 2
        old_m = float(np.mean(valid[:half])) if half else np.nan
        new_m = float(np.mean(valid[half:])) if half else np.nan
        summary[key] = dict(r=r, ci=(bcl, bch), edge=edge, stab=stab, hl=hl,
                            old=old_m, new=new_m, roll=roll, beta=beta)
        nm = {"ret_lead": "LEADER move", "gap": "GAP (lead-alt)", "ret_alt": "ALT-own move"}[key]
        print(f"\n[{nm}]  full r={r:+.4f}  95%CI[{bcl:+.4f},{bch:+.4f}]  "
              f"hit-edge={edge:+.4f}")
        print(f"    rolling buckets={len(valid)}  sign-stability={stab:.0%}  "
              f"AR1 beta={beta:+.2f}  half-life={hl:.1f} buckets  "
              f"(old half mean r={old_m:+.4f} -> new half {new_m:+.4f})")

    # label robustness on the headline predictor (leader)
    print("\n[LABEL ROBUSTNESS on LEADER predictor]")
    r0 = signed_r(rows["ret_lead"], rows["y"])
    rp = signed_r(rows["ret_lead"], rows["y_p"])
    near = np.abs(rows["margin"]) < 0.0003   # ~3bp boundary band
    rfar = signed_r(rows["ret_lead"][~near], rows["y"][~near])
    print(f"    boundary-close label : r={r0:+.4f}")
    print(f"    last-3s-mean   label : r={rp:+.4f}   (sign {'STABLE' if np.sign(r0)==np.sign(rp) else 'FLIPS'})")
    print(f"    excl near-boundary   : r={rfar:+.4f}  ({int(near.sum())} of {len(near)} "
          f"windows within ~3bp dropped)  (sign {'STABLE' if np.sign(r0)==np.sign(rfar) else 'FLIPS'})")
    print("    NOTE: true Binance-vs-Pyth/Coinbase cross-venue check is the v2 hardening.")

    _plot(leader, alt, decision, horizon, summary, span, n, start)
    _csv(leader, alt, summary, decision, horizon, start)
    print("=" * 78)
    return summary


def _plot(leader, alt, decision, horizon, summary, span, n, start):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig, ax = plt.subplots(figsize=(12, 6), dpi=130)
    colors = {"ret_lead": "#1f77b4", "gap": "#2ca02c", "ret_alt": "#d62728"}
    names = {"ret_lead": "leader move", "gap": "gap (lead-alt)", "ret_alt": "alt-own move"}
    for key in ("ret_lead", "gap", "ret_alt"):
        roll = summary[key]["roll"]
        if not len(roll["center"]):
            continue
        x = [datetime.fromtimestamp(int(c), tz=timezone.utc) for c in roll["center"]]
        ax.plot(x, roll["r"], "-o", ms=3, lw=1.4, color=colors[key],
                label=f"{names[key]} (full r={summary[key]['r']:+.3f})")
        if key == "ret_lead":
            ax.fill_between(x, roll["lo"], roll["hi"], color=colors[key], alpha=0.15)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(f"Stage-1 rolling signed-r: does {leader.upper()} {horizon}s move predict "
                 f"{alt.upper()} 5-min UP?  (decision t0+{decision}s, n={n:,}, {span})",
                 fontsize=11)
    ax.set_ylabel("signed r  ( +co-move / -reversal )")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%d"))
    ax.legend(fontsize=9, loc="best"); ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    path = os.path.join(OUT, f"rolling_{leader}_{alt}_d{decision}_h{horizon}_{start}.png")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    print(f"\nplot -> {path}")


def _csv(leader, alt, summary, decision, horizon, start):
    path = os.path.join(OUT, f"rolling_{leader}_{alt}_d{decision}_h{horizon}_{start}.csv")
    roll = summary["ret_lead"]["roll"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bucket_center_utc", "n", "r_leader", "lo", "hi", "hit_edge_leader",
                    "r_gap", "r_altown"])
        for i in range(len(roll["center"])):
            w.writerow([dt(roll["center"][i]), roll["n"][i],
                        f"{roll['r'][i]:.5f}", f"{roll['lo'][i]:.5f}",
                        f"{roll['hi'][i]:.5f}", f"{roll['edge'][i]:.5f}",
                        f"{summary['gap']['roll']['r'][i]:.5f}",
                        f"{summary['ret_alt']['roll']['r'][i]:.5f}"])
    print(f"csv  -> {path}")


def analyze_many(leader, alts, start, decision, horizon, roll_days, step_days):
    """Run every alt against one leader (loaded once), print a cross-coin leaderboard,
    and emit a gathered plot of each predictor's full-sample signed-r per alt."""
    print(f"loading {SYMBOL[leader]} (leader, once) ...", file=sys.stderr)
    dl = spot_data.load_range(SYMBOL[leader], start)
    lser = (dl["sec"], dl["close"])
    results = {}
    for alt in alts:
        if alt == leader:
            continue
        try:
            results[alt] = analyze(leader, alt, start, decision, horizon,
                                   roll_days, step_days, leader_series=lser)
        except SystemExit as e:
            print(f"  [{alt}] skipped: {e}", file=sys.stderr)
    if not results:
        return
    print("\n" + "#" * 78)
    print(f"CROSS-COIN LEADERBOARD  leader={leader.upper()}  decision=t0+{decision}s  "
          f"horizon={horizon}s  start={start}")
    print(f"{'alt':5} {'r_leader':>10} {'95% CI':>20} {'stab':>6} {'hl':>6} "
          f"{'r_gap':>9} {'r_altown':>9}")
    for alt, s in results.items():
        L = s["ret_lead"]; ci = L["ci"]
        print(f"{alt.upper():5} {L['r']:>+10.4f} "
              f"[{ci[0]:+.3f},{ci[1]:+.3f}]   {L['stab']:>5.0%} {L['hl']:>6.1f} "
              f"{s['gap']['r']:>+9.4f} {s['ret_alt']['r']:>+9.4f}")
    print("#" * 78)
    _plot_gathered(leader, results, decision, horizon, start)
    return results


def _plot_gathered(leader, results, decision, horizon, start):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    alts = list(results.keys())
    x = np.arange(len(alts))
    fig, ax = plt.subplots(figsize=(max(8, 1.6 * len(alts)), 5), dpi=130)
    series = [("ret_lead", "leader move", "#1f77b4"),
              ("gap", "gap (lead-alt)", "#2ca02c"),
              ("ret_alt", "alt-own move", "#d62728")]
    w = 0.26
    for i, (key, nm, col) in enumerate(series):
        vals = [results[a][key]["r"] for a in alts]
        if key == "ret_lead":
            lo = [results[a][key]["r"] - results[a][key]["ci"][0] for a in alts]
            hi = [results[a][key]["ci"][1] - results[a][key]["r"] for a in alts]
            ax.bar(x + (i - 1) * w, vals, w, color=col, label=nm,
                   yerr=[lo, hi], capsize=3)
        else:
            ax.bar(x + (i - 1) * w, vals, w, color=col, label=nm)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels([a.upper() for a in alts])
    ax.set_ylabel("full-sample signed r  ( +co-move / -reversal )")
    ax.set_title(f"Stage-1 cross-coin: {leader.upper()} {horizon}s move (and gap / alt-own) "
                 f"vs each alt's 5-min UP  (decision t0+{decision}s, start {start})", fontsize=11)
    ax.legend(fontsize=9); ax.grid(axis="y", alpha=0.25)
    path = os.path.join(OUT, f"gathered_{leader}_d{decision}_h{horizon}_{start}.png")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    print(f"gathered plot -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leader", default="btc")
    ap.add_argument("--alt", default="sol", help="single alt; ignored if --alts given")
    ap.add_argument("--alts", default=None,
                    help="'all' or comma list e.g. eth,sol,xrp -> cross-coin leaderboard")
    ap.add_argument("--start", default="2025-07", help="first month YYYY-MM")
    ap.add_argument("--decision", type=int, default=30, help="decision instant = t0 + this many s")
    ap.add_argument("--horizon", type=int, default=15, help="predictor lookback seconds")
    ap.add_argument("--roll-days", type=int, default=30)
    ap.add_argument("--step-days", type=int, default=7)
    a = ap.parse_args()
    if a.alts:
        alts = [c for c in spot_data.COINS if c != a.leader] if a.alts == "all" \
            else [c.strip() for c in a.alts.split(",")]
        analyze_many(a.leader, alts, a.start, a.decision, a.horizon, a.roll_days, a.step_days)
    else:
        analyze(a.leader, a.alt, a.start, a.decision, a.horizon, a.roll_days, a.step_days)


if __name__ == "__main__":
    main()

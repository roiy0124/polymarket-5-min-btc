"""CONDITIONAL-SKEW MODEL-FORM RESIDUAL — the one TESTABLE candidate from the Phase-1 field survey
(Field A option-pricing ⊗ Field B volatility; see RESEARCH-EXTERNAL.md "PHASE 1" + memory
field-research-program / hierarchy-expansion-skew-candidate).

THE FACTOR (trader-behavior story).  The maker quotes a DRIFTLESS, SYMMETRIC Gaussian digital:
    up_mid ≈ Φ( ln(spot/strike) / (σ·√t) ).
Option theory (Breeden–Litzenberger; Wystup "Slope Matters") says the TRUE digital-call price is
    D = Φ(d2)  −  vega · (dσ/dK),
i.e. the symmetric Φ OMITS a skew term. A single σ is a 2nd-moment object and CANNOT encode the 3rd
moment, so — unlike σ-level, which the maker re-fits and which is therefore self-priced — a conditional
SKEW error could survive in the quote. Sign rule: NEGATIVE return-skew (downside-heavy regime, dσ/dK<0)
⇒ −vega·dσ/dK > 0 ⇒ the true Up-digital is worth MORE than the symmetric quote ⇒ the maker UNDER-prices
Up. POSITIVE skew ⇒ Up over-priced. Rough-vol (Gatheral, H≈0.1) says the skew term ∝ τ^(H−1/2) ≈ τ^−0.4
is MAXIMAL at our 5-min horizon — the strongest argument the seam is non-trivial.

THE PROXY (strictly causal, native, no look-ahead).  For each resolved window the realized 5-min log
return is r = ln(final_binance / strike_binance) — literally the variable the digital bets on (Up iff
r≥0). The skew regime for window w = the SAMPLE SKEWNESS of the trailing N realized 5-min returns of the
SAME coin that closed STRICTLY BEFORE w opened. Per coin. No external feed; covers the exact window range.

THE TEST (the project rigor stack).
  1. JOINT CONTROL (falsification, the test that killed the b-filter / validated over-round): logistic
     won_up ~ up_mid + trend + skew. If the skew coef collapses given the mid (+ the priced trend), the
     maker already prices it ⇒ DEAD. We WANT a stable, ask-independent NEGATIVE skew coef (more-negative
     skew ⇒ more likely Up beyond the quote).
  2. DOSE-RESPONSE: per-coin causal skew terciles ⇒ mean residual (won_up − up_mid). Theory ⇒ monotone
     DECREASING (neg-skew tercile residual>0 = Up underpriced; pos-skew tercile residual<0).
  3. NET-EV GATE (the only verdict that counts): pre-committed directional trade — buy Up (taker, at
     up_ask) in the most-NEGATIVE-skew per-coin tercile, buy Down in the most-POSITIVE — routed through
     analysis.stats.assess (fee-aware net-EV, window-clustered, deflated, n_loss≥30). Restricted to a
     moneyness band where the digital's vega (hence the skew sensitivity) is non-trivial.

PRE-COMMITTED KILL (any one ⇒ DEAD, archive to dead_ends/): (a) skew coef not stably NEGATIVE under the
joint control (sign in <95% of cluster refits, or permutation p≥0.05) = priced; (b) no monotone
dose-response across skew terciles; (c) the net-EV gate FAILS / is fee-capped (deflated p≥0.05 or
cluster-CI includes 0) with n_loss≥30; (d) the sign only "works" by flipping it in-sample, or is driven
by one coin (LOCO). The SIGN is pre-committed from option theory — we do NOT flip-and-retest (the b-filter
trap). LOW prior going in: σ-padding absorbs symmetric tails; the fee 0.07·(1−p) peaks ~1.75%/share at the
p≈0.5 ATM zone where vega (skew sensitivity) is largest; and crypto's INVERSE leverage effect makes the
realized→implied skew-sign mapping regime-unstable (the make-or-break unknown).

    python experiment_skew_residual.py            # moment skew (pre-committed primary)
    python experiment_skew_residual.py --robust   # Bowley quantile skew (secondary cross-check)

Constants below are LOCKED (pre-registered). Do NOT tune them on this data.

VERDICT (2026-06-28) — DEAD (second-mind reviewed; archived to dead_ends/). The maker PRICES the skew.
  - MOMENT skew (primary): joint-control skew coef +0.002 (negative in 20% of refits, perm p=0.52) =
    collapses given the mid; corr(skew,residual) = -0.001. Net-EV gate FAILS (n=861, n_loss=412, win
    52.1% vs 54.4% breakeven, mean -0.046, cluster-CI[-0.117,+0.025], deflated p=1.0).
  - ROBUST (Bowley) skew: a FAINT theory-signed joint-control whiff (coef -0.156, perm p=0.003) that is
    BTC-concentrated + coin-INCOHERENT (sol/xrp sign-reversed, LOCO halves it, dies under multiplicity)
    and STILL fee-capped (win 50.5% vs 53.9% breakeven, net-EV -0.067, CI incl 0). Dose-response
    non-monotone under both. Second-mind: 0/40 deflated grid cells survive; a sharper intraday-spot skew
    has the WRONG sign (the crypto inverse-leverage caveat is real). No look-ahead bug; sign-flip is WORSE
    (no-signal, not sign-error); ATM maker route is the already-walled -0.365 toxic zone.
  CONCLUSION: the symmetric-Φ model-form/skew residual is the absorbable, fee-capped half — Grossman-
  Stiglitz "residual sized to the fee." This was the ONE testable lead of the field-research program; with
  it dead, the only on-market open thread is Thread B (settlement basis, data-gated).
"""
import argparse
import sqlite3
import sys

import numpy as np

try:                                   # Windows consoles default to a legacy codepage; force UTF-8 out
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import coins
from analysis import stats as S
from analysis.adaptive import rolling_pct_rank, stability_by_bin, rolling_wilson_monitor

# ---- LOCKED pre-registered constants ----
N_TRAIL = 288        # trailing realized 5-min returns for the skew proxy (~24h). LOCKED.
MIN_TRAIL = 120      # need at least this many prior returns to estimate skew (else drop the window)
TL = 30.0            # decision time_left (project-locked clock constant)
TOL = 12.0           # snapshot time_left tolerance
M_LO, M_HI = 0.20, 0.80   # moneyness band (up_mid) where digital vega is non-trivial. LOCKED.


def sample_skew(x):
    """Fisher-Pearson moment skewness of a 1-D array (the literal 3rd standardized moment = the object
    the −vega·dσ/dK correction tracks). NaN if too few / zero-variance."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < MIN_TRAIL:
        return np.nan
    s = x.std()
    if s == 0:
        return np.nan
    return float(np.mean(((x - x.mean()) / s) ** 3))


def robust_skew(x):
    """Bowley/quantile skew (Q90+Q10−2·Q50)/(Q90−Q10) — outlier-robust cross-check (moment skew on
    fat-tailed 5-min returns is single-jump-dominated). Secondary diagnostic only."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < MIN_TRAIL:
        return np.nan
    q10, q50, q90 = np.percentile(x, [10, 50, 90])
    if q90 == q10:
        return np.nan
    return float((q90 + q10 - 2 * q50) / (q90 - q10))


def joint_control(mid, trend, skew, wons, ws, B=300, seed=5):
    """won_up ~ up_mid + trend + skew (z-scored), ridge-IRLS logistic. Tracks the SKEW coef (index 3).
    Want it stably NEGATIVE after mid+trend are in the model = a real, ask-independent skew signal."""
    def z(v):
        v = np.asarray(v, float); sd = v.std()
        return (v - v.mean()) / (sd if sd else 1.0)
    a, t, k = z(mid), z(trend), z(skew); y = wons.astype(float)

    def fit(X, yy):
        Xb = np.column_stack([np.ones(len(yy)), X]); beta = np.zeros(Xb.shape[1])
        for _ in range(60):
            p = 1 / (1 + np.exp(-Xb @ beta)); Wd = np.clip(p * (1 - p), 1e-6, None)
            g = Xb.T @ (yy - p) - 1e-3 * beta
            H = Xb.T @ (Xb * Wd[:, None]) + 1e-3 * np.eye(Xb.shape[1])
            step = np.linalg.solve(H, g); beta += step
            if np.abs(step).max() < 1e-8:
                break
        return beta
    beta = fit(np.column_stack([a, t, k]), y)        # [const, mid, trend, skew]
    uniq = np.unique(ws); idx_by = {c: np.where(ws == c)[0] for c in uniq}
    rng = np.random.default_rng(seed); coefs = []
    for _ in range(B):
        pick = [rng.choice(idx_by[c]) for c in uniq]
        coefs.append(fit(np.column_stack([a[pick], t[pick], k[pick]]), y[pick])[3])
    coefs = np.array(coefs); neg = float(np.mean(coefs < 0))
    null = []
    for _ in range(B):
        kp = rng.permutation(k); null.append(fit(np.column_stack([a, t, kp]), y)[3])
    null = np.array(null)
    pperm = float(np.mean(null <= beta[3]))          # one-sided: skew coef MORE negative than chance
    print("\n  JOINT CONTROL  won_up ~ up_mid + trend + skew  (z-scored; the anti-confound test):")
    print(f"      up_mid coef {beta[1]:+.3f}   trend coef {beta[2]:+.3f}   SKEW coef {beta[3]:+.3f}  "
          f"(want SKEW negative & ask-independent)")
    print(f"      cluster-robust: skew coef NEGATIVE in {100*neg:.0f}% of refits   permutation p={pperm:.3f}")
    real = (neg > 0.95 or neg < 0.05) and pperm < 0.05
    print(f"      => {'SKEW signal real & ask-independent' if real else 'collapses under control (maker prices the skew)'}")
    return real


def load(coin):
    """Per resolved window at time_left~TL: (ws, up_ask, down_ask, up_mid, won_up, trend, r5) for the coin,
    deduped across live+archive DBs. r5 = ln(final/strike) = the realized 5-min return (builds the proxy)."""
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = conn.execute(
                "SELECT window_start, strike_binance, final_binance, resolved_outcome FROM windows "
                "WHERE resolved_outcome IN ('Up','Down') AND strike_binance IS NOT NULL "
                "AND final_binance IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            conn.close(); continue
        for ws, strike, final, outcome in wins:
            if ws in seen or strike <= 0 or final <= 0:
                continue
            seen.add(ws)
            r = conn.execute(
                "SELECT time_left, up_ask, down_ask, up_mid, price_binance FROM snapshots "
                "WHERE window_start=? AND up_ask IS NOT NULL AND down_ask IS NOT NULL "
                "AND up_mid IS NOT NULL AND price_binance IS NOT NULL "
                "ORDER BY ABS(time_left-?) LIMIT 1", (ws, TL)).fetchone()
            if not r:
                continue
            t_l, ua, da, um, px = r
            if abs(t_l - TL) > TOL or px <= 0:
                continue
            won_up = 1 if outcome == "Up" else 0
            trend = float(np.log(px / strike))         # causal move so far (the 1st moment the maker sees)
            r5 = float(np.log(final / strike))         # realized 5-min return (for the trailing proxy)
            out.append((ws, ua, da, um, won_up, trend, r5))
        conn.close()
    out.sort(key=lambda x: x[0])
    return out


def trailing_proxy(r5, fn):
    """Strictly-causal trailing skew: proxy[j] = fn(r5[max(0,j-N):j]) over returns STRICTLY before j."""
    out = np.full(len(r5), np.nan)
    for j in range(len(r5)):
        if j >= MIN_TRAIL:
            out[j] = fn(r5[max(0, j - N_TRAIL):j])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robust", action="store_true", help="use Bowley quantile skew (secondary cross-check)")
    ap.add_argument("--m-lo", type=float, default=M_LO, dest="m_lo")
    ap.add_argument("--m-hi", type=float, default=M_HI, dest="m_hi")
    args = ap.parse_args()
    skew_fn = robust_skew if args.robust else sample_skew
    tag = "robust(Bowley)" if args.robust else "moment"

    rows = []
    for c in coins.ENABLED:
        rc = load(c)
        r5 = np.array([x[6] for x in rc])
        sk = trailing_proxy(r5, skew_fn)
        for i, x in enumerate(rc):
            rows.append((c,) + x + (sk[i],))
        nfin = int(np.isfinite(sk).sum())
        print(f"  loaded {c}: {len(rc)} windows, {nfin} with a {tag}-skew proxy "
              f"(trailing skew mean {np.nanmean(sk):+.3f})")

    coin = np.array([r[0] for r in rows])
    ws   = np.array([r[1] for r in rows], float)
    uask = np.array([r[2] for r in rows], float)
    dask = np.array([r[3] for r in rows], float)
    umid = np.array([r[4] for r in rows], float)
    wup  = np.array([r[5] for r in rows], float)
    trend = np.array([r[6] for r in rows], float)
    skew = np.array([r[8] for r in rows], float)

    have = np.isfinite(skew)
    band = have & (umid >= args.m_lo) & (umid < args.m_hi)
    print(f"\nCONDITIONAL-SKEW RESIDUAL  tl~{TL:g}  proxy={tag}  N_trail={N_TRAIL}  "
          f"moneyness up_mid∈[{args.m_lo},{args.m_hi})")
    print("=" * 88)
    print(f"  windows with proxy: {int(have.sum())}   in moneyness band: {int(band.sum())}   "
          f"(band Up-rate {wup[band].mean():.3f}, mean up_mid {umid[band].mean():.3f})")

    # raw association: does the skew proxy correlate with the unpriced residual (won_up − up_mid)?
    resid = wup - umid
    rho = np.corrcoef(skew[band], resid[band])[0, 1]
    print(f"  corr(skew, residual won_up−up_mid) in band = {rho:+.3f}   "
          f"(theory: NEGATIVE — neg-skew ⇒ Up underpriced ⇒ residual>0)")

    # 1) joint control (full proxy set, not just band, for power)
    joint_control(umid[have], trend[have], skew[have], wup[have], ws[have])

    # 2) dose-response across per-coin CAUSAL skew terciles (self-normalizing, no fitted threshold)
    rank = rolling_pct_rank(skew, ws, lookback=400, min_obs=60, groups=coin)
    print("\n  DOSE-RESPONSE  per-coin causal skew terciles (in moneyness band):")
    print("      tercile            n   Up-rate  mean up_mid  residual(won−mid)")
    terc = [("T1 most-neg skew", rank < 1/3), ("T2 mid", (rank >= 1/3) & (rank < 2/3)),
            ("T3 most-pos skew", rank >= 2/3)]
    for name, m in terc:
        mm = m & band & np.isfinite(rank)
        if mm.sum() >= 10:
            print(f"      {name:18s} {int(mm.sum()):>4}   {wup[mm].mean():.3f}    "
                  f"{umid[mm].mean():.3f}       {resid[mm].mean():+.4f}")
        else:
            print(f"      {name:18s} {int(mm.sum()):>4}   (too few)")

    # 3) NET-EV GATE — pre-committed directional trade (sign from option theory, NOT fitted):
    #    most-NEGATIVE-skew tercile -> BUY UP (taker @ up_ask);  most-POSITIVE -> BUY DOWN (@ down_ask).
    buy_up = band & np.isfinite(rank) & (rank < 1/3)
    buy_dn = band & np.isfinite(rank) & (rank >= 2/3)
    g_ask = np.concatenate([uask[buy_up], dask[buy_dn]])
    g_won = np.concatenate([wup[buy_up], 1 - wup[buy_dn]])
    g_ws  = np.concatenate([ws[buy_up], ws[buy_dn]])
    print(f"\n  NET-EV GATE  (pre-committed sign): buy Up in T1 ({int(buy_up.sum())}), "
          f"buy Down in T3 ({int(buy_dn.sum())})  -> {len(g_ask)} directional taker bets")
    # n_trials = honest within-experiment count (2 skew defs x 4 N_TRAIL x 5 bands ~ 40, per the
    # second-mind grid); deflated p is already 1.0 so this only hardens the kill.
    a = S.assess(g_ask, g_won, g_ws, n_trials=40, label="skew directional (theory sign, ATM band)")
    S.print_assess(a)

    # LOCO sign-stability: per-coin mean residual in the T1(neg) and T3(pos) cells — is the sign one-coin-driven?
    print("\n  LOCO sign-stability (per-coin residual in T1 neg-skew / T3 pos-skew cells; want T1>0>T3 broadly):")
    for c in coins.ENABLED:
        cm = coin == c
        t1 = cm & buy_up; t3 = cm & buy_dn
        if t1.sum() >= 8 and t3.sum() >= 8:
            print(f"      {c}: T1 residual {resid[t1].mean():+.4f} (n={int(t1.sum())})   "
                  f"T3 residual {resid[t3].mean():+.4f} (n={int(t3.sum())})")
        else:
            print(f"      {c}: too few (T1 {int(t1.sum())}, T3 {int(t3.sum())})")

    # drift monitor on the gated directional bets
    mon_ws = g_ws; mon_won = g_won; mon_ask = g_ask
    order = np.argsort(mon_ws, kind="stable")
    if len(order) >= 155:
        m = rolling_wilson_monitor(mon_ws[order], mon_won[order], mon_ask[order],
                                   np.ones(len(order), bool), window=150)
        if m:
            print(f"\n  DRIFT MONITOR (rolling Wilson-LB(win) − breakeven, window=150): latest {m[0]:+.4f}  "
                  f"frac<0 {m[1]:.2f}  ({m[2]} steps)")

    print("\n  READ vs the PRE-COMMITTED KILL: DEAD if (a) skew coef collapses under joint control, OR")
    print("  (b) no monotone dose-response across terciles, OR (c) the net-EV gate FAILS/fee-capped with")
    print("  n_loss≥30, OR (d) sign one-coin-driven / only works flipped. The sign is locked from theory.")


if __name__ == "__main__":
    main()

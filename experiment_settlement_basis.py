"""THREAD B — settlement-feed mismatch harness (the maker prices BINANCE, the market settles CHAINLINK).

The one structurally-open maker-component edge (see maker_behavior.md sections 0/7/9; memory settlement-basis-wall).
The maker computes fair value off Binance (verified R2=0.75) but the market resolves on the Chainlink <coin>/USD
oracle. The Binance(USDT)-vs-Chainlink(USD) basis is a NEAR-CONSTANT ~16 bps (~$100) that MOSTLY CANCELS in the
Up/Down outcome (strike & final share the denomination). The edge, if any, is the NON-CANCELLING RESIDUAL: when
the USDT/USD basis MOVES within the window, or near the strike where a few bps flips Up<->Down, the maker's
Binance-favorite settles the OTHER way on Chainlink. We bet the Chainlink-implied side BEFORE the maker (it never
re-prices to Chainlink). NOTE: a divergence window means the Chainlink-implied side is the maker's UNDERDOG, so
the trade buys at a LOW ask (~0.35-0.55) and pays a HIGH taker fee (0.07*(1-p) ~ 3-4.5%) -> it needs a high
flip-hit-rate to clear, which is exactly why the residual must be NEAR-STRIKE-selected, not basis-noise.

THIS IS A DATA-GATED HARNESS (Chainlink layer started 2026-06-27; only a handful of realized flips so far ->
every gated cell is INSUFFICIENT by construction). Its job NOW is to (1) VALIDATE Chainlink is the settlement
source, (2) MEASURE the realized flip rate AND whether resolved_outcome actually tracks Chainlink at the boundary
(the kill-relevant check), and (3) build the CAUSAL, NEAR-STRIKE-gated decision-time predictor wired to
stats.assess. DO NOT read a verdict from it yet; DO NOT arm live_runner. See the PRE-REGISTRATION block at the end.

CAUSAL discipline: every signal input is the tick AT/BEFORE the decision instant (strict newest-before, no
two-sided tolerance). final_* / resolved_outcome are used ONLY as the LABEL and in the realized-stats sections.

RESEARCH-CONFIRMED ENCODING (deep-research Topic 2, 2026-06-28; RESEARCH-EXTERNAL.md): Polymarket's own market
rule is verbatim "the price according to Chainlink DATA STREAM BTC/USD, not other sources or spot markets";
Up iff final >= strike with TIES (final==strike) resolving UP. The settled value is the Chainlink DON-consensus
MEDIAN (a MULTI-VENUE aggregate), so the basis we trade is Binance(single-venue) vs Chainlink-median — flips are
driven by BINANCE-IDIOSYNCRATIC moves the median doesn't follow (smaller/noisier than a clean two-feed gap).
There is NO oracle-sniping/OEV/MEV angle (the snapshot is non-movable; we can only position BEFORE). The binding
wall is Synthetix's economic law fee < exploitable-move; the USDT/USD basis is tens of bps, two-sided, mostly
cancels and is NOT a predictable drift. (Open: Polymarket's exact report-selection at the boundary is unconfirmed
by docs.)

    python experiment_settlement_basis.py [--tl 30] [--kappa 0.5] [--coins all]
"""
import argparse
import sqlite3

import numpy as np

import coins
from analysis import stats as S
from net_ev import breakeven_winrate

DEADBAND_MID = 0.01      # skip near-50/50 maker mids (no real favorite -> a coin-flip is not a divergence)
DEADBAND_MONEY = 0.0     # cl_money exact-tie guard handled explicitly


def chainlink_before(con, target_ts, tol=20.0):
    """STRICTLY-CAUSAL decision-time Chainlink price = the newest source='chainlink' tick AT or BEFORE
    target_ts (within tol s). No two-sided tolerance -> can never peek toward settlement. None if none retained."""
    try:
        r = con.execute(
            "SELECT mid FROM price_ticks WHERE source='chainlink' AND recv_ts <= ? AND recv_ts >= ? "
            "ORDER BY recv_ts DESC LIMIT 1", (target_ts, target_ts - tol)).fetchone()
    except sqlite3.OperationalError:
        return None
    return r[0] if r and r[0] is not None else None


def _rv_remaining(path, tl):
    """Causal per-sqrt-second realized vol over the trailing ~2min before decision -> scaled to the REMAINING
    time: sigma_remaining ~ rv * sqrt(tl) (the $ move scale that could still flip the outcome)."""
    tw = [(300.0 - r[0], r[4]) for r in path if tl <= r[0] <= tl + 150.0 and r[4] and r[4] > 0]
    if len(tw) < 10:
        return None
    tw.sort()
    t = np.array([x[0] for x in tw]); sp = np.array([x[1] for x in tw])
    lr = np.diff(np.log(sp)); dt = np.diff(t); ok = dt > 0
    if ok.sum() < 8:
        return None
    rv = np.sqrt(np.mean(lr[ok] ** 2 / dt[ok]))           # per-sqrt-sec, in log-return units
    if not (np.isfinite(rv) and rv > 0):
        return None
    return rv * np.sqrt(tl) * sp[-1]                       # -> approx $ move scale over the remaining tl seconds


def load(coin, tl):
    out = []; seen = set()
    for db in coins.all_dbs(coin):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        try:
            wins = con.execute(
                "SELECT window_start, strike_binance, strike_chainlink, final_binance, final_chainlink, "
                "resolved_outcome FROM windows WHERE resolved_outcome IN ('Up','Down') "
                "AND strike_binance IS NOT NULL AND strike_chainlink IS NOT NULL "
                "AND final_binance IS NOT NULL AND final_chainlink IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            con.close(); continue
        for ws, sb, scl, fb, fcl, ro in wins:
            if ws in seen:
                continue
            seen.add(ws)
            path = con.execute(
                "SELECT time_left, up_mid, up_ask, down_ask, price_binance FROM snapshots WHERE window_start=? "
                "AND up_mid IS NOT NULL AND up_ask IS NOT NULL AND down_ask IS NOT NULL "
                "AND price_binance IS NOT NULL ORDER BY time_left DESC", (ws,)).fetchall()
            dec = None
            if path:
                # STRICT newest-before-decision snapshot: smallest time_left that is still >= tl (at/just before)
                before = [r for r in path if r[0] >= tl - 0.5]
                snap = min(before, key=lambda r: r[0] - tl) if before else None
                if snap and snap[0] - tl <= 12.0:
                    t_l, um, ua, da, pxb = snap
                    px_cl = chainlink_before(con, ws + (300.0 - t_l))
                    sig = _rv_remaining(path, t_l)
                    dec = (t_l, um, ua, da, pxb, px_cl, sig)
            out.append((ws, sb, scl, fb, fcl, ro, dec))
        con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, default=30.0)
    ap.add_argument("--kappa", type=float, default=0.5,
                    help="near-strike gate: keep |cl_money| < kappa * sigma_remaining (structural, NOT fit). "
                         "As data deepens, self-normalize per-coin via adaptive.rolling_pct_rank instead.")
    ap.add_argument("--coins", default="all")
    args = ap.parse_args()
    clist = coins.ENABLED if args.coins == "all" else args.coins.split(",")

    rows = []
    for c in clist:
        rows += [(c,) + x for x in load(c, args.tl)]
    if not rows:
        print("  no fully-Chainlink-stamped resolved windows yet — keep the collector running."); return
    n = len(rows)
    print(f"THREAD B — settlement-feed mismatch harness  tl~{args.tl:g}  kappa={args.kappa:g}  "
          f"(DATA-GATED, structural validation)")
    print("=" * 92)

    # ---- (1) VALIDATE: is Chainlink the settlement source? ----
    cl_match = bin_match = flip = 0
    for (c, ws, sb, scl, fb, fcl, ro, dec) in rows:
        clo = "Up" if fcl >= scl else "Down"; bino = "Up" if fb >= sb else "Down"
        cl_match += (clo == ro); bin_match += (bino == ro); flip += (clo != bino)
    print(f"\n  (1) SETTLEMENT-SOURCE VALIDATION  (n={n}):")
    print(f"      chainlink-outcome matches resolved: {cl_match}/{n} ({100*cl_match/n:.1f}%)   "
          f"binance-outcome matches resolved: {bin_match}/{n} ({100*bin_match/n:.1f}%)")

    # ---- (2) MEASURE: flip rate AND does resolved actually track CHAINLINK at the boundary? (kill-relevant) ----
    print(f"\n  (2) REALIZED BASIS-FLIP RATE: binance vs chainlink outcome DISAGREE {flip}/{n} ({100*flip/n:.1f}%)")
    # the decisive premise check: in the flip windows, does resolved side == the CHAINLINK side or the BINANCE side?
    cl_side_wins = bin_side_wins = 0
    for (c, ws, sb, scl, fb, fcl, ro, dec) in rows:
        clo = "Up" if fcl >= scl else "Down"; bino = "Up" if fb >= sb else "Down"
        if clo != bino:
            cl_side_wins += (ro == clo); bin_side_wins += (ro == bino)
    if flip:
        print(f"      in the {flip} flip windows, resolved matched the CHAINLINK side {cl_side_wins}/{flip}, "
              f"the BINANCE side {bin_side_wins}/{flip}.")
        print(f"      => if resolved does NOT cleanly track Chainlink here, the edge's own LABEL is noisiest exactly")
        print(f"         where it must pay (our captured final-Chainlink tick != the exact settlement snapshot).")

    # ---- (3) CAUSAL, NEAR-STRIKE-gated decision-time predictor + the trade ----
    dec_rows = [r for r in rows if r[-1] is not None and r[-1][5] is not None and r[-1][6] is not None]
    print(f"\n  (3) CAUSAL NEAR-STRIKE DIVERGENCE PREDICTOR  (windows w/ decision-time chainlink tick + vol: "
          f"{len(dec_rows)}/{n}):")
    div_ask, div_won, div_ws = [], [], []
    n_div = n_near = 0
    for (c, ws, sb, scl, fb, fcl, ro, dec) in dec_rows:
        t_l, um, ua, da, pxb, pxcl, sig = dec
        if abs(um - 0.5) < DEADBAND_MID:                  # no real favorite -> not a divergence
            continue
        bin_money = pxb - sb
        cl_money = pxcl - scl
        if cl_money == 0:                                  # exact tie guard
            continue
        maker_fav = "Up" if um >= 0.5 else "Down"
        cl_implied = "Up" if cl_money > 0 else "Down"
        near = abs(cl_money) < args.kappa * sig            # NEAR-STRIKE: residual could flip the outcome
        if cl_implied != maker_fav and near:
            n_div += 1
            ask = ua if cl_implied == "Up" else da
            if ask and 0 < ask < 1:
                div_ask.append(ask); div_won.append(1 if cl_implied == ro else 0); div_ws.append(ws)
        n_near += near
    print(f"      near-strike windows (|cl_money| < {args.kappa:g}*sigma_remaining): {n_near}/{len(dec_rows)}   "
          f"near-strike DIVERGENCE trades: {n_div}")
    if len(div_ask) >= 10:
        aa = np.array(div_ask)
        print(f"      divergence-trade ask range [{aa.min():.2f},{aa.max():.2f}] (underdog -> fee "
              f"~{100*0.07*(1-aa.mean()):.1f}%/stake; needs hit-rate > {100*breakeven_winrate(aa.mean()):.0f}%)")
        a = S.assess(aa, np.array(div_won), np.array(div_ws),
                     n_trials=S.N_PROGRAM, label="THREAD B: near-strike chainlink-implied bet")
        S.print_assess(a)
    else:
        print(f"      only {len(div_ask)} near-strike divergence trades so far -> INSUFFICIENT "
              f"(need n_loss>=30; months more data).")
    _print_prereg()


def _print_prereg():
    print("""
  PRE-REGISTRATION (LOCKED — do not re-tune on this data):
    params : tl=30; near-strike gate |cl_money| < kappa(0.5)*sigma_remaining (causal trailing-vol * sqrt(tl),
             per-coin); maker-mid dead-band 0.01; entry = TAKER at the chainlink-implied side's ask; exit = HOLD;
             label = official resolved_outcome; log every selector variant to TrialsLedger so DSR deflates them.
    GRADUATE iff (months of data): the near-strike-selected subset has n_loss>=30 AND deflated cluster-bootstrap
             p<0.05 AND cluster-CI lo>0 net of the 0.07*(1-p) fee, replicated across >=3 coins (not one).
    KILL iff (once n_loss>=30): EITHER resolved tracks the Chainlink side <= it tracks the Binance side in the
             flip windows (section 2 -> the label doesn't cleanly track Chainlink at the boundary; no exploitable
             mismatch), OR the selected subset's net-EV CI includes 0 with deflated p>=0.05. settlement-basis-wall
             already found flip-rate ~ breakeven, so Thread B must show the CAUSALLY-SELECTED subset's flip-rate is
             materially BELOW its asks' breakeven, else it confirms the wall.
    STATUS : structure validated, verdict DATA-GATED. Thread B stays OPEN; live_runner stays GATED.""")


if __name__ == "__main__":
    main()

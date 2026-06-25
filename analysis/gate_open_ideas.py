"""Route EVERY still-open candidate through the corrected rigor gate (analysis/stats.assess).

`audit_candidates.py` only gated favorite-tail + spike-fade. This extends the SAME honest gate
(deflated cluster-bootstrap p on the fee-aware net-EV stream AND cluster-CI>0 AND n_loss>=30) to
the candidates that were "not yet proven unworking" as of the 2026-06-25 post-mortem:

  - token-fear FOLLOW   (buy the alt DOWN token on an informed dump; parked, revisit n_fired~1800)
  - B risk-filter       (skip alt favorite-tail when BTC opposes; pre-registered, forward+in-sample)
  - spike-gated fade    (fade an alt token dump that coincides with an idiosyncratic spot down-spike)

Maker-in-noise is settled separately (see experiment_maker_noise.py header + post-mortem): the cell
populates (~2254 modeled fills) but is -0.36/$1 from adverse selection; no causal toxicity gate with
data rescues it. So it is reported here as a fixed result, not re-mined.

    python -m analysis.gate_open_ideas
"""
from __future__ import annotations
import numpy as np

import coins
from analysis import stats as S


def _hdr(t):
    print("\n" + "=" * 82); print(t); print("=" * 82)


def gate_token_fear_follow():
    _hdr("TOKEN-FEAR FOLLOW  (buy alt DOWN token on an informed dump)  drop>=.05 peers~flat gap>=.05")
    from ideas_old.experiment_token_fear import load_sides, scan
    cl = list(coins.ENABLED)
    data, meta = load_sides(cl)
    fired, _ = scan(data, meta, cl, 0.05, 0.02, 0.05, (0.20, 0.85), follow=True)
    if not fired:
        print("  no fired positions"); return
    # fired rows: (coin, ws, tau, mid, ask, won) for the DOWN side
    asks = np.array([r[4] for r in fired]); wons = np.array([r[5] for r in fired])
    wsids = np.array([r[1] for r in fired])
    # honest N: this idea was mined over (fade/follow) x (drop, peer_tol, gap, band) sweeps x 6 coins
    a = S.assess(asks, wons, wsids, n_trials=60, label="token-fear FOLLOW (pooled)")
    S.print_assess(a)
    return a


def gate_b_riskfilter():
    _hdr("B RISK-FILTER  (skip alt favorite-tail when BTC's last 15s opposes the favorite)")
    import time, calendar
    from experiment_b_component import load_persec, Series, load_alt_positions
    TL, MIN_ASK, L = 30.0, 0.95, 15
    PREREG = calendar.timegm(time.strptime("2026-06-23T18:20:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    ALTS = [c for c in coins.ENABLED if c != "btc"]
    btc = Series(load_persec("btc", 1e9))
    rows = {c: [] for c in ALTS}
    for c in ALTS:
        for ws, t, ask, sign, won in load_alt_positions(c, TL, MIN_ASK, max(3.0, 0.3 * TL)):
            b1 = btc.at(t); b0 = btc.at(t - L)
            if not b1 or not b0 or b0 <= 0:
                continue
            rows[c].append((ws, ask, won, sign * (b1 / b0 - 1.0)))
    for tag, cutoff in (("IN-SAMPLE (all data)", 0), ("FORWARD (post-prereg)", PREREG)):
        gated = [(ws, a, w) for c in ALTS for (ws, a, w, s) in rows[c] if ws >= cutoff and s >= 0.0]
        if len(gated) < 10:
            print(f"  [{tag}] only {len(gated)} gated positions"); continue
        asks = np.array([g[1] for g in gated]); wons = np.array([g[2] for g in gated])
        wsids = np.array([g[0] for g in gated])
        a = S.assess(asks, wons, wsids, n_trials=40, label=f"B-gated favorite-tail — {tag}")
        S.print_assess(a)


def gate_spike_fade():
    _hdr("SPIKE-GATED FADE  (fade alt token dump coinciding w/ idiosyncratic spot down-spike z<-3)")
    try:
        from experiment_fear_dip import load_all
        from experiment_spike_fade import spot_z_lookups, scan
        data, meta = load_all(coins.ENABLED)
        lk = spot_z_lookups("2026-06", 300.0)
        _, spike_dumps, _ = scan(data, meta, lk, 0.05, 3.0, (0.20, 0.85))
        if not spike_dumps:
            print("  no spike-gated dumps"); return
        asks = np.array([r[4] for r in spike_dumps]); wons = np.array([r[5] for r in spike_dumps])
        wsids = np.array([r[1] for r in spike_dumps])
        a = S.assess(asks, wons, wsids, n_trials=30, label="spike-gated fade (buy Up)")
        S.print_assess(a)
        return a
    except Exception as e:
        print(f"  (skipped: {type(e).__name__}: {e})")


if __name__ == "__main__":
    gate_token_fear_follow()
    gate_b_riskfilter()
    gate_spike_fade()
    print("\n" + "=" * 82)
    print("GATE: SURVIVES iff deflated cluster-bootstrap p<0.05 AND cluster-CI excludes 0 AND n_loss>=30.")
    print("INSUFFICIENT (n_loss<30) is NOT a pass — the -100% tail makes a loss-light CI meaningless.")
    print("=" * 82)

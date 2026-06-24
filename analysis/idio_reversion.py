"""IDIOSYNCRATIC-SPIKE REVERSION — does a lone small-cap spike fill the gap predictably,
at a timescale WE can act on?

The idea (memory `idiosyncratic-spike-idea`): a small coin spikes idiosyncratically (a whale
dump on one venue; peers/majors flat) and, because crypto is fragmented across exchanges, the
arbitrage that fills the gap isn't instant -> a brief PREDICTABLE reversion. The make-or-break
question for US (we are not an HFT): is that reversion visible/actionable at >=1s, or is it all
sub-second (in which case we can't play it)?

Method: reuse the adaptive cross-asset detector (analysis/cross_asset_factor) on DEEP 1s spot.
z_i(t) = (r_i - beta_BTC*r_BTC - beta_ETH*r_ETH)/sigma(eps_i) = the standardized IDIOSYNCRATIC
1s move. A DOWN-spike = z < -THRESH (a big move the majors don't explain). Then measure the
FORWARD cumulative residual (the idiosyncratic component) over the next k seconds: if it comes
back POSITIVE, the gap filled (reversion); if ~0 or negative, it persisted (informed / no edge).

This characterizes the PREMISE on years of data. It does NOT test the token/Polymarket trade
(thin data); it tells us whether an actionable reversion exists at all.

    python -m analysis.idio_reversion [--start 2026-01] [--hl 300] [--thresh 3.0]
"""
from __future__ import annotations
import argparse, sys
import numpy as np
import pandas as pd
from analysis.cross_asset_factor import load_minute_returns, adaptive_betas, FACTORS, COINS

HORIZONS = [1, 5, 15, 30, 60, 120]   # seconds forward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01", help="first month YYYY-MM (1s data is heavy; 6mo default)")
    ap.add_argument("--hl", type=float, default=300.0, help="adaptive-beta half-life in SECONDS (spike scale)")
    ap.add_argument("--thresh", type=float, default=0.0, help="|z| spike threshold (0 = sweep 3/5/7/10)")
    a = ap.parse_args()
    print(f"loading 6 coins @ 1s from {a.start} (heavy) ...", file=sys.stderr)
    ret, _ = load_minute_returns(a.start, 1)          # interval=1 -> 1s returns
    days = len(ret) / 86400.0
    alts = [c for c in COINS if c not in FACTORS]

    # precompute z / resid / cumulative-resid per alt ONCE (the expensive part), then sweep thresholds
    prec = {}
    for alt in alts:
        ab = adaptive_betas(ret, alt, a.hl)
        z = ab["z"].values; resid = ab["resid"].values
        prec[alt] = (z, resid, np.nancumsum(np.nan_to_num(resid)))

    thresholds = [a.thresh] if a.thresh else [3.0, 5.0, 7.0, 10.0]
    for thr in thresholds:
        print("\n" + "=" * 96)
        print(f"IDIOSYNCRATIC-SPIKE REVERSION   1s spot   ~{days:.0f}d   hl={a.hl:.0f}s   "
              f"DOWN-spike = z < -{thr}")
        print("  fwd bps = mean cumulative idiosyncratic return after the spike (+ = gap fills);  "
              "%rec = fwd / spike;  %+ = share reverting")
        print("=" * 96)
        print(f"{'coin':5} {'n_dn':>7} {'/day':>7} {'spk_bps':>8} | " +
              "  ".join(f"{('+'+str(k)+'s'):>15}" for k in HORIZONS))
        for alt in alts:
            z, resid, cumr = prec[alt]
            valid = np.isfinite(z) & np.isfinite(resid)
            dn = valid & (z < -thr)
            n = int(dn.sum())
            if n < 20:
                print(f"{alt.upper():5} {n:>7} (too few)"); continue
            spike_bps = -np.nanmean(resid[dn]) * 1e4
            cells = []
            for k in HORIZONS:
                fwd = np.empty(len(resid)); fwd[:] = np.nan
                fwd[:-k] = cumr[k:] - cumr[:-k]
                f = fwd[dn]; f = f[np.isfinite(f)]
                cells.append(f"{np.mean(f)*1e4:>+6.1f} {(np.mean(f)/(-np.nanmean(resid[dn])))*100:>+4.0f}% "
                             f"{np.mean(f>0)*100:>3.0f}%")
            print(f"{alt.upper():5} {n:>7} {n/days:>7.1f} {spike_bps:>8.1f} | " + "  ".join(cells))

    print("=" * 96)
    print("READ: actionable reversion exists iff forward bps stays POSITIVE and GROWS into the +5..+60s")
    print("  horizons (the gap fills over seconds we can trade) AND %rec is a meaningful fraction of the spike.")
    print("  If forward ~0 / negative, the spike was informed or the revert is sub-second -> no edge for us.")
    print("  NB: even if reversion is real here, the 5-min OUTCOME is ~unchanged by a reverting spike -> the")
    print("  tradable form is the TOKEN overshoot/lag (thin Polymarket data); this only tests the PREMISE.")


if __name__ == "__main__":
    main()

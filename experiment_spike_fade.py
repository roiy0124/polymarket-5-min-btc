"""SPIKE-GATED FADE — does the idiosyncratic-spike NOISE filter resurrect the fear-fade?

The fear-fade (buy the alt UP token when it dumps) DIED because the dumps were INFORMED
(gated on peer TOKENS staying flat). This gates the same fade on a DIFFERENT, cleaner noise
signal: the alt's OWN SPOT just had an idiosyncratic spike (a move the majors don't explain,
shown to PARTIALLY mean-revert in analysis/idio_reversion.py). Hypothesis: a token dump that
coincides with an idiosyncratic spot DOWN-spike is (more) noise -> the token over-reacts ->
fade it (buy UP, hold to 0/1).

Compares, on the same token dumps: ALL dumps vs SPIKE-GATED dumps (alt spot z < -ZTHRESH at the
decision second). If the spike gate pushes the fade residual from negative toward positive, the
noise filter works. Causal: spot z uses only data up to the decision second. Thin Polymarket
token data => directional, power-limited.

    python experiment_spike_fade.py --drop 0.05 --zthresh 3 --hl 300
"""
import argparse

import numpy as np

import coins
from net_ev import net_ev_per_dollar
from experiment_fear_dip import load_all, ev_stats, GRID
from analysis.cross_asset_factor import load_minute_returns, adaptive_betas, FACTORS

ALTS = [c for c in coins.ENABLED if c not in FACTORS]


def spot_z_lookups(start, hl):
    """Per-alt (secs, z) arrays: the causal idiosyncratic spot z at 1s over the token period."""
    ret, _ = load_minute_returns(start, 1)                 # 1s returns, all coins, recent
    secs = ret.index.values.astype(np.int64)
    return {a: (secs, adaptive_betas(ret, a, hl)["z"].values) for a in ALTS}


def z_at(lk, alt, ts, max_stale=30):
    secs, z = lk[alt]
    i = int(np.searchsorted(secs, ts, side="right")) - 1
    if i < 0 or (ts - secs[i]) > max_stale:
        return None
    v = z[i]
    return float(v) if np.isfinite(v) else None


def scan(data, meta, lk, drop, zthr, band):
    """Return (dumps, spike_dumps, universe). dumps = token dumps (fade-Up); spike_dumps =
    those whose alt SPOT z at the decision second < -zthr. First qualifying tau / window."""
    dumps, spike_dumps, universe = [], [], []
    all_ws = set().union(*[set(data[c]) for c in coins.ENABLED])
    for ws in all_ws:
        present = [c for c in ALTS if ws in data[c]]
        for X in present:
            won = meta[X][ws]; first_d = first_s = None
            for tau in GRID:
                if tau == GRID[0]:
                    continue
                g = data[X][ws]
                if tau not in g or (tau + 30) not in g:
                    continue
                um, ua = g[tau]; dropX = um - g[tau + 30][0]
                if band[0] <= um <= band[1]:
                    universe.append((X, ws, tau, um, ua, won))
                if dropX <= -drop and band[0] <= um <= band[1]:
                    if first_d is None:
                        first_d = (X, ws, tau, um, ua, won)
                    zs = z_at(lk, X, ws + (300 - tau))      # alt spot z at the decision second
                    if zs is not None and zs < -zthr and first_s is None:
                        first_s = (X, ws, tau, um, ua, won)
            if first_d:
                dumps.append(first_d)
            if first_s:
                spike_dumps.append(first_s)
    return dumps, spike_dumps, universe


def show(label, s):
    if not s:
        print(f"  {label:>16}: (none)"); return
    print(f"  {label:>16}: n={s['n']:>4} win {100*s['win']:>5.1f}% mid {s['mid']:.2f} ask {s['ask']:.2f} "
          f"EV {s['ev']:>+7.4f} resid {s['resid']:>+6.3f} wlb-be {s['wlb']-s['be']:>+.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", type=float, default=0.05, help="min alt up_mid drop over 30s (token dump)")
    ap.add_argument("--zthresh", type=float, default=3.0, help="idiosyncratic spot down-spike: alt z < -this")
    ap.add_argument("--hl", type=float, default=300.0, help="adaptive spot-beta half-life (s)")
    ap.add_argument("--start", default="2026-06", help="spot month covering the token windows")
    ap.add_argument("--band", default="0.20,0.85")
    args = ap.parse_args()
    band = tuple(float(x) for x in args.band.split(","))

    print("loading token grid (all DBs) ...", flush=True)
    data, meta = load_all(coins.ENABLED)
    print(f"loading 1s spot from {args.start} + adaptive z ...", flush=True)
    lk = spot_z_lookups(args.start, args.hl)
    dumps, spike_dumps, universe = scan(data, meta, lk, args.drop, args.zthresh, band)

    print(f"\nSPIKE-GATED FADE (buy Up, hold 0/1)  |  token drop<=-{args.drop}, spot z<-{args.zthresh}, band={band}")
    show("mid-band univ", ev_stats(universe))
    show("ALL dumps", ev_stats(dumps))
    show("SPIKE dumps", ev_stats(spike_dumps))

    sd = ev_stats(spike_dumps)
    if sd and sd["n"] >= 20 and len(universe) > sd["n"]:
        import random
        rng = random.Random(7); k = sd["n"]; draws = []
        for _ in range(4000):
            sub = rng.sample(universe, k)
            draws.append(sum(net_ev_per_dollar(r[4], r[5], "taker", "hold") for r in sub) / k)
        draws.sort()
        p = sum(1 for x in draws if x >= sd["ev"]) / len(draws)
        print(f"\n  PLACEBO (random {k} same-band Up buys): signal {sd['ev']:+.4f} -> p={p:.3f} "
              f"{'(beats random)' if p < 0.05 else '(not distinguishable)'}")
    print("\n  per-coin SPIKE dumps:")
    for c in ALTS:
        sc = ev_stats([r for r in spike_dumps if r[0] == c])
        if sc:
            print(f"    {c:>5}: n={sc['n']:>3} resid {sc['resid']:>+6.3f} EV {sc['ev']:>+7.4f}")
    print("\n  READ: the spike NOISE-filter works iff SPIKE-dumps resid is clearly > ALL-dumps resid AND > 0")
    print("  (the token over-reacted to a noise spike -> fade pays). Else the spike is informed too -> dead.")


if __name__ == "__main__":
    main()

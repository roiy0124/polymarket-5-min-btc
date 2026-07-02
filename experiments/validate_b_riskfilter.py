"""LOCKED validation runner for the pre-registered B risk-filter (memory b-riskfilter-preregistered).

Hypothesis (LOCKED 2026-06-23 — do NOT change these to chase a result):
  Base = favorite-tail: at time_left~TL, buy the favorite (price vs strike) at ask>=MIN_ASK, hold to 0/1.
  GATE = SKIP the entry when BTC's last-L-second move OPPOSES the favorite (btc_sig < 0).
  Claim = the gate lifts net EV by cutting boundary-flip losers the alt quote hasn't repriced from BTC's lead.

This runner is PARAMETER-LOCKED (TL, MIN_ASK, L below) so a future re-test has ZERO researcher
degrees of freedom. It evaluates ONLY data collected AFTER the pre-registration instant (forward /
out-of-sample by construction); pass --all for an in-sample dry-run of the machinery on current data.

Decision bar (all four must hold on FORWARD data with NON-DEGENERATE losses):
  1. EV:        gated net EV/$1  >  baseline (trade-all)               [via net_ev]
  2. WILSON:    gated Wilson-LB(win) > ask+fee breakeven, with >= MIN_LOSERS gated losses (non-degenerate)
  3. REPLICATE: gated EV > baseline per-coin and on every leave-one-coin-out fold
  4. PLACEBO:   gate beats a same-size random subset (p<0.05) AND a BTC-signal permutation (p<0.05)

    python validate_b_riskfilter.py            # forward data only (the real test)
    python validate_b_riskfilter.py --all      # in-sample dry-run (reproduce the discovery; NOT validation)
"""

import sys
import time
import random
import argparse
import calendar

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import coins
from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb
from experiment_b_component import load_persec, Series, load_alt_positions

# ---- LOCKED PARAMETERS (pre-registered 2026-06-23; changing these invalidates the test) ----
TL = 30.0                       # decision time_left (s)
MIN_ASK = 0.95                  # favorite-tail band
L = 15                          # BTC move lookback (s)
PREREG_UTC = "2026-06-23T18:20:00Z"
PREREG_TS = calendar.timegm(time.strptime(PREREG_UTC, "%Y-%m-%dT%H:%M:%SZ"))
MIN_LOSERS = 30                 # need >= this many gated losses for a NON-degenerate win-rate CI
ALTS = [c for c in coins.ENABLED if c != "btc"]


def ev_of(rows):
    """rows: list of (ask, won). -> (n, losses, win, net_ev/$1, wilson_lb, breakeven)."""
    if not rows:
        return None
    per = [net_ev_per_dollar(a, w, "taker", "hold") for a, w in rows]
    per = [x for x in per if x is not None]
    n = len(rows); k = sum(w for _, w in rows)
    a_mean = sum(a for a, _ in rows) / n
    return dict(n=n, losses=n - k, win=k / n, ev=sum(per) / len(per),
                wlb=wilson_lb(k, n), be=breakeven_winrate(a_mean))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="in-sample dry-run on ALL data (not validation)")
    ap.add_argument("--boot", type=int, default=3000)
    args = ap.parse_args()

    cutoff = 0 if args.all else PREREG_TS
    mode = "IN-SAMPLE DRY-RUN (machinery check, NOT validation)" if args.all else \
           f"FORWARD / OUT-OF-SAMPLE (windows after {PREREG_UTC})"
    print("=" * 78)
    print("LOCKED VALIDATION — B risk-filter (skip alt favorite-tail when BTC opposes the favorite)")
    print(f"  params: tl={TL:g}s ask>={MIN_ASK} L={L}s | mode: {mode}")
    print("=" * 78)

    btc = Series(load_persec("btc", 1e9))
    rows = {}                      # coin -> list of (ask, won, btc_sig)
    for c in ALTS:
        ap_ser = Series(load_persec(c, 1e9))
        rows[c] = []
        for ws, t, ask, sign, won in load_alt_positions(c, TL, MIN_ASK, max(3.0, 0.3 * TL)):
            if ws < cutoff:
                continue
            b1 = btc.at(t); b0 = btc.at(t - L)
            if not b1 or not b0 or b0 <= 0:
                continue
            rows[c].append((ask, won, sign * (b1 / b0 - 1.0)))

    base_all = [(a, w) for c in ALTS for (a, w, s) in rows[c]]
    gate = lambda r: [(a, w) for (a, w, s) in r if s >= 0.0]      # LOCKED gate: skip btc_sig < 0
    gated_all = [(a, w) for c in ALTS for r in [rows[c]] for (a, w) in gate(r)]

    nfwd = len(base_all)
    print(f"\n{'coin':>5} {'n':>4} {'gated_n':>7} {'base_loss':>9} {'gated_loss':>10}")
    for c in ALTS:
        b = rows[c]; g = gate(b)
        print(f"{c:>5} {len(b):>4} {len(g):>7} {sum(1 for _,w,_ in b if w==0):>9} {sum(1 for a,w in g if w==0):>10}")
    print(f"{'ALL':>5} {nfwd:>4} {len(gated_all):>7}")

    if nfwd == 0:
        print(f"\n>>> 0 forward positions yet. Pre-registered {PREREG_UTC}; let the collector run "
              f"~2-4 weeks, then re-run. (Use --all for an in-sample machinery check.)")
        return

    base = ev_of(base_all); gated = ev_of(gated_all)
    print(f"\n{'set':>10} {'n':>5} {'loss':>4} {'win%':>6} {'net EV/$1':>10} {'WilsonLB':>9} {'breakeven':>9}")
    for tag, s in (("baseline", base), ("GATED", gated)):
        print(f"{tag:>10} {s['n']:>5} {s['losses']:>4} {100*s['win']:>5.1f}% {s['ev']:>+10.4f} "
              f"{s['wlb']:>9.4f} {s['be']:>9.4f}")

    # ---- the four checks ----
    rng = random.Random(20260623)
    c1 = gated["ev"] > base["ev"]
    c2 = (gated["wlb"] > gated["be"]) and (gated["losses"] >= MIN_LOSERS)
    # per-coin + LOCO
    def coin_ev(cs):
        rs = [(a, w) for c in cs for (a, w) in gate(rows[c])]
        bb = [(a, w) for c in cs for (a, w, s) in rows[c]]
        if not rs or not bb:
            return None
        return ev_of(rs)["ev"] - ev_of(bb)["ev"]
    percoin = {c: coin_ev([c]) for c in ALTS}
    loco = {c: coin_ev([x for x in ALTS if x != c]) for c in ALTS}
    c3 = all((percoin[c] is not None and percoin[c] > 0) for c in ALTS) and \
         all((loco[c] is not None and loco[c] > 0) for c in ALTS)
    # placebo: random same-size subset; permutation: shuffle the btc_sig sign
    k = len(gated_all)
    def rand_ev():
        pick = rng.sample(base_all, k) if k <= len(base_all) else base_all
        return ev_of(pick)["ev"]
    null_rand = sorted(rand_ev() for _ in range(args.boot))
    p_rand = sum(1 for x in null_rand if x >= gated["ev"]) / len(null_rand)
    def perm_ev():
        out = []
        for c in ALTS:
            sgs = [s for (_, _, s) in rows[c]]; rng.shuffle(sgs)
            out += [(a, w) for (a, w, _), s in zip(rows[c], sgs) if s >= 0.0]
        return ev_of(out)["ev"] if out else -9
    null_perm = sorted(perm_ev() for _ in range(args.boot))
    p_perm = sum(1 for x in null_perm if x >= gated["ev"]) / len(null_perm)
    c4 = (p_rand < 0.05) and (p_perm < 0.05)

    # ---- CONTROL ARM (added 2026-06-25, second-mind review): falsify the CROSS-ASSET story ----
    # B's whole claim is "BTC LEADS the alt." If the alt's OWN last-L-second move gates as well or
    # better than BTC's, B is just a generic favorite-MOMENTUM filter (skip when the favorite is
    # mid-move against you) with no cross-asset content. We re-mine the SAME positions using the
    # alt's own per-second series as the gate signal and compare. On discovery data the own-momentum
    # gate BEAT BTC's and B's orthogonal (BTC-minus-own) component was negative -> story falsified.
    own = {c: Series(load_persec(c, 1e9)) for c in ALTS}
    rows_own = {c: [] for c in ALTS}
    for c in ALTS:
        for ws, t, ask, sign, won in load_alt_positions(c, TL, MIN_ASK, max(3.0, 0.3 * TL)):
            if ws < cutoff:
                continue
            a1 = own[c].at(t); a0 = own[c].at(t - L)
            if not a1 or not a0 or a0 <= 0:
                continue
            rows_own[c].append((ask, won, sign * (a1 / a0 - 1.0)))
    gated_own = [(a, w) for c in ALTS for (a, w, s) in rows_own[c] if s >= 0.0]
    own_ev = ev_of(gated_own)["ev"] if gated_own else None
    c5 = (own_ev is None) or (gated["ev"] > own_ev)      # B must beat its own-momentum twin

    def mark(b):
        return "PASS" if b else "FAIL"
    print(f"\n  CHECK 1 EV gated>baseline ............ {mark(c1)}  ({gated['ev']:+.4f} vs {base['ev']:+.4f})")
    print(f"  CHECK 2 Wilson-LB>be & >={MIN_LOSERS} losses .. {mark(c2)}  "
          f"(wlb-be {gated['wlb']-gated['be']:+.4f}, gated losses {gated['losses']})")
    print(f"  CHECK 3 per-coin + LOCO all + ........ {mark(c3)}  "
          f"(per-coin min {min(v for v in percoin.values() if v is not None):+.4f})")
    print(f"  CHECK 4 placebo p<.05 (rand & perm) .. {mark(c4)}  (rand p={p_rand:.3f}, perm p={p_perm:.3f})")
    print(f"  CHECK 5 beats own-momentum control ... {mark(c5)}  "
          f"(B-gated {gated['ev']:+.4f} vs alt-own-momentum {own_ev:+.4f})" if own_ev is not None
          else f"  CHECK 5 beats own-momentum control ... {mark(c5)}  (no own-momentum positions)")
    if own_ev is not None and not c5:
        print(f"          -> cross-asset story FALSIFIED: the alt's OWN move gates >= BTC's, so B is a "
              f"generic favorite-momentum filter, not a BTC lead.")
    overall = c1 and c2 and c3 and c4 and c5
    print("\n  " + ("=" * 30))
    if args.all:
        print("  IN-SAMPLE DRY-RUN — machinery works. This is NOT validation (the edge was discovered")
        print("  in-sample). The real verdict is the FORWARD run on post-pre-registration data.")
    print(f"  OVERALL: {'>>> VALIDATED (all 4 pass on forward data) — consider arming <<<' if overall and not args.all else 'NOT validated' }")
    if not c2 and gated["losses"] < MIN_LOSERS:
        print(f"  (Wilson check is DEGENERATE: only {gated['losses']} gated losses < {MIN_LOSERS} — "
              f"need more data; a 0-1-loss 'pass' is the artifact we are guarding against.)")


if __name__ == "__main__":
    main()

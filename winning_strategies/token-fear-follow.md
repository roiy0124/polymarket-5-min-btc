# Token-Fear FOLLOW (buy the alt DOWN token on an informed dump) — TIER 3 (pre-registered candidate)

**The closest-to-edge *parked* thread in the project** — not because its net EV is positive (it
isn't yet), but because it is the **only** idea whose underlying signal is statistically significant
and cross-coin-consistent, with the kill being **cost, not absence of signal**. Every other dead
idea failed because there was no edge; this one fails because the taker fee + spread eat a *real* edge.

> **STATUS (2026-06-25, second-mind reviewed — `analysis/gate_open_ideas.py`):**
> - ✅ **Causal / real-time implementable, NO look-ahead.** Gate uses only past token moves; outcome is the label.
> - ✅ **Signal is REAL at the mid.** On n=599 fired: residual `won − down_MID` = **+0.052, cluster-CI [+0.009, +0.095], p=0.008**, **positive in all 6 coins** — the best cross-coin consistency *and* the only sub-0.05 cluster-bootstrap p in the whole program. An un-proportionate alt-token dump (vs peer tokens) is a genuine **informed-bearish** signal.
> - ⚠️ **FAILS net of cost.** −half-spread → +0.037 (p≈0.05); −3.1pp taker fee → **+0.024, cluster-CI [−0.074, +0.122], p=0.32**, placebo p=0.158, Wilson-LB(win) < breakeven on every coin. The Down-side ask (~2c over mid) + the 0.07·(1−p) fee consume the residual.
> - It graduates ONLY via a **fee-free maker-Down entry** (where the +0.052 gross-mid edge clears breakeven) OR materially more data — NOT by re-tuning the gate.

## The rule (exactly what a live bot does)
On a 30s grid within each 5-min window, for each alt coin `X` (peers = the other present coins):
1. `dropX = up_mid_X(τ) − up_mid_X(τ+30)` — the alt's own UP-token change over the last 30s.
2. `pchg  = mean over peers[ up_mid_p(τ) − up_mid_p(τ+30) ]` — the peer tokens' change.
3. **FIRE** iff `dropX ≤ −0.05` AND `pchg ≥ −0.02` (peers ~flat/up) AND `(dropX − pchg) ≤ −0.05`
   (the alt dumped ≥5c MORE than its peers) AND the UP token is mid-band `0.20 ≤ up_mid ≤ 0.85`.
4. On the first qualifying τ, **taker-BUY the DOWN token** at `down_ask`. **HOLD to 0/1** (fee only on entry).

One position per coin-window. Params **LOCKED** (drop 5c / gap 5c / peer-tol 2c / buy-Down).
Reproduce: `python ideas_old/experiment_token_fear.py --follow` · gated: `python -m analysis.gate_open_ideas`.

## Performance (causal, net of taker entry fee, window-clustered bootstrap CI)
| stage | value | read |
|---|---|---|
| fired | n=599, win 59.4%, mean down-ask 0.56 | healthy sample, 243 losers (non-degenerate) |
| gross resid (won − **mid**) | **+0.052, CI [+0.009, +0.095], p=0.008** | **the real, significant signal** — all 6 coins positive |
| − half-spread (won − ask) | +0.037, p≈0.05 | the ~1.6c Down half-spread eats ~⅓ |
| − taker fee → **net EV/$1** | **+0.024, CI [−0.074, +0.122], deflated p=1.0** | **FAILS the gate** — fee/skew sink it |
| placebo (vs random mid-band Down buys) | p=0.158 | net stream indistinguishable from random |

Per-coin net EV splits 3/3 (btc/eth/xrp +, sol/doge/bnb −), but the gross-**mid** residual is positive in
all 6 — so the *direction* replicates; only the cost margin doesn't.

## Why it isn't money yet
1. **Fee-capped, not signal-less.** The +0.052 mid-edge is real; the 0.07·(1−p) taker fee (~3.1pp here) + the
   ~1.6c Down half-spread (~4.7pp combined) is larger than the edge. This is the program's central wall
   (`../POSTMORTEM.md`, memory `market-efficient-no-knowledge-edge`) — but here the edge is the *largest* and
   the gap is the *smallest*, so it's the best candidate to flip if cost drops.
2. **−100% binary tail** (skew) makes the +0.024 mean unreliable; PSR/deflation push it below zero.
3. **Cross-coin within-window correlation** (a fear event hits several coins at once) shrinks the effective N,
   widening the cluster-CI to span zero despite n=599.

## Adaptivity / drift (2026-06-25, second-mind reviewed)
The fire condition `drop ≥ 0.05` (and `gap ≥ 0.05`) is an **absolute token-price move** that does NOT
scale with volatility — the single most drift-fragile param in the roster (token mid-vol swings far more
than spreads). The pre-registered **adaptive form** (the recommended primary when this is next re-tested):
self-normalize the drop **per coin** via `analysis/adaptive.rolling_pct_rank(drop, ws, groups=coin)` —
fire when the drop is in the bottom percentile of *its own coin's* recent drop distribution, instead of a
fixed 5c. No new fitted DOF (the percentile is fixed; only the reference floats). The `band`, side
(buy-Down), and `tl` grid stay fixed. Until then the LOCKED absolute params hold for the OOS re-test, but
do not deploy on the fixed `drop` without the self-normalized version (a vol regime shift would silently
change how often it fires).

## Path to Tier 1 (the two SEPARABLE levers — either one could flip it)
- **Fee-free maker-Down entry.** Rest a maker BUY on the DOWN token at `down_mid`/`down_bid` instead of crossing
  the ask. The +0.052 gross-**mid** edge clears breakeven with no taker fee. This is the principled variant (not a
  re-tune) and the single most likely path to viability — but it needs live maker-fill modeling, and must beat the
  adverse selection the passive branch lost to (cf. `experiments/experiment_maker_noise.py`: a naive resting bid is −0.36).
- **More data.** Today Wilson-LB(win) 0.555 < breakeven 0.575; if the win-rate holds, the LB crosses breakeven at
  **n_fired ≈ 1800** (~a few more months of the running collector). Re-run LOCKED; VIABLE iff Wilson-LB > breakeven
  AND placebo p < 0.05 AND the cluster-CI excludes 0 — or it REGRESSES (confirmed dead).
- **Fee drop / tighter Down spreads** — re-test immediately if the 5-min taker fee falls; ~halving it likely flips it +EV.

**Do NOT** re-tune drop/gap/peer-tol/band (overfit trap — see memory `reversion-fear-dip-idea`, the FADE direction
already died this way). `execution/live_runner.py` stays GATED until a clean pre-registered OOS / maker-entry pass.

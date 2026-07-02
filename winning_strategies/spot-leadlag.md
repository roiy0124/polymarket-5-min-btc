# Spot Cross-Asset Lead-Lag (SMT)  — TIER 3 (pre-registered candidate)

**Stage-1 (does the signal EXIST and is it STABLE) = PASS, emphatically. Stage-2 (does it
BEAT THE QUOTE + FEE) = UNPROVEN, and not testable on spot.** This card records the Stage-1
evidence and locks the direction for an out-of-sample Stage-2 test on live Polymarket data.

Tooling: `analysis/spot_data.py` (free Binance 1s store, all 6 coins to 2021-01, `data/spot/`),
`analysis/spot_leadlag.py` (this analysis; `--alts all`, outputs `spot_leadlag/`).
Reproduce: `python -m analysis.spot_leadlag --leader btc --alts all --start 2021-01`.

## Hypothesis
BTC's recent short-horizon move predicts each alt's next-5-min UP/DOWN outcome (alt
`final ≥ strike`) — the "sleepy alt lags the big coin" SMT idea. Decision is strictly causal:
at `t_d = t0 + 30s`, predictor = BTC return over `[t_d−15s, t_d]`; outcome scored only at
resolution. Three predictors, signed so **+r = co-move / −r = reversal**:
`leader` (BTC move), `gap` (BTC − alt move), `altown` (the alt's own move).

## Result 1 — DEEP 5.5-year stability (2021-01 → 2026-06, 575,783 windows/coin, decision t0+30s, H=15s)
| alt | r_leader | 95% CI | rolling sign-stability | r_gap | r_altown |
|---|---:|---|---:|---:|---:|
| ETH | **+0.131** | [+0.128,+0.133] | **100%** (283/283 buckets) | −0.084 | +0.151 |
| SOL | **+0.107** | [+0.104,+0.109] | **100%** | −0.113 | +0.147 |
| XRP | **+0.110** | [+0.108,+0.113] | **100%** | −0.097 | +0.145 |
| DOGE | **+0.113** | [+0.110,+0.115] | **100%** | −0.093 | +0.132 |
| BNB | **+0.115** | [+0.112,+0.117] | **100%** | −0.068 | +0.142 |

Every coin: BTC-lead is **positive, tight, and 100% sign-stable across 283 weekly buckets spanning
the 2021 bull, the 2022 bear (LUNA/FTX), the 2023–24 recovery, and 2025–26** — old-half ≈ new-half on
all. Outcome labels robust to boundary-close vs last-3s-mean vs near-boundary-exclusion (sign never flips).

**This decisively answers the non-stationarity worry ("maybe only the last month is relevant"): for THIS
signal the relationship is a 5.5-year structural constant, not a recent-regime artifact.**

## Result 2 — Robustness across decision time & horizon (recent 12mo, all 5 alts)
r_leader, with sign-stability in parentheses — **positive and 100% stable in every one of 35 (coin×framing) cells:**
| framing | r_leader range across coins |
|---|---|
| d=30, H=10 | +0.099 … +0.109 (100%) |
| d=30, H=15 | +0.119 … +0.132 (100%) |
| d=30, H=30 | +0.174 … +0.189 (100%) |
| d=30, H=60 | +0.129 … +0.137 (100%) |
| d=15, H=15 | +0.130 … +0.139 (100%) |
| d=60, H=15 | +0.116 … +0.128 (100%) |
| d=120, H=15 | +0.108 … +0.119 (100%) |

Magnitude scales sensibly (more with a longer predictor window H; decays slightly the later in the window you
decide) — but the **sign is never framing-fragile.** Not a knife-edge artifact.

## The honest reading — why this is NOT yet money
1. **r is signal-EXISTENCE, the UPPER BOUND — not edge.** The Polymarket alt token moves with BTC and with the
   alt's own price in real time, so by t0+30 the **quote already prices most of this**. The market is
   efficient-on-knowledge (residual-after-quote ~0 in prior tests). Stage 1 proves the signal is real and stable;
   it says nothing about what survives the ask + the ~3.5% taker fee.
2. **`altown` (+0.13–0.15, the strongest) is mostly mechanical and already priced** — the alt's recent move ≈ its
   price-vs-strike position, which is exactly what favorite-tail / the ask already encode. Not novel.
3. **The genuinely novel quantity is `leader`** — does BTC's move add information *beyond* the alt's own price?
   Stage 1 says it's independently real and stable. But it may still be fully priced into the alt quote. Only live
   token data settles that.
4. **`gap` is stably negative on spot**, yet the gap/convergence framing tested **dead on Polymarket** (residual,
   doge-noise) — a textbook illustration of (1): raw spot predictability ≠ post-quote edge.

## Stage 2 — what would promote this to Tier 1 (needs LIVE Polymarket data, can't be spot-tested)
The incremental value of the BTC-lead over the already-priced favorite is exactly the **B risk-filter** hypothesis,
already PRE-REGISTERED with LOCKED params: `experiments/validate_b_riskfilter.py` (skip an alt favorite-tail entry when BTC's
last ~15s move opposes the favorite). Re-evaluate after ≥2–4 weeks more live data accrue ≥30–50 alt losers.
**Pre-registered here:** the spot signal direction is **positive BTC-lead, all 5 alts, robust over d∈[15,120]s and
H∈[10,60]s** — so Stage 2 must not re-mine a sign/threshold; it only tests whether this locked, real signal beats
the quote net of fee. `live_runner` stays GATED.

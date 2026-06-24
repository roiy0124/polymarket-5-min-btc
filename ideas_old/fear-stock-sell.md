# Fear Stock-Sell (stock-vs-stock)  — PARKED 2026-06-24

**Status: explored to conclusion. The fade thesis is dead; the flip (follow) is a *real but
fee-capped* signal — parked, not killed.** Code: `experiment_token_fear.py` (this folder).

## The idea (the user's)
The Polymarket alt UP-tokens move proportionally to the big coins (BTC/ETH). Standard SMT: BTC up →
the alt's UP-token gets bid up to price the expected follow. **Fear** = when an alt's *token* gets
panic-**dumped** even though the **peer tokens did not drop** — the alt token moved *un-proportionately*
down, an unjustified fear sell → **fade it** (buy the discount, hold to 0/1).

Key framing the user insisted on (and the right one): **compare the stock price to the stock price** —
the alt's UP-token vs the *peer UP-tokens* — **not** the token vs the underlying coin spot. The fear is a
prediction-market event, so the reference is the other prediction-market prices.

## How it was tested
`experiment_token_fear.py` (reuses the `experiment_fear_dip` loader + `net_ev`). Causal, 30s decision grid,
windows synchronized across coins. Gate: alt `up_mid` drops ≥5¢/30s **while peers stay flat/up** (≥−2¢) and
the alt drops ≥5¢ **more** than peers (un-proportionate). Entry = `up_ask` (fade) or `down_ask` (follow), hold
to resolution, taker fee. n=497 fired (healthy). Bar = beat the same-side placebo (p<0.05) + Wilson-LB(win) >
breakeven + per-coin replication, net of fee.

## Verdict (n=497, both directions)
| direction | win% | net EV/$1 | residual | placebo | Wilson-LB vs breakeven |
|---|---|---|---|---|---|
| **FADE (buy Up)** — the thesis | 40.2% | −0.250 | −0.055 (all 6 coins −) | p=0.998 | 0.360 < 0.490 ❌ |
| **FOLLOW (buy Down)** — the flip | 59.8% | +0.0195 | **+0.055 (all 6 coins +)** | p=0.186 | 0.554 < 0.575 ❌ |

- **Fade is decisively wrong-signed.** The un-proportionate token dump is **informed, not fear** — the alt
  closes Down *more* than its discounted price implies. The peers staying flat means the move is
  *idiosyncratic to that alt*, and the token market is correctly front-running a real Down outcome.
- **Follow is a genuinely real signal** — positive residual on **all six coins** (the best cross-coin
  consistency we've measured), confirming the dump carries real bearish information.
- **…but it's fee-capped.** The Down-side ask (~0.56, ~2¢ over mid) + the ~3.5% taker fee eat the +0.055
  residual down to +0.0195 net, which **fails the placebo (p=0.186)** and sits **below breakeven** on the
  pooled set and every coin. Real information, priced + fee-capped → no deployable edge. The same wall
  favorite-tail / lead-lag / the B-filter all hit.

## Why parked (not dead, not deployed)
The mechanism the user intuited is **real** — an un-proportionate token dump is an informed bearish signal —
it's just **too small to clear the spread + fee** today. That's a different failure than "never real," so it's
archived here rather than in `dead_ends/`.

## Revisit if
- **Fees drop or spreads tighten** on the 5-min market (the residual is +0.055; today's ~3.5% fee + ~2¢ Down
  spread is what kills it — a materially cheaper venue could flip it positive).
- **A larger-residual subset survives OOS** — more-extreme dumps *might* carry a bigger residual that clears the
  fee. ⚠️ This is threshold-mining (the trap that killed favtail-adaptive / config_tod OOS) — only pursue with
  a *single pre-specified* threshold tested on *fresh* data, never an in-sample sweep.
- As a **weak Tier-3 pre-registration candidate**: lock the current gate (drop 5¢ / gap 5¢ / peer-tol 2¢,
  follow/buy-Down) and re-check on ≥2–4 weeks more data; promote only if it then clears placebo + Wilson.

Run: `python ideas_old/experiment_token_fear.py --follow` (or omit `--follow` for the dead fade).
Related: memory `reversion-fear-dip-idea`, `market-efficient-no-knowledge-edge`. The earlier token-**vs-spot**
variant (SMT-panic-fade) was killed first — see `reversion-fear-dip-idea`.

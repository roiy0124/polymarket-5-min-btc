# Open-imbalance overreaction fade — TESTED, DEAD (2026-06-26)

## Thesis (why it could work)
At each 5-min window OPEN the strike has *just* been set, so the first ~20s of price movement is the
speculative crowd taking positions with **no real information** — a 5-min Chainlink close cannot be
predicted from 20s of spot. If that early crowd OVERSHOOTS (e.g. bids the Up token to 0.62 on light flow),
the eventual outcome should correct it. So: at `time_left ≈ 280` (20s in), FADE the early skew — buy the
cheaper side — and hold to 0/1. This is the one moment where "the marginal trader is provably uninformed"
is a defensible claim, and it sidesteps the maker adverse-selection wall (it's a taker bet).

## Verdict: DEAD — the open price is already calibrated, no overshoot to fade.
Calibration probe at tl≈280 (n=4887, all 6 coins): bucketed early `up_mid` vs realized P(Up):

| early up_mid | mean price | realized P(Up) | resid |
|---|---:|---:|---:|
| 0.0–0.35 | 0.283 | 0.234 | −0.049 |
| 0.45–0.55 | 0.499 | 0.495 | −0.004 |
| 0.65–1.0 | 0.711 | 0.678 | −0.033 |

Slope of (realized−0.5) on (price−0.5) = **1.044 ≈ 1** (a fade needs slope < 1 = overshoot). If anything
the early price slightly UNDER-reacts (slope > 1 → momentum, not fade), and `corr(price, outcome)=+0.26`.

## Why it probably failed
The market is **efficient-on-knowledge even 20s in** ([[market-efficient-no-knowledge-edge]]): the open
price already prices whatever the first 20s of spot implies, and the crowd is not systematically
overshooting. The "uninformed open crowd" premise is wrong — there are enough informed/arbitrage
participants from the first seconds that the quote is calibrated. And at tl≈280 the price sits near 0.5,
where the taker fee `0.07·(1−p)` is largest (~3.5%), so even the marginal slope-1.04 under-reaction (a
momentum tilt, the opposite of the thesis) couldn't clear the fee.

## Revisit if
A fade only lives where price DECOUPLES from fundamentals — which this spot-settled 5-min token doesn't do
at 1/s. Only worth a second look with **sub-second** open-flow data showing a transient overshoot that
reverts within the window, AND a fee drop. Prior: low. No standalone script (one-off calibration probe).

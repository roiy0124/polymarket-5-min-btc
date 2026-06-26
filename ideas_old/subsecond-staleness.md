# Sub-second spot staleness (Binance burst vs token quote) — TESTED, real-at-mid but FEE-CAPPED (2026-06-26)

## Thesis (why it could work)
The token CLOB quote is maintained by bots polling ~1/s; Binance `@bookTicker` fires 50–85×/s. When Binance
makes a sharp **sub-second** move (a burst completing *between* two 1/s token snapshots), the token ask is
provably stale for a few hundred ms before the maker repriced. The project's prior lead-lag work
([[faster-feed-lag-is-real]]) measured the lag at **1/s sampling**, so it could only see the *average* lag —
it literally could not see the sub-second window where staleness is maximal. Claim: the *conditional*
sub-second lead (token mid hasn't moved yet, Binance just burst) is larger than the unconditional 1s lead,
and might clear the fee. Tested on `price_ticks` (Binance bookTicker, sub-second, ~18M rows / 60h on eth).

## Verdict: the sub-second lead is REAL at the mid, but the win-rate is BELOW breakeven → fee-capped, FAILS.
At tl≈45, bet the direction of the trailing-1.5s Binance burst, hold to 0/1 (n=995, coins with price_ticks):
- **signed residual vs the mid = +0.0256, cluster-CI [−0.005, +0.056], raw-p = 0.050** (borderline real —
  the burst predicts the outcome ~2.6pp beyond the token mid, i.e. an unpriced sub-second lead exists).
- BUT directional taker: win **56.6% < breakeven 57.3%** → net-EV CI [−0.13, +0.43] (skew +20, hugely
  noisy), Wilson-LB 0.535 < be 0.573, **deflated p = 0.976 → FAILS**. Large-burst subset (top 30%): residual
  +0.028 but n=299, CI even wider, also FAILS.

## Why it probably failed
Exactly the wall from [[faster-feed-lag-is-real]] and [[market-efficient-no-knowledge-edge]], now confirmed
at finer resolution: a faster feed IS worth money, but **the bet fires near p≈0.5 (tl≈45), where the taker
fee `0.07·(1−p)` ≈ 3.5% is largest**, and the spread compounds it. The gross sub-second residual (~2.6pp)
is real but smaller than the ~3–4pp fee+spread, so the win-rate lands just under breakeven. It is the same
"signal real at the mid, fee-capped" shape as [[reversion-fear-dip-idea]] (token-fear FOLLOW), only noisier
(raw-p 0.05 vs 0.008) because the near-0.5 binary bets are violently skewed.

## Revisit if
- **Fees drop materially** (the residual already clears a smaller cost), OR
- a way to harvest the lead at a LESS central price (the fee is smaller away from 0.5). I TESTED the obvious
  version — use the sub-second burst as a CONFIRMING micro-gate on the favorite-tail entry (ask 0.95+, fee
  ~0.2%): **it does not work** (confirm subset EV −0.0049 vs baseline −0.0062, still negative, cuts to 5
  losers). Reason: at ask 0.95+ the favorite's spot is already moving its way, so a confirming burst is
  redundant, and only 16% of favorites even have a clear burst at the instant. So the lead is real but has no
  low-fee harvest point on this product. Prior now: low. Params LOCKED; re-gate on fresh data if fees drop
  (price_ticks is only ~3-day retention, so n accrues slowly). One-off probes (no committed script).

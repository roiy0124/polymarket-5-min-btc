# Cross-window return momentum / serial outcome correlation — TESTED, DEAD (2026-06-26)

## Thesis (why it could work)
Short-horizon return autocorrelation is a documented effect, and consecutive 5-min windows even share a
boundary (window N's `final_binance` ≈ window N+1's `strike_binance`), giving a mechanical reason for serial
structure. If a window's realized direction predicts the NEXT window's outcome *beyond* what the next
window's open token price already reflects, that is a new, boundary-independent edge (sidesteps the
Chainlink-basis wall that kills the favorite-tail/settlement ideas).

## Verdict: DEAD — weak mean-reversion, already priced into the next open.
Consecutive-window pairs, all 6 coins (n=440–662 each):
- `corr(prev_return, next_outcome)` = **−0.014 to −0.039** (a faint MEAN-reversion: an up window slightly
  favors down next), consistent in sign but tiny.
- `corr(prev_return, RESIDUAL = next_outcome − next_open_mid)` = **−0.007 to −0.051** (sol the largest),
  noise-level and inconsistent across coins.

The serial structure that exists is weak AND already in the next window's open price (residual ≈ 0). At the
near-0.5 open prices where you'd trade it, the taker fee (~3.5%) dwarfs a sub-1% edge.

## Why it probably failed
The boundary-sharing momentum is real but mechanical and obvious, so the market prices it into the next
open immediately (efficient-on-knowledge, [[market-efficient-no-knowledge-edge]]). And trading it means
betting near p=0.5, the worst fee zone. Same wall, boundary-independent confirmation: even a structurally
*different* signal (cross-window, not within-window microstructure) is priced + fee-capped.

## Revisit if
A larger, sign-stable residual correlation emerges with more data (unlikely — it's already ~0), or fees
drop enough that a sub-1% edge near p=0.5 clears. Prior: very low. One-off probe; no committed script.

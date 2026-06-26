# Whale / large-print follow-through — TESTED, DEAD (2026-06-26)

## Thesis (why it could work)
Trade size is bimodal: a flood of tiny retail clicks and rare large prints. A single LARGE buy is
informed conviction, not noise. The flow research killed *average* flow (CTAP cross-token aggressor
imbalance has corr ~0 with the residual — priced), but **average flow ≠ big flow**: maybe the whale
prints carry information the small ones dilute. So: at `time_left ≈ 60`, take the largest BUY print on
each token in the trailing 45s; if the big Up-buy dwarfs the big Down-buy, bet Up (follow the whale),
hold to 0/1. Size-conditioning has never been tested here (`analysis/flow.py` only sums size, never
conditions on it).

## Verdict: DEAD — the whale's direction does NOT predict beyond the mid.
Probe at tl≈60 (n=4381 windows with a whale ≥$5, all 6 coins):
- whale-Up windows: P(Up) 0.553 vs mid 0.558 → resid **−0.0052**
- whale-Dn windows: P(Up) 0.405 vs mid 0.406 → resid **−0.0011**
- **signed residual (bet whale direction vs the mid) = −0.0020** (negative)
- `corr(whale_up, won) = +0.148` — positive only because whales buy the favorite, which the mid already prices.

## Why it probably failed
Same wall as CTAP and every flow factor: **the mid absorbs the large print as fast as the small ones**
(efficient-on-knowledge). The whale moves the book on arrival; by the next snapshot the mid already
reflects it, so conditioning on the whale's direction adds nothing over the mid (the residual is ~0,
slightly negative). The +0.148 raw correlation is the favorite-tail relationship in disguise (big buys
land on the likely winner), not incremental information. Size-conditioning didn't rescue flow — informed
or not, the print is priced the instant it lands.

## Revisit if
Only with **sub-second** data showing the whale's print leads the mid by a measurable lag the quote
hasn't closed (the same sub-second-staleness question as the spot lead-lag) — and even then the taker fee
near p=0.5 is the executioner. Prior: low. No standalone script (one-off probe).

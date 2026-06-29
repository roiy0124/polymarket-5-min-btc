# Favorite-longshot bias / full calibration curve — TESTED, NO BIAS (2026-06-26)

## Thesis (why it could work)
The favorite-longshot bias is one of the most documented inefficiencies in binary/betting markets:
longshots (low p) are systematically OVER-priced and favorites (high p) UNDER-priced. If this token market
has it, buying favorites would be +EV *beyond* breakeven. And critically, the taker fee `0.07·(1−p)` is
**tiny at high p** (0.2% at p=0.97) and huge near 0.5 — so even a small favorite under-pricing at high p
could clear the fee where a mid-price one couldn't. I had only ever looked at the 0.95+ tail; this maps the
FULL calibration curve at tl≈30 (both Up and Down sides as buyable positions, n=7974).

## Verdict: NO bias — the market is calibrated on the MID; buying the ASK costs the half-spread everywhere.
| ask band | n | mean ask | realized win | miscal (real−ask) | net EV/$1 |
|---|---:|---:|---:|---:|---:|
| 0.02–0.10 | 1756 | 0.041 | 0.027 | −0.013 | −0.46 |
| 0.30–0.50 | 693 | 0.395 | 0.372 | −0.023 | −0.11 |
| 0.70–0.90 | 927 | 0.803 | 0.796 | −0.007 | −0.022 |
| 0.95–0.98 | 519 | 0.960 | 0.958 | −0.003 | −0.006 |
| 0.98–1.00 | 1501 | 0.990 | 0.988 | −0.001 | −0.002 |

**Every band realizes slightly BELOW its ask** (the opposite of a favorite under-pricing), and the gap
shrinks to exactly the half-spread at the extremes (0.988 vs 0.990). Net EV is negative across the whole
curve. There is no band where realized win-rate beats ask + fee.

## Why it probably failed
The favorite-longshot bias comes from *uninformed/recreational* bettors who like longshots; this 5-min
crypto market is **arbitraged on the mid** (the token mid tracks the calibrated probability), so the only
cost is mechanical: the ASK sits a half-spread above the fair mid, and you pay the fee on top. There is no
behavioral mispricing to harvest — buying any band at the ask just pays spread + fee. (This also re-confirms
why the favorite-tail is breakeven, not +EV: at 0.98+ the spread+fee is tiny, so it's near-zero, not
positive.) The ONLY way to beat it is to find the rare subset where realized > ask+fee — which is exactly
what the over-round gate does (favorites that win MORE than priced when makers are calm), and essentially
nothing else does.

## Revisit if
A behavioral cohort (uninformed longshot buyers) ever shows up — undetectable on current data. Prior: very
low (the market is too efficient on the mid). One-off probe; no committed script.

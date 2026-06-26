# Dynamic loss-stop exit on the favorite-tail (over-round-widening trigger) — TESTED, HURTS (2026-06-26)

## Thesis (why it could work)
The favorite-tail's whole loss is the rare FLIP (−100%). The user's stated lever
([[strategy-preference-consistency]]) is a **loss-stop**: don't hold a losing favorite to 0, exit it early.
The over-round gate predicts flips at ENTRY; the over-round CHANGE should predict flips DURING the position.
So: enter the favorite at tl≈30; if by tl≈10 the over-round has WIDENED (makers turned nervous after you're
in), EXIT by selling the favorite at its bid (as a MAKER, no exit fee — per [[exit-execution-verdict]]);
else hold to 0/1. If the trigger catches flips early enough, it caps the −100% tail and lifts EV.

## The flip signal IS real (the diagnostic looked great):
| over-round change entry→tl10 | n | flip rate | favorite bid @ tl10 |
|---|---:|---:|---:|
| tightened / flat | 474 | ~3% | 0.94 |
| widened 2–5c | 39 | **20.5%** | 0.849 |
| widened >5c | 52 | 15.4% | 0.585 |

Widening 2–5c jumps the flip rate 6× (3%→20.5%) while the favorite still trades at 0.849 (savable).

## Verdict: the exit HURTS, significantly. HOLD beats every exit threshold.
| rule | EV/$1 | Δ vs hold (cluster-CI) |
|---|---:|---|
| HOLD baseline | −0.0244 | — |
| exit if widen ≥2c | −0.0456 | **−0.021 [−0.034, −0.009]** (CI excludes 0) |
| exit if widen ≥3c | −0.0485 | −0.024 [−0.036, −0.013] |
| exit if widen ≥5c | −0.0494 | −0.025 [−0.036, −0.015] |

## Why it probably failed (the durable lesson on loss-stops here)
A 20.5% flip rate is **not high enough** to justify exiting: the other **79.5% of stressed favorites
RECOVER to 1.0**. Exiting them at the depressed bid (~0.85, or 0.585 in the >5c bucket) locks a real loss on
the majority that would have won — and that cost overwhelms the savings on the 20% that flip. The market
**over-reacts intra-window** (the same "stress mostly reverts" force that made the reversion/fear ideas hard
from the other side): a favorite getting marked down mid-window is usually a temporary wobble, not a true
flip, so **holding through the stress is correct**. The −100% binary tail cannot be cheaply stopped because
no intra-position signal separates the recovering wobble from the genuine flip sharply enough (you'd need a
trigger with >~50% conditional flip rate; the best available is ~20%). This is the concrete reason the
user's favored loss-stop lever does not work on this product.

## Revisit if
A sharper intra-position flip trigger (>~50% conditional flip rate) is found — e.g. a sub-second spot cross
of the strike with seconds left. Prior: low (the tested over-round trigger is the most natural one and it's
far short). One-off probe; no committed script.

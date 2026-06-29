# Favorite persistence as a favorite-tail loser-cutter — TESTED, DEAD-CONFOUND (2026-06-26)

## Thesis (why it could work)
The favorite-tail dies only to FLIPS. A favorite that has led the *whole* window should be safer than one
that flipped to favorite recently (which is more likely to flip back). Define PERSISTENCE = the fraction of
the window's snapshots (time_left ≥ 30, i.e. open → decision) where the Binance-implied favorite matched the
current favorite. It looked like the low-Jaccard partner the [[additivity-overlap-lesson]] says is needed:
it separated winners/losers (W 0.775 vs L 0.736) AND had Jaccard ≈ 0.48 with the over-round gate (cuts
*different* losers), so stacking it on the over-round gate appeared to ~double the EV
(over_round-alone +0.0020 → stack +0.0039).

## Verdict: DEAD — persistence is a PROXY FOR THE FAVORITE ASK; it fails the decisive ask-control test.
Second-mind reviewed (agent ad34f249), which rebuilt it independently and ran the anti-confound test the
over-round card itself defines:
- **Joint logistic `won ~ ask + persist`: persist coef positive in only 74% of cluster-robust refits
  (permutation p=0.21).** The bar is >95% / p<0.05. The over-round gate on the IDENTICAL test scores
  **98% / p=0.003** (PASS) — so the test discriminates; persistence simply fails it.
- **Within-ask-bin the separation is SIGN-INCONSISTENT** (+0.044, −0.018, −0.009, +0.098 across four ask
  bins — two bins have persistence *higher* for losers). The pooled W>L gap is a between-bin artifact:
  higher-ask favorites both persist more AND win more. Control for the ask and the effect vanishes.
- The stack vs over-round-alone Δ = +0.0024, cluster-CI spans 0, **P(stack > over_round) = 0.64** (coin
  flip), and it cuts 7 incremental losers only by DISCARDING 47% of the over-round gate's winners (the
  loss-light win-rate trick). Through `stats.assess`: INSUFFICIENT (6 losers), CI spans 0, deflated p=0.98.

## Why it probably failed
A favorite that persisted the whole window is, by construction, one the spot stayed clearly on one side of —
which is exactly what makes its token ASK high (more certain). So persistence ⊂ the priced ask: the market
already charges for it. It is the same trap as the spot-margin gate ([[spot-margin-stack]]) but worse —
margin at least survived the ask-control (it was real-but-overlapping); persistence does NOT even survive it
(it IS the ask). The lesson sharpens: a low Jaccard with the over-round gate is necessary but NOT sufficient
— the partner must ALSO be independent of the favorite's own price (pass the joint ask-control), or it is
just the priced ask cutting losers the price already accounts for.

## Disposition / revisit
DEAD as an independent signal. The single **over-round gate** stays the robust primary (it passes
ask-control; persistence does not). Methodology note for the future: my first probe used ask up to 1.0 (not
the canonical [0.95,0.99)) and reported inflated n=1987/39 vs the canonical 859/31 — always use the LOCKED
favorite-tail definition. No revisit unless a persistence-like signal is constructed that is demonstrably
orthogonal to the ask. Params LOCKED. (One-off probe; no committed script.)

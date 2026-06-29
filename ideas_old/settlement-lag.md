# Settlement-convergence lag (buy the near-locked late winner) — TESTED, DEAD: basis-flip dominated (2026-06-26)

Script: `../experiment_settlement_lag.py` (kept — the flip-rate-bound test is reusable). Second-mind reviewed (agent abfc1a9a).

## Thesis (why it could work)
In the final seconds (time_left ≈ 5), when spot is CLEARLY past the strike (large Binance margin = the
outcome looks locked, spot can't cross back in 5s), the winning token still trades a few tenths below 1.0
(it hasn't fully converged). Buy that near-certain winner at its ask, hold to 0/1, collect the convergence
lag. The taker fee is tiny at ask≈0.99 (~0.1%), so a 0.3–0.6% lag clears it. Distinct mechanism from the
over-round gate (tl~30 maker confidence). It LOOKED like the session's best new edge: at margin≥3bp, n=936,
win 99.5%, net-EV **+0.0063, cluster-CI [+0.0010, +0.0106]** (the only candidate whose CI excluded 0), raw
one-sided p=0.011.

## Verdict: DEAD — a margin cherry-pick whose tail is the Binance/Chainlink settlement basis.
1. **Margin cherry-pick.** The UNGATED effect is NEGATIVE (−0.0015); the +0.0063 is entirely manufactured by
   the gate, and net-EV shrinks monotonically as margin tightens (0.0063→0.0010) — tightening removes flips
   but pushes ask→1 so there's nothing left to collect. The 3bp cell is the unique "just enough losers to be
   net-positive, not enough to bound the tail." Fails honest deflation: **deflated p = 0.89 at the correct
   N=200** (the experiment originally used a wrong n_trials=20 → 0.198; bug fixed).
2. **THE KILL — wrong oracle / settlement basis.** The favorite is picked on BINANCE but settles on
   CHAINLINK. An independent oracle (Pyth) disagrees with Binance on the favored side **2.79% of the time at
   the decision instant** (1.78% at margin≥5bp). The edge needs the true flip rate **< 1.24%** (= 1−ask). The
   real flip-proneness (~2.8%, confirmed by Pyth AND by Binance's own 3.59% final-vs-decision crossings) is
   **>2× the tolerance**. All 5 in-sample losers were already basis flips; the 0.53% in-sample rate is a lucky
   small-sample draw. **At the true flip rate, net-EV is NEGATIVE (−0.006 to −0.017); Kelly goes negative.**
3. **Thin depth.** Favorite best-ask depth median ~71 shares (~$70), 58% of windows <100 shares. A 0.3–0.6%
   edge on ~$50–70 of fillable size (before you walk the book to ~1.0 where the edge is gone) is not real,
   and a taker buy at tl=5 is operationally marginal.

## Why it probably failed (the durable lesson)
The convergence lag is REAL (the token does sit <1.0 when near-locked), but it lives exactly at the
boundary — and the boundary is precisely where the **Binance/Chainlink basis flips outcomes** (the
resolution-source caveat in CLAUDE.md). So the play is self-defeating: you're paid the lag for bearing the
basis-flip risk, and that risk (2.8%) is bigger than the lag (1.2% tolerance). It is the same wall as the
whole program, in its purest form: **Chainlink (the only thing that matters) is efficient, and our Binance
proxy is not the settlement oracle.** Pennies in front of the basis-flip steamroller.

## Attempted fix: DUAL-ORACLE agreement (Binance AND Pyth) — ALSO DEAD (the fix targets the wrong oracle)
Tried requiring Binance AND Pyth to agree on the favored side, to remove the basis-flip windows. It looked
better: margin≥3bp & Pyth-agree → n=907, 4 losers, net-EV +0.0070, **cluster-CI [+0.0021,+0.0109] excludes 0**,
raw p=0.004, 5/6 coins positive, flip Wilson-UB 0.0113 now < the 0.0121 need. But the second-mind (agent
a3f117a2) killed it: **the fix removes the wrong losers.** Decomposing the 5 single-oracle losers, the
Pyth-agreement filter drops only 1 (the Pyth-disagree one) and KEEPS 4 — windows where Binance AND Pyth both
agreed the favorite wins but **CHAINLINK** (a THIRD oracle) flipped it. The losses live in Chainlink, which
neither proxy sees. Flip-rate improvement is +0.0009 at 3bp (one window), −0.0001 at 5bp. It's a single-point
cherry-pick (only 3bp passes, by 0.0008, broken by +1 loser), fails deflation (p=0.56 at N=200), depth still
~$71 (~$0.49 expected profit/window). Adding a second PROXY oracle cannot fix a tail that lives in the
settlement oracle itself.

## Revisit if
- A **Chainlink price adapter** is added to `feeds.py` (the CLAUDE.md drop-in): selecting the favorite on the
  ACTUAL settlement oracle is the ONLY thing that removes the basis-flip tail (a second proxy like Pyth does
  not — the losers are Pyth-agreed Chainlink flips). THEN the convergence lag, if it survives on Chainlink
  margins, could be real. This is the single concrete unlock for this idea family. Params LOCKED; re-gate at
  ≥30 gated losers. See memory `settlement-basis-wall`.

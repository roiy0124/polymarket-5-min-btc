# ideas_old/ — explored & parked ideas (preserved, not thrown away)

Ideas we **tested to a conclusion** and shelved — kept here with their full verdict and the
code that produced it, so we never re-run them from scratch or forget *why* they were parked.

How this differs from the neighbours:
- **`../IDEAS.md`** — the *forward* backlog (ideas to try). This folder is the *backward* archive (ideas already tried).
- **`../dead_ends/`** — proven-**dead** experiment code (no signal / overfit artifacts).
- **`ideas_old/`** — ideas where there *was* something real but it didn't reach the deployment bar (usually fee/spread-capped). Worth revisiting if conditions change (fees drop, spreads tighten, more data).
- **`../winning_strategies/`** — the active roster (Tier 1–3).

Each idea = one `.md` (thesis + verdict + revisit-conditions) + its experiment script. Scripts add a
`sys.path` shim to the repo root so they still run in place: `python ideas_old/<script>.py`.

## Index
| Idea | Verdict | Revisit if |
|---|---|---|
| [Fear stock-sell (stock-vs-stock)](fear-stock-sell.md) — `experiment_token_fear.py` | Fade DEAD (dump is informed, not fear); FOLLOW real all-coin residual +0.055 but **fee-capped** (net +0.02, placebo p=0.19, Wilson<be) | fees drop / spreads tighten / a larger-residual subset survives OOS |

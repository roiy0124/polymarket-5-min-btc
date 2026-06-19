# round_charts — per-round price graphs from the website

Goal: capture **one image per resolved 5-minute round** showing that round's price
graph as Polymarket presents it — a visual ground-truth to eyeball against the data
we capture in `btc_updown.db`.

Status: **pending deep research** (task `wrftip1ff`) on the most reliable way to do
this. Two candidate approaches under evaluation:

1. **Fetch the chart's underlying data and render it ourselves** — Polymarket's CLOB
   `prices-history` endpoint feeds the website chart; pulling that JSON for the
   round's two token IDs and plotting it (matplotlib) is deterministic, fast, and
   needs no browser. Most likely the reliable choice.
2. **Headless-browser screenshot** (Playwright) of `polymarket.com/event/<slug>` —
   the literal website chart, but subject to bot-protection, render-timing, and
   stability concerns.

The collector already knows each round's `slug` (= window-start unix ts),
`conditionId`, and the two `clobTokenIds`, and it knows exactly when a round ends
(`window_start + 300`), so capture can be triggered precisely at round close.

Planned layout (finalized after research): one image per round, named by
window-start timestamp, likely split `up/` vs `down/` or kept per-round combined.

Implementation will follow the research findings (favouring the most reliable +
faithful approach), with ToS/rate-limit caveats respected. Images here are
git-ignored (regenerable); this README is tracked.

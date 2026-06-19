# Analysis Strategy — how we hunt for (real) edges

The evolving playbook for finding a statistically-real edge in the BTC up/down
5-minute markets, and the tools that implement it. Companion to `ANALYSIS.md`
(theory blueprint) and `DATA-ANALYSIS-TOOLKIT.md` (reliability methods). Read this
first when resuming analysis.

## North star
Find conditions under which a token is **mispriced**, confirm the edge is **real**
(survives out-of-sample + fills + fees), then size it safely. The hard part is not
finding patterns — it's **not fooling ourselves**. Every number is guilty until
proven out-of-sample.

## The framing that matters
A token price *is* a probability. The edge is where the **true probability differs
from the token price**. Two complementary views of "true probability":

1. **Realized frequency** — does a token at price p actually win p% of the time?
   (calibration). Deviations = mispricing.
2. **Fundamental fair value** — the digital-option price
   `fair P(Up) = Φ((S − K) / (σ·√T))`, where `S`=current BTC, `K`=strike (BTC at
   window start), `T`=time-left, `σ`=short-horizon vol. The edge is the **token
   price lagging this fair value** (the market underreacts to BTC moves).

**Key lesson (learned the hard way):** the token PRICE ALONE IS NOT THE STATE. The
same 5¢ means a live bet (4 min left, BTC near strike) or a dead bet (4 sec left,
BTC far). Always condition on **time-left** and **BTC gap-to-strike**, never price
alone. The fair-value formula does this automatically (a 4-sec/far bet → fair P≈0).

The four things that define a trade: **time-left (T), BTC gap (S−K), the frequency
(realized win-rate we test against), and the margin (fair − market = the edge).**

## The workflow (explore → confirm → trade)
1. **EXPLORE visually** (hypothesis generation) — `exit_maps` to SEE structure.
2. **SPOT a region** that looks like an edge (a price/time band where the picture
   is favorable).
3. **QUANTIFY that exact slice rigorously** — `calibration_test` / `fair_vs_market`:
   one obs/window, CIs, multiple-testing correction, out-of-sample, horizon checks.
4. **FILL-AWARE BACKTEST** — `backtest` (+ `flow` toxicity filter) with the
   RiskAverse fill model + real fees. Converts a *forecasting* edge into a
   *tradeable* one (adverse selection always shrinks it).
5. **SIZE** — fractional Kelly on the deflated edge; respect the negative skew.

## The tools (`analysis/`)
| Module | Question it answers | Run |
|--------|--------------------|-----|
| `exit_maps.py` | For each entry price/side, when do I enter and what's the best exit? (visual) | `python -m analysis.exit_maps` |
| `calibrate.py` | Is the Up price calibrated to outcomes overall? | `python -m analysis.calibrate` |
| `calibration_test.py` | RIGOROUS: do cheap tokens win more than priced? (CIs, FDR, OOS) | `python -m analysis.calibration_test` |
| `fair_vs_market.py` | Does BTC-implied fair value beat the token price? (underreaction) | `python -m analysis.fair_vs_market` |
| `fairvalue.py` | Fair P(Up) per window + Brier vs market | `python -m analysis.fairvalue` |
| `reversion.py` | Unconditional dip→recover screen | `python -m analysis.reversion` |
| `combo_ev.py` | Combo EV sweep (USE WITH CARE — multiple-testing trap) | `python -m analysis.combo_ev` |
| `flow.py` | Toxic vs panic flow conditional reversion | `python -m analysis.flow` |
| `backtest.py` | Replay a rule via the real fill engine (+ `--max-toxicity`) | `python -m analysis.backtest` |
| `exit_maps.py` | Per-entry-price exit-opportunity scatter maps (settlement-aware, 0.4s latency) | `python -m analysis.exit_maps` |
| `data_quality.py` | Liveness / coverage / gaps / WS-freeze audit | `python -m analysis.data_quality` |
| `panel.py` | Shared per-window feature/outcome table | (imported) |

## The exit-opportunity maps (the visual core)
`exit_maps/up/entry_NNc.png` and `exit_maps/down/entry_NNc.png` (99 each).
Generate: `python -m analysis.exit_maps` (read-only — no need to stop the collectors).
- **x** = entry time in the 5-min round (the first moment that window's token hit
  price bucket `z`).
- **y** = realized **exit value**:
  - the best price you could have **sold** at after entry (highest mid), **only if
    it rose ≥ `SELL_THRESHOLD` (1¢) above entry** — a real sellable bounce; otherwise
  - the **resolution value: 0 if that side lost (complete loss), 1 if it won**.
  So a "couldn't sell" loss sits on the **floor at 0**, a held win at the **top (1.0)**,
  and genuine bounces show their height. (Earlier versions left no-bounce dots at the
  entry line, which hid the losses — fixed.)
- **execution latency**: the exit search starts `EXEC_DELAY_SEC` (**0.4s**) after
  entry, so you never "sell" into price action a real (latent) system couldn't react to.
- **binning**: floor into uniform 1¢ buckets `[c, c+1)` — NOT `round()`, whose
  banker's rounding left odd-cent charts artificially empty.
- **color** = window outcome: green = resolved Up, red = resolved Down. (So on the
  DOWN chart, red dots are the Down-token winners → they rise to ~1.0.)
- **lines**: dashed at y=z (entry), dotted at y=2z.

**Best buy-window overlay** (added): each chart shades the contiguous **entry-time
window (≥30s)** that buying at that price wins most *consistently*, with a line at
the expected exit price and a left-side label `BUY t1-t2 min · win % · EV %`. The
window is chosen by the **Wilson lower bound** of the win-rate (consistency we can
trust — rewards a high rate AND enough samples), then ROI, then width. A "win" =
exit value above the entry price. Tunables: `BUY_WIN_MIN_WIDTH`, `BUY_WIN_MIN_DOTS`.

**How to read them:**
- A **floor of dots at 0** → complete losses (entered, never got a sellable bounce,
  resolved against you). This is the honest downside.
- Dots reaching well above z → a sellable bounce existed (margin = y − z).
- **Right edge dropping to 0** → late entries (little time left) can't bounce — the
  time-left wall.
- Find a **band** (price × entry-time) where dots reliably clear a target → that's
  a candidate rule to quantify in step 3.
- Tunables at the top of `exit_maps.py`: `SELL_THRESHOLD` (min bounce to count as a
  sellable exit) and `EXEC_DELAY_SEC` (signal→execution latency).

## Per-round charts (ground-truth viewer) — `round_charts/`
`chart_capture.py` (a supervised service; backfill with `python chart_capture.py --once`)
draws one chart per resolved round from the DB: Up/Down token lines + the **BTC price
and target/strike on a second axis** + Polymarket's official price dots (live rounds)
as a ground-truth overlay. Lets you eyeball each round and confirm BTC crossing the
target drives the odds.

## The operator menu — `python menu.py`
A numbered control menu wrapping everything (inspect, generate maps/charts, run the
analyses, paper-trade, start/stop the collectors). The easiest way to drive the project.

## Rigor rules (non-negotiable)
- **One observation per window** — windows are independent 5-min markets; pooling
  per-second snapshots fakes significance via autocorrelation.
- **Confidence intervals, not point estimates** — Wilson for rates, bootstrap
  (resample windows) for means. A CI that includes 0 = not proven.
- **Multiple-testing correction** — count every combo/bucket tried; Benjamini-
  Hochberg / deflated Sharpe. The best of N is luck by default.
- **Out-of-sample + robustness** — split by time; vary the horizon. A real edge
  replicates; a one-cell wonder is overfit.
- **Martingale ceiling** — a price is a bounded martingale, so P(reach 2z | z) ≤
  z/2z = 50%. Any "doubles 89% of the time" is a measurement artifact (fills you'd
  never get / hidden momentum / tiny n), not an edge.
- **Mid ≠ fill** — every screen here uses mids and is OPTIMISTIC. Adverse selection
  (you fill as it heads against you) only lowers EV. Nothing is tradeable until the
  fill-aware backtest confirms it.

## Findings so far (as of ~93–98 settled windows — all PROVISIONAL)
- Market is roughly calibrated overall.
- **Longshot hint**: cheaper tokens at 0.10–0.20 won ~43% vs ~15% priced (one
  FDR-significant bin) — but pooled edge CI includes 0 and it doesn't replicate.
  Not proven.
- **Underreaction (most promising)**: BTC-implied fair value beats the token price
  on Brier (0.237 → 0.232; blend 0.228 best), corr(fair−market, residual)=+0.20 —
  directionally supports "trade toward fair value," but CIs include 0. Not proven.
- **The `combo_ev` +1.4 EV result was an ARTIFACT** (mid-based, 168 combos, tiny
  n) — the canonical example of why the rigor above exists.
- Verdict: no established edge yet; need far more windows (a day = 288). The
  collector now runs reliably; re-run the tests as data grows.

## Next steps
1. Browse `exit_maps`, mark promising price×time bands.
2. Quantify those bands with `calibration_test` / `fair_vs_market` as N grows.
3. Upgrade σ (longer BTC history / realized kernel) to sharpen fair value.
4. Fill-aware backtest of the survivors; then fractional-Kelly sizing.

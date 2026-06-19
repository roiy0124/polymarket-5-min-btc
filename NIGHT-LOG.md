# Night Log — 2026-06-19 (morning follow-up)

Everything done overnight while you slept, per the goal: finish the research needed
for reliable results, and build the execution tooling (limit buys, cancel, fills
listener, auto-sell-on-fill) — all **paper-safe**. Read this top-to-bottom for the
full picture; it's all committed.

## TL;DR
- **Collectors now run until interrupted.** Root cause of the auto-stop fixed
  (unprotected loop line) + a **supervisor** that auto-restarts anything that dies.
- **4 of 5 research passes done & written up**; the 5th (Polymarket order
  execution) was still running at log time — the live trading path is intentionally
  left **disabled** until it lands and I verify the recipe.
- **Execution engine built and verified in paper mode**: resting limit BUYs, cancel,
  fills listener, auto-place SELL on fill. **Nothing real was traded.**
- **Analysis layer built**: calibration, mean-reversion screen, a real **backtest
  harness**, and a **fair-value vs market** head-to-head — your "compare both" idea
  is now runnable.
- **Honest early signal (tiny sample, NOT significant):** the market looks fairly
  efficient short-horizon and the naive buy-the-dip rule loses once you model fills.
  This *sharpens* the plan rather than killing it.

## Data status (at log time)
- `snapshots` 11,340 · `windows` 26 (24 settled) · `book_events` 633k · `trades`
  10.7k · `btc_ticks` 535k · DB 661 MB (auto-retention will plateau it).
- Live dashboard: **http://127.0.0.1:8765** (supervised, auto-restarts).

## Processes (supervised tree)
`supervisor.py` → `collector.py` + `ws_collector.py` + `viewer.py`. Auto-restart
with backoff. **Stop everything** with: create a file named `STOP` in the project
folder, or `Stop-Process` the supervisor. Cleaned up duplicate/orphan processes.

## Research completed (cited, verified, committed)
1. **Data-collection reliability** → memory `btc-updown-data-reliability`. (WS
   primary + REST fallback; silent-freeze bug; Chainlink gated; queue position
   unobservable.)
2. **Statistical analysis methodology** → `ANALYSIS.md`. (Digital-option fair value,
   OFI/microprice/imbalance, modeled fills, calibration; coefficients don't transfer.)
3. **Your mean-reversion idea, pressure-tested** → `STRATEGY-MEAN-REVERSION.md`.
   (Real liquidity-provision reversal mechanism, BUT short-horizon efficiency +
   adverse-selection headwinds; decisive variable = filtering toxic vs panic flow;
   measure reversion **conditional on a fill**, not unconditional.)
4. **Data-analysis toolkit for reliable results** → `DATA-ANALYSIS-TOOLKIT.md`.
   (Track N trials; t>3 hurdle; Deflated Sharpe / PBO; TimeSeriesSplit+gap / CPCV;
   robust SEs; block bootstrap; calibration; honest end-to-end checklist.)
5. **Polymarket order execution** → **DONE** → `EXECUTION.md` + `LiveBroker`.
   Verified recipe (py-clob-client GTC limit / FOK / cancel / user-channel fills).
   ⚠️ **Critical gotcha**: only a plain **EOA (signature_type=0)** works — a
   website/proxy (POLY_1271) wallet fails HTTP 400. Auto-sell must gate on
   **CONFIRMED**. Allowances/fees still to verify before live.

## Reliability fixes
- `collector.py`: per-tick DB writes + settlement wrapped in try/except — a
  transient SQLite lock / network blip now logs and continues instead of killing it.
- `supervisor.py`: the real "run until interrupted" guarantee (auto-restart).

## Execution engine (paper-safe) — `exec_engine/` + `paper_trade.py`
- `model.py / config.py / broker.py / order_manager.py` — orders, safety limits,
  `PaperBroker` (RiskAverse queue fills + PnL), `LiveBroker` (gated stub), and
  **auto-place-sell-on-fill** (partial-aware).
- `selftest.py` — **PASSES** (round-trip PnL + guardrails).
- `user_stream.py` — authenticated user-channel fill/order listener (live path).
- `paper_trade.py` — drives the engine off the **real live trade stream**; verified
  end-to-end (placed a sim BUY, filled from a live taker-sell, auto-sold).
- **Safety**: paper by default; live double-gated (`SafetyConfig(live=True)` + creds)
  and the order calls stay disabled until the execution recipe is verified.

## Analysis layer — `analysis/`
- `panel.py` — per-window feature/outcome table.
- `calibrate.py` — is the Up price calibrated? (`python -m analysis.calibrate`)
- `reversion.py` — unconditional dip→recover screen of your idea.
- `backtest.py` — replays the mean-reversion rule over all windows via the *same*
  fill engine the bot uses. (`python -m analysis.backtest --entry 0.22 --exit 0.33`)
- `fairvalue.py` — digital-option P(Up) vs market, head-to-head Brier.

### Early results (⚠️ tiny sample — directional only, not significant)
- **Calibration** (22 windows): market roughly tracks outcomes; Brier ≈ 0.21.
- **Reversion screen** (0.25→0.33): 3/5 recovered = 60%, **below** the 75.8%
  break-even → naive EV negative.
- **Backtest** (0.22→0.33): entries fill ~75% but **exits rarely fill before the
  close**, so positions carry to settlement and often resolve to 0 → net negative.
  This is exactly the adverse-selection failure the research predicted.
- **Fair-value vs market**: both beat the base-rate floor; **market price predicts
  slightly better** than the naive model (Brier 0.215 vs 0.226). Market ≈ efficient.

**Interpretation:** don't deploy the naive buy-the-dip rule. The edge — if any —
lives in (a) filtering *non-toxic* (panic) flow, and (b) measuring reversion
*conditional on a fill*. Both are buildable on the data we now capture.

## What's still open
- **All 5 night tasks are DONE.** The only remaining items are *your* pre-live
  verifications (not codeable without your account): set USDC+CTF allowances,
  confirm the real fee, and fund a **plain EOA** (not the website proxy wallet).
- The live path is wired but **untested without keys** — paper-trade the exact
  rule first, then enable `SafetyConfig(live=True)` with EOA creds.

## Recommended next steps (for you)
1. Let it keep collecting — significance needs hundreds of windows (a day = 288).
2. When ready to analyse for real, `pip install -r requirements-analysis.txt` and
   apply the toolkit discipline (walk-forward, count trials, deflated Sharpe).
3. Build the **toxic-flow filter** (trade-sign imbalance / VPIN) and re-run the
   backtest **conditional on fills** — that's the make-or-break test for your idea.
4. Decide on the live path only after a rule survives the honest backtest.

## All commits tonight
```
093ea22 fair-value module + market head-to-head (Brier)
8dd6f77 backtest harness (PaperBroker fill engine)
06bdc9c EXECUTION.md (design + safety; live recipe pending)
da1e544 analysis scaffold (panel + calibration + reversion)
117b501 user-channel fill listener + live paper-trading harness
24dea59 paper-safe execution engine core
dd42061 DATA-ANALYSIS-TOOLKIT.md
a586436 crash-proof collector loop + supervisor
400ef03 live viewer dashboard + mean-reversion assessment
6807865 ANALYSIS.md methodology blueprint
16ebe88 hybrid collector (WS + REST)
```

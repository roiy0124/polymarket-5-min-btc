# execution/ — the gated executors (NEVER ARMED)

Trading scaffolding built ahead of need and **kept gated**: no candidate ever cleared the validation bar
([`../POSTMORTEM.md`](../POSTMORTEM.md)), so nothing here has ever traded real money. Kept because the
order-management plumbing is sound and reusable if a future edge (on any venue) clears the gate.

| File | Role |
|---|---|
| `live_runner.py` | Phase-3 live executor on the CLOB V2 API — **hard-gated**, requires an explicit arming file + funded EOA; see `../docs/EXECUTION.md` |
| `paper_trade.py` | Manual paper-trade ledger CLI |
| `phase2.py` | Phase-2 paper executor (passive resting-limit strategy — strategy proven dead) |
| `phase2_nested.py` | Nested 24/16/8 gap→time paper executor (strategy proven ≈breakeven, net-negative after fees) |

The shared broker/order-manager/strategy-runner package lives in [`../exec_engine/`](../exec_engine/)
(`phase2_selftest.py`/`selftest.py` inside it exercise the plumbing without touching a market).
Launch via `../menu.py` (options 12+) or directly: `python execution/<script>.py`.

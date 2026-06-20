"""Summarize the Phase-2 paper ledger (paper_trades.csv).

The honest scoreboard: did the signals actually pay like Phase-1 predicted once
real (simulated) fills and adverse selection are in the picture? Read-only.

    python -m analysis.paper_ledger            # all signals
    python -m analysis.paper_ledger --min-n 10 # only signals with >=10 attempts

Metrics, per signal (side / entry / sell) and overall:
  attempts   how many windows armed this signal
  fill%      of attempts, how often the BUY actually filled
  win%       of FILLED legs, how often the leg ended positive (sold at T, or held
             a winning settlement)
  EVpred     Phase-1 predicted EV per $1 staked (the mid-price estimate)
  EVfill     REALIZED EV per $1, counting only filled legs  -> compare to EVpred;
             the gap is the adverse-selection cost the mid-price couldn't see
  EVatt      REALIZED EV per $1 of *intended* stake across ALL attempts -> folds in
             the fill rate, so a great-but-rarely-fills signal is penalized here

Small samples are noisy: a '*' marks signals with < 10 attempts. Treat their EVs as
provisional, not proof.
"""

import os
import csv
import argparse
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(HERE, "paper_trades.csv")
SMALL_N = 10


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _bought(r):
    """Filled BUY shares. Prefer the logged value; fall back (older rows) to a
    full-fill assumption when buy_filled is set."""
    if r.get("bought") not in (None, ""):
        return _f(r["bought"])
    return _f(r["shares"]) if _f(r["buy_filled"]) >= 1 else 0.0


def _stats(rows):
    """Aggregate a list of ledger rows into one metrics dict."""
    n = len(rows)
    filled = sum(1 for r in rows if _f(r["buy_filled"]) >= 1)
    sold = sum(1 for r in rows if _f(r["sell_filled"]) >= 1)
    pnl = sum(_f(r["realized_pnl"]) for r in rows)
    wins = sum(1 for r in rows if _f(r["buy_filled"]) >= 1 and _f(r["realized_pnl"]) > 1e-9)
    stake_fill = sum(_bought(r) * _f(r["entry_z"]) for r in rows)
    stake_att = sum(_f(r["shares"]) * _f(r["entry_z"]) for r in rows)
    ev_pred = (sum(_f(r["ev_predicted"]) for r in rows) / n) if n else None
    return {
        "n": n, "filled": filled, "sold": sold, "pnl": pnl, "wins": wins,
        "fill_rate": (filled / n) if n else None,
        "win_rate": (wins / filled) if filled else None,
        "ev_pred": ev_pred,
        "ev_fill": (pnl / stake_fill) if stake_fill > 1e-9 else None,
        "ev_att": (pnl / stake_att) if stake_att > 1e-9 else None,
    }


def _pct(x):
    return f"{x*100:>3.0f}%" if x is not None else "   -"


def _ev(x):
    return f"{x:>+6.2f}" if x is not None else "     -"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=LEDGER)
    ap.add_argument("--min-n", type=int, default=1, dest="min_n",
                    help="only show signals with at least this many attempts")
    args = ap.parse_args()

    if not os.path.exists(args.ledger) or os.path.getsize(args.ledger) == 0:
        print(f"no paper ledger yet at {args.ledger}")
        print("  -> run the Phase-2 paper executor (menu 12) and let it settle some rounds.")
        return
    with open(args.ledger, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("ledger is empty (header only) — no settled legs yet.")
        return

    overall = _stats(rows)
    print("=" * 78)
    print(f"PAPER LEDGER  |  {overall['n']} legs settled across "
          f"{len({r['window_start'] for r in rows})} windows  |  {args.ledger}")
    print("=" * 78)
    print(f"  filled {overall['filled']}/{overall['n']} ({_pct(overall['fill_rate'])})   "
          f"sold {overall['sold']}   total pnl {overall['pnl']:+.3f}")
    gap = (overall["ev_fill"] - overall["ev_pred"]) if (
        overall["ev_fill"] is not None and overall["ev_pred"] is not None) else None
    print(f"  EV/$1  predicted {_ev(overall['ev_pred'])}   realized-on-fill "
          f"{_ev(overall['ev_fill'])}   per-attempt {_ev(overall['ev_att'])}")
    if gap is not None:
        verdict = ("realized BEATS predicted" if gap > 0.05 else
                   "realized BELOW predicted (adverse selection)" if gap < -0.05 else
                   "realized ~ predicted")
        print(f"  adverse-selection gap (realized-on-fill - predicted): {gap:+.2f}  -> {verdict}")

    # per-signal
    groups = defaultdict(list)
    for r in rows:
        groups[(r["side"], r["entry_z"], r["sell_T"])].append(r)
    table = []
    for (side, entry, sell), rs in groups.items():
        st = _stats(rs)
        if st["n"] >= args.min_n:
            table.append((side, entry, sell, st))
    table.sort(key=lambda t: (-t[3]["n"], -t[3]["pnl"]))    # most-tested, then most pnl

    print("\n  per signal (most-tested first; * = < %d attempts, noisy):" % SMALL_N)
    print(f"  {'side':>4} {'entry':>5} {'sell':>5} {'n':>4} {'fill':>5} {'win':>5} "
          f"{'pnl':>8} {'EVpred':>7} {'EVfill':>7} {'EVatt':>7}")
    for side, entry, sell, st in table:
        flag = "*" if st["n"] < SMALL_N else " "
        print(f"  {side:>4} {_f(entry):>5.2f} {_f(sell):>5.2f} {st['n']:>3}{flag} "
              f"{_pct(st['fill_rate'])} {_pct(st['win_rate'])} {st['pnl']:>+8.2f} "
              f"{_ev(st['ev_pred'])} {_ev(st['ev_fill'])} {_ev(st['ev_att'])}")
    if not table:
        print(f"  (no signal has >= {args.min_n} attempts yet)")
    print("\n  EVfill is the apples-to-apples check vs EVpred; EVatt folds in fill rate.")
    print("  Small n = provisional. Let many rounds accumulate before trusting any line.")


if __name__ == "__main__":
    main()

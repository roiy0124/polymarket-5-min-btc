"""Per-window winner-vs-loser feature analysis (experiment, not in the menu).

The last signal-side idea: not WHICH config, but WHICH windows to sit out. Trade a
fixed config walk-forward (out-of-sample), and for every FILLED leg tag its window
with features measured AT ENTRY -- flow toxicity, pre-entry volume, spread, BTC
move, hour-of-day -- then bucket and ask: does any feature separate the winning
fills from the losing ones? If yes -> a real "don't trade this window" gate. If no
feature splits them, the edge doesn't survive realistic fills.

    python experiment_window_features.py

Reads all merged data. Fixed config default = the least-bad fixed config (24h/0.5/
0.2). Stdlib + the project's own modules. HONEST CAVEAT: ~2 days of data, fills are
correlated within windows, and trying many feature cuts is multiple-comparisons --
a split here is a hypothesis to confirm on more data, not proof.
"""

import os
import time
import argparse
import statistics

from experiment_walkforward import open_merged, generate_signals, replay_leg
from analysis.flow import flow_imbalance
from exec_engine.config import SafetyConfig

WINDOW = 300.0


def window_feats(conn, ws, placement_ts):
    """Spread (latest), BTC range so far, signed BTC move so far -- all up to entry."""
    snaps = conn.execute(
        "SELECT up_spread, down_spread, btc_binance FROM snapshots WHERE window_start=? "
        "AND ts<=? AND up_mid IS NOT NULL ORDER BY ts", (ws, placement_ts)).fetchall()
    if not snaps:
        return None
    spread = ((snaps[-1][0] or 0) + (snaps[-1][1] or 0)) / 2
    btcs = [r[2] for r in snaps if r[2]]
    btc_rng = (max(btcs) - min(btcs)) if len(btcs) > 1 else 0.0
    btc_move = (btcs[-1] - btcs[0]) if len(btcs) > 1 else 0.0
    return spread, btc_rng, btc_move


def bucketize(name, data, bins, getter):
    """data = list of dicts; bins = list of (label, lo, hi); getter(d)->value.
    Print win% / mean-pnl / n per bin."""
    print(f"\n  -- {name} --")
    print(f"     {'bucket':>14} {'n':>5} {'fills_win%':>10} {'mean_pnl':>9} {'EV/fill':>8}")
    for label, lo, hi in bins:
        sel = [d for d in data if getter(d) is not None and lo <= getter(d) < hi]
        n = len(sel)
        if n == 0:
            print(f"     {label:>14} {0:>5}")
            continue
        wins = sum(1 for d in sel if d["pnl"] > 1e-9)
        pnl = sum(d["pnl"] for d in sel)
        stake = sum(d["stake"] for d in sel)
        print(f"     {label:>14} {n:>5} {wins/n:>9.0%} {pnl/n:>+9.2f} "
              f"{(pnl/stake if stake else 0):>+8.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=float, default=24.0)
    ap.add_argument("--min-frac", type=float, default=0.50, dest="min_frac")
    ap.add_argument("--min-roi", type=float, default=0.20, dest="min_roi")
    ap.add_argument("--min-ev", type=float, default=0.05, dest="min_ev")
    ap.add_argument("--refresh-min", type=float, default=30.0, dest="refresh_min")
    ap.add_argument("--flow-lookback", type=float, default=60.0, dest="flow_lb")
    args = ap.parse_args()
    cfg = {"min_win": 0.70, "min_roi": args.min_roi, "min_dots": 8,
           "min_frac": args.min_frac, "min_ev": args.min_ev, "min_entry": 0.10,
           "usd": 2.0, "alpha": 0.05, "power": 0.80}

    conn, dbs = open_merged()
    from analysis.signals import load
    windows = load(conn)
    tokens = {ws: (tu, td) for ws, tu, td in conn.execute(
        "SELECT window_start, token_up, token_down FROM windows WHERE token_up IS NOT NULL")}
    outcomes = {w["ws"]: w["outcome"] for w in windows}
    all_ws = sorted(w["ws"] for w in windows)
    t_end = all_ws[-1] + WINDOW
    t_start = all_ws[0] + 24 * 3600     # need 24h history before first trade
    refresh = args.refresh_min * 60.0
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)
    print(f"data: {len(dbs)} db(s), fixed config lookback={args.lookback:g}h "
          f"frac={args.min_frac} roi={args.min_roi}; trading {(t_end-t_start)/3600:.0f}h")

    legs = []
    T = t_start
    while T < t_end:
        past = [w for w in windows if w["ws"] + WINDOW <= T]
        cuts = [(f"{args.lookback:g}h", T - args.lookback * 3600)]
        sigs = generate_signals(past, cuts, cfg) if past else []
        for ws in [w for w in all_ws if T <= w < T + refresh and w + WINDOW <= t_end]:
            outcome = outcomes.get(ws)
            if outcome not in ("Up", "Down"):
                continue
            tu, td = tokens.get(ws, (None, None))
            for s in sigs:
                token = tu if s["side"] == "up" else td
                if not token:
                    continue
                r = replay_leg(conn, ws, token, s["side"], s, outcome, scfg)
                if not r or not r[0]:        # only filled legs have an outcome
                    continue
                placement = ws + s["t1"] * 60.0
                imb, vol = flow_imbalance(conn, token, placement - args.flow_lb, placement)
                wf = window_feats(conn, ws, placement)
                if wf is None:
                    continue
                spread, btc_rng, btc_move = wf
                legs.append({"pnl": r[1], "stake": s["shares"] * s["entry"],
                             "tox": abs(imb) if imb is not None else None,
                             "imb": imb, "vol": vol, "spread": spread,
                             "btc_rng": btc_rng, "btc_absmove": abs(btc_move),
                             "hour": time.localtime(placement).tm_hour,
                             "side": s["side"]})
        T += refresh

    n = len(legs)
    if n == 0:
        print("no filled legs.")
        return
    wins = sum(1 for d in legs if d["pnl"] > 1e-9)
    pnl = sum(d["pnl"] for d in legs)
    print(f"\nFILLED legs: {n}  overall win {wins/n:.0%}  total pnl {pnl:+.1f}  "
          f"(this is the baseline to beat by GATING)")

    bucketize("FLOW TOXICITY |imbalance|  (the key test)", legs,
              [("0.0-0.2", 0.0, 0.2), ("0.2-0.4", 0.2, 0.4), ("0.4-0.6", 0.4, 0.6),
               ("0.6-0.8", 0.6, 0.8), ("0.8-1.01", 0.8, 1.01)], lambda d: d["tox"])
    bucketize("SIGNED flow imbalance", legs,
              [("-1.0--0.5", -1.0, -0.5), ("-0.5-0.0", -0.5, 0.0),
               ("0.0-0.5", 0.0, 0.5), ("0.5-1.01", 0.5, 1.01)], lambda d: d["imb"])
    vols = sorted(d["vol"] for d in legs)
    q = lambda p: vols[min(len(vols) - 1, int(p * len(vols)))]
    bucketize("PRE-ENTRY volume (quartiles)", legs,
              [("Q1 low", -1, q(0.25)), ("Q2", q(0.25), q(0.5)),
               ("Q3", q(0.5), q(0.75)), ("Q4 high", q(0.75), 1e18)], lambda d: d["vol"])
    bucketize("BTC abs move so far ($)", legs,
              [("0-20", 0, 20), ("20-40", 20, 40), ("40-70", 40, 70),
               ("70+", 70, 1e9)], lambda d: d["btc_absmove"])
    bucketize("HOUR of day (IL)", legs,
              [(f"{h:02d}-{h+3:02d}", h, h + 3) for h in range(0, 24, 3)],
              lambda d: d["hour"])
    print("\n  A feature is a usable GATE if win%/EV rises monotonically across its")
    print("  buckets. Flat across buckets = that feature can't separate winners.")


if __name__ == "__main__":
    main()

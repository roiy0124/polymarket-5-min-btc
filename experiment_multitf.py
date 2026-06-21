"""Multi-timeframe line construction (experiment, not in the menu).

The line is ANCHORED on the 24h signal, then nudged by shorter timeframes with
DECREASING strength, and the buy-window may only SHORTEN as timeframes shrink:

  24h  -> hard anchor (sell T, buy-window [t1,t2])
  18h  -> nudge T by 0.50 toward the 18h optimum; window may narrow by 0.50
  12h  -> nudge T by 0.25; window may narrow by 0.25
   8h  -> nudge T by 0.125; window may narrow by 0.125

Entry price z is fixed (it's the signal identity). Shorter TFs only ADJUST an
existing 24h anchor -- they can't create a line, and they can never widen the
window. We trade the resulting line walk-forward (out-of-sample) and also trade an
ANCHOR-ONLY version (no shorter-TF nudges) as the baseline, at 5h and 2h blocks.

    python experiment_multitf.py

*** PREVIEW ONLY -- one night of data CANNOT decide edge. *** This shows whether the
construction behaves as intended and its rough direction vs the plain anchor. The
real test is re-running this over weeks of data (with book_events compaction).
"""

import os
import time
import argparse

from experiment_walkforward import open_merged, replay_leg
from analysis.signals import load, dots_for, find_signal, map_admit_threshold
from exec_engine.config import SafetyConfig

WINDOW = 300.0
ANCHOR_H = 24
LADDER = [(18, 0.50), (12, 0.25), (8, 0.125)]   # (timeframe hours, nudge strength)
FLOORS = {"min_win": 0.70, "min_roi": 0.10, "min_dots": 8, "min_frac": 0.20,
          "min_entry": 0.10, "usd": 2.0, "alpha": 0.05, "power": 0.80}
TICK = 0.01


def _fs(dots, z, tf_h, cut, f):
    return find_signal(dots, z, [(f"{tf_h}h", cut)], f["min_win"], f["min_roi"],
                       f["min_dots"], f["min_frac"], f["alpha"], f["power"])


def build_both(windows, T, f):
    """Return (anchor_only_signals, multitf_signals) as of time T."""
    lo = max(1, int(round(f["min_entry"] * 100)))
    cut24 = T - ANCHOR_H * 3600
    past24 = [w for w in windows if w["ws"] + WINDOW <= T and w["ws"] >= cut24]
    # cache 24h dots per (side,cent); admission from the 24h maps
    dots24, totals = {}, []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d = dots_for(past24, side, cent)
            dots24[(side, cent)] = d
            totals.append(len(d))
    admit = map_admit_threshold(totals)

    anchor_sigs, multitf_sigs = [], []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d24 = dots24[(side, cent)]
            if len(d24) < admit:
                continue
            z = cent / 100.0
            a = _fs(d24, z, ANCHOR_H, cut24, f)
            if not a:
                continue
            shares = round(f["usd"] / z, 2)
            anchor_sigs.append({"side": side, "entry": z, "sell": a["sell"],
                                "t1": a["t1"], "t2": a["t2"], "shares": shares, "ev": a["ev"]})
            # ---- apply the damped, shorten-only ladder ----
            Tsell, t1, t2 = a["sell"], a["t1"], a["t2"]
            for tf_h, w in LADDER:
                cuttf = T - tf_h * 3600
                dtf = [dd for dd in d24 if dd[2] >= cuttf]   # same dots, TF-windowed
                s = _fs(dtf, z, tf_h, cuttf, f)
                if not s:
                    continue
                Tsell = Tsell + w * (s["sell"] - Tsell)          # nudge sell toward TF opt
                t1p = t1 + w * (s["t1"] - t1)
                if t1p > t1:                                      # only narrow the start
                    t1 = t1p
                t2p = t2 + w * (s["t2"] - t2)
                if t2p < t2:                                      # only narrow the end
                    t2 = t2p
            Tsell = round(round(Tsell / TICK) * TICK, 2)
            if Tsell <= z or (t2 - t1) < 0.5:                    # invalid / collapsed window
                continue
            multitf_sigs.append({"side": side, "entry": z, "sell": Tsell,
                                 "t1": round(t1, 2), "t2": round(t2, 2),
                                 "shares": shares, "ev": a["ev"]})
    return anchor_sigs, multitf_sigs


def trade_walkforward(conn, windows, tokens, outcomes, all_ws, t_start, t_end,
                      block_h, scfg, which):
    """which: 'anchor' or 'multitf'. Returns (rows per block)."""
    refresh = block_h * 3600.0
    blocks = []
    T = t_start
    while T < t_end:
        a, m = build_both(windows, T, FLOORS)
        sigs = a if which == "anchor" else m
        legs = fills = wins = 0
        pnl = stake = 0.0
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
                if r is None:
                    continue
                legs += 1
                pnl += r[1]
                if r[0]:
                    fills += 1
                    stake += s["shares"] * s["entry"]
                    if r[1] > 1e-9:
                        wins += 1
        blocks.append({"start": time.strftime("%m-%d %H:%M", time.localtime(T)),
                       "n_sigs": len(sigs), "fills": fills, "wins": wins,
                       "pnl": pnl, "stake": stake})
        T += refresh
    return blocks


def summarize(name, blocks):
    fills = sum(b["fills"] for b in blocks)
    wins = sum(b["wins"] for b in blocks)
    pnl = sum(b["pnl"] for b in blocks)
    stake = sum(b["stake"] for b in blocks)
    wr = (wins / fills) if fills else 0.0
    ev = (pnl / stake) if stake else 0.0
    print(f"  {name:>14}: fills {fills:>4}  win {wr:>4.0%}  pnl {pnl:>+8.1f}  EV/fill {ev:>+5.2f}")
    return pnl, ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block-hours", type=float, nargs="+", default=[5.0, 2.0],
                    dest="block_hours")
    args = ap.parse_args()

    conn, dbs = open_merged()
    windows = load(conn)
    tokens = {ws: (tu, td) for ws, tu, td in conn.execute(
        "SELECT window_start, token_up, token_down FROM windows WHERE token_up IS NOT NULL")}
    outcomes = {w["ws"]: w["outcome"] for w in windows}
    all_ws = sorted(w["ws"] for w in windows)
    t_end = all_ws[-1] + WINDOW
    t_start = all_ws[0] + ANCHOR_H * 3600     # need 24h history before first trade
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)

    print("*** PREVIEW ONLY -- one night of data cannot decide edge ***")
    print(f"data: {len(dbs)} db(s); trading {(t_end - t_start)/3600:.0f}h; "
          f"anchor {ANCHOR_H}h, ladder {LADDER}\n")

    for bh in args.block_hours:
        print(f"===== {bh:g}h blocks =====")
        anc = trade_walkforward(conn, windows, tokens, outcomes, all_ws, t_start, t_end,
                                bh, scfg, "anchor")
        mtf = trade_walkforward(conn, windows, tokens, outcomes, all_ws, t_start, t_end,
                                bh, scfg, "multitf")
        # per-block detail (anchor vs multi-TF side by side)
        print(f"  {'start':>11} | {'ANCHOR win/pnl':>16} | {'MULTI-TF win/pnl':>17}")
        for ba, bm in zip(anc, mtf):
            aw = (ba["wins"] / ba["fills"]) if ba["fills"] else 0.0
            mw = (bm["wins"] / bm["fills"]) if bm["fills"] else 0.0
            print(f"  {ba['start']:>11} | {aw:>6.0%} {ba['pnl']:>+9.1f} | "
                  f"{mw:>6.0%} {bm['pnl']:>+10.1f}")
        ap_, ae = summarize("anchor-only", anc)
        mp, me = summarize("multi-TF", mtf)
        print(f"  -> multi-TF vs anchor: pnl {mp-ap_:+.1f}, EV/fill {me-ae:+.2f} "
              f"({'helps' if me > ae + 0.02 else 'hurts' if me < ae - 0.02 else 'no diff'})\n")

    print("Reminder: PREVIEW. Re-run over weeks of data for a real verdict.")


if __name__ == "__main__":
    main()

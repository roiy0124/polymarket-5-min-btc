"""Toxic-flow filter — the decisive test for the mean-reversion idea.

The mean-reversion research concluded the edge (if any) lives in separating
NON-informational (panic/forced) selling, which reverts, from INFORMED (toxic)
selling, which does not. This measures, for each dip episode, the trade-sign
imbalance of the flow that caused the dip, then compares the recover rate of
LOW-toxicity dips vs HIGH-toxicity dips.

If low-toxicity dips recover much more often than high-toxicity ones, there's a
real, filterable edge. If not, the dip is just efficient repricing.

    python -m analysis.flow [--dip 0.25 --recover 0.33 --min-left 240
                             --lookback 60 --tox 0.6]

Stdlib only. Small-sample caveats apply (DATA-ANALYSIS-TOOLKIT.md). This is the
conditional test the research demands; treat thresholds as hypotheses to count.
"""

import argparse

from . import panel


def find_dip(conn, ws, side, dip, recover, min_left):
    """Return (dip_ts, recovered) for the first qualifying dip, else (None, None)."""
    col = "up_mid" if side == "up" else "down_mid"
    snaps = conn.execute(
        f"SELECT ts, time_left, {col} FROM snapshots WHERE window_start=? AND {col} "
        f"IS NOT NULL ORDER BY ts", (ws,)).fetchall()
    dip_ts = None
    for ts, tl, mid in snaps:
        if dip_ts is None:
            if mid <= dip and tl >= min_left:
                dip_ts = ts
        elif mid >= recover:
            return dip_ts, True
    return dip_ts, (False if dip_ts is not None else None)


def flow_imbalance(conn, token, t0, t1):
    """Signed trade-sign imbalance (buy-sell)/(buy+sell) in [t0,t1], and volume."""
    rows = conn.execute(
        "SELECT side, size FROM trades WHERE asset_id=? AND recv_ts>=? AND recv_ts<=?",
        (token, t0, t1)).fetchall()
    buy = sum(float(s) for sd, s in rows if sd == "BUY" and s is not None)
    sell = sum(float(s) for sd, s in rows if sd == "SELL" and s is not None)
    tot = buy + sell
    if tot <= 0:
        return None, 0.0
    return (buy - sell) / tot, tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dip", type=float, default=0.25)
    ap.add_argument("--recover", type=float, default=0.33)
    ap.add_argument("--min-left", type=float, default=240.0, dest="min_left")
    ap.add_argument("--lookback", type=float, default=60.0)
    ap.add_argument("--tox", type=float, default=0.6,
                    help="|imbalance| at/above this = high-toxicity (informed) flow")
    args = ap.parse_args()

    conn = panel.connect()
    windows = conn.execute(
        "SELECT window_start, token_up, token_down FROM windows ORDER BY window_start"
    ).fetchall()

    low = {"n": 0, "rec": 0}
    high = {"n": 0, "rec": 0}
    no_flow = 0
    for ws, tok_up, tok_down in windows:
        for side, token in (("up", tok_up), ("down", tok_down)):
            dip_ts, recovered = find_dip(conn, ws, side, args.dip, args.recover, args.min_left)
            if dip_ts is None:
                continue
            imb, vol = flow_imbalance(conn, token, dip_ts - args.lookback, dip_ts)
            if imb is None:
                no_flow += 1
                continue
            # a dip is sell-driven; |imbalance| measures one-sidedness (toxicity proxy)
            bucket = high if abs(imb) >= args.tox else low
            bucket["n"] += 1
            if recovered:
                bucket["rec"] += 1
    conn.close()

    print(f"Toxic-flow conditional reversion  dip<= {args.dip} recover>= {args.recover} "
          f"min_left>= {args.min_left:.0f}s lookback {args.lookback:.0f}s tox>= {args.tox}")

    def line(name, b):
        if b["n"] == 0:
            print(f"  {name:>16}: 0 episodes")
            return
        print(f"  {name:>16}: {b['rec']}/{b['n']} recovered = {b['rec']/b['n']:.3f}")

    line("LOW-toxicity", low)
    line("HIGH-toxicity", high)
    if no_flow:
        print(f"  (skipped {no_flow} dips with no trade flow in the lookback window)")
    if low["n"] and high["n"]:
        edge = low["rec"] / low["n"] - high["rec"] / high["n"]
        print(f"\n  low-minus-high recover gap: {edge:+.3f}  "
              f"({'supports the filter' if edge > 0.05 else 'no clear filter edge yet'})")
    print("\n  This is the make-or-break test. Needs many episodes to be significant;")
    print("  also try VPIN-style bucketing and trade-size/speed features (see research).")


if __name__ == "__main__":
    main()

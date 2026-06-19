"""Per-round price-graph capture -> round_charts/.

For each resolved 5-minute round, render ONE chart showing that round's price
evolution, built from our own high-fidelity snapshots (~300 points/round, 1/sec)
and overlaid with Polymarket's OFFICIAL price points (from the public
prices-history API, fetched live near close) as ground-truth validation.

Why this design (see deep research): the website's own API gives only ~3-5 coarse
points per 5-min round AND returns empty once the round resolves -- so our 1/sec
data is the better line, and the API points serve only to confirm our line is
accurate. No browser, no ToS/bot risk.

Runs continuously (a supervisor child). On startup it BACKFILLS any settled
windows that don't have a chart yet (line only; official points exist only for
rounds captured live going forward).

    python chart_capture.py            # run as a service
    python chart_capture.py --once     # backfill existing windows and exit
"""

import os
import sys
import glob
import time
import sqlite3
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import feeds

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "btc_updown.db")
OUTDIR = os.path.join(HERE, "round_charts")
WINDOW = 300
INTERVAL = 5.0
OFFICIAL_FETCH_BELOW = 25.0   # fetch official points when time-left < this (still live)


def utc_stamp(ws):
    return datetime.fromtimestamp(ws, tz=timezone.utc).strftime("%Y%m%d-%H%M")


def charted(ws):
    return bool(glob.glob(os.path.join(OUTDIR, f"{ws}_*.png")))


def render(conn, ws, official_up=None):
    row = conn.execute(
        "SELECT strike_binance, final_binance, our_outcome, resolved_outcome "
        "FROM windows WHERE window_start=?", (ws,)).fetchone()
    if not row:
        return False
    strike, final, our, official_outcome = row
    snaps = conn.execute(
        "SELECT time_left, up_mid, down_mid, btc_binance FROM snapshots "
        "WHERE window_start=? AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
    if len(snaps) < 3:
        return False
    xs = [(WINDOW - tl) / 60.0 for tl, _, _, _ in snaps]
    up = [u for _, u, _, _ in snaps]
    dn = [d for _, _, d, _ in snaps]
    btc = [b for _, _, _, b in snaps]

    fig, ax = plt.subplots(figsize=(7.6, 4.4), dpi=90)
    # --- left axis: token prices (0..1) ---
    ax.plot(xs, up, color="#3fb950", lw=1.4, label="Up  (our 1/sec data)")
    if any(d is not None for d in dn):
        ax.plot(xs, dn, color="#e5534b", lw=1.0, alpha=0.4, label="Down")
    if official_up:
        ox = [(t - ws) / 60.0 for t, _ in official_up]
        oy = [p for _, p in official_up]
        ax.scatter(ox, oy, c="black", s=34, zorder=6, marker="o",
                   label="Polymarket official (Up)")
    ax.axhline(0.5, ls=":", color="#888", lw=0.8)
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 1)
    ax.set_xlabel("minutes into the 5-minute round")
    ax.set_ylabel("token price (implied probability)")

    # --- right axis: BTC price + target (strike) ---
    ax2 = ax.twinx()
    bx = [x for x, b in zip(xs, btc) if b is not None]
    by = [b for b in btc if b is not None]
    if by:
        ax2.plot(bx, by, color="#f0883e", lw=1.3, label="BTC price", zorder=4)
        anchors = list(by) + ([strike] if strike else [])
        lo, hi = min(anchors), max(anchors)
        pad = max((hi - lo) * 0.35, 3.0)
        ax2.set_ylim(lo - pad, hi + pad)
        if strike:
            ax2.axhline(strike, ls="--", color="#d4a017", lw=1.2,
                        label=f"target / strike  {strike:.0f}")
        ax2.set_ylabel("BTC price (USD)", color="#f0883e")
        ax2.tick_params(axis="y", labelcolor="#f0883e")
        ax2.ticklabel_format(axis="y", style="plain", useOffset=False)

    outc = official_outcome or our or "pending"
    t = datetime.fromtimestamp(ws, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    sub = f"  |  BTC {strike:.0f} -> {final:.0f}" if (strike and final) else ""
    ax.set_title(f"{t} UTC   resolved: {outc}{sub}")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7.5, framealpha=0.9)
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTDIR, f"{ws}_{utc_stamp(ws)}.png"))
    plt.close(fig)
    return True


def backfill(conn):
    n = 0
    for (ws,) in conn.execute(
            "SELECT window_start FROM windows WHERE resolved_outcome IS NOT NULL "
            "ORDER BY window_start"):
        if charted(ws):
            continue
        if render(conn, ws):
            n += 1
    return n


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    once = "--once" in sys.argv

    n = backfill(conn)
    print(f"chart_capture: backfilled {n} round chart(s) -> {OUTDIR}", flush=True)
    if once:
        conn.close()
        return

    official = {}   # window_start -> official up points (fetched live near close)
    print("chart_capture: live (Ctrl-C to stop)", flush=True)
    while True:
        try:
            now = time.time()
            ws = int(now // WINDOW * WINDOW)
            end = ws + WINDOW
            tleft = end - now
            # grab official points while the round is still live (API erases on resolve)
            if 0 < tleft < OFFICIAL_FETCH_BELOW and ws not in official:
                tok = conn.execute(
                    "SELECT token_up FROM windows WHERE window_start=?", (ws,)).fetchone()
                if tok and tok[0]:
                    try:
                        official[ws] = feeds.fetch_price_history(tok[0], ws, end, fidelity=1)
                    except Exception:
                        official[ws] = None
            # render any settled, un-charted window
            for (cw,) in conn.execute(
                    "SELECT window_start FROM windows WHERE window_end<=? AND "
                    "resolved_outcome IS NOT NULL ORDER BY window_start DESC LIMIT 8",
                    (now - 3,)):
                if charted(cw):
                    continue
                if render(conn, cw, official.get(cw)):
                    print(f"[{time.strftime('%H:%M:%S')}] charted round {cw} "
                          f"({'official' if official.get(cw) else 'data-only'})", flush=True)
            # prune old cached official points
            for k in [k for k in official if k < now - 2 * WINDOW]:
                official.pop(k, None)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] chart_capture error (continuing): {e!r}",
                  flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

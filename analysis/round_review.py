"""Round reviews — per-round charts of what the PAPER executor actually did.

For each round (window) the paper executor traded, render the traded token's price
path with three things marked:
  * ENTRY   — where the BUY filled (green dot at the entry price z)
  * TARGET  — the expected sell price T, drawn higher up the y-axis (purple dashed)
  * BEST    — the best price actually reachable AFTER entry until the round ended
              (orange dot). If BEST sits below TARGET, the sell could never have
              filled and the position rode to settlement — the adverse-selection
              story, made visible.

Reads paper_trades.csv (the executor's recordings) + the DB price path. One PNG per
round into round_reviews/. Read-only.

    python -m analysis.round_review                 # last 20 rounds with fills
    python -m analysis.round_review --last 50
    python -m analysis.round_review --include-unfilled
"""

import os
import csv
import sqlite3
import argparse
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(HERE, "btc_updown.db")
LEDGER = os.path.join(HERE, "paper_trades.csv")
OUTDIR = os.path.join(HERE, "round_reviews")
WINDOW = 300.0
SIDE_COLOR = {"up": "#1f77b4", "down": "#8c564b"}


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_legs(path):
    """window_start -> list of leg dicts."""
    by_win = defaultdict(list)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            by_win[int(r["window_start"])].append(r)
    return by_win


def path_for(conn, ws, side):
    """[(minutes_in, mid)] for one side's token over the window."""
    rows = conn.execute(
        "SELECT time_left, up_mid, down_mid FROM snapshots WHERE window_start=? "
        "AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
    out = []
    for tl, um, dm in rows:
        mid = um if side == "up" else dm
        if mid is not None:
            out.append((max(0.0, (WINDOW - tl) / 60.0), mid))
    return out


def entry_and_best(path, z, tol=0.005):
    """First touch of the entry price z, then the best (max) price reachable after.
    Returns (entry_x, best_x, best_y) or None if z was never touched."""
    entry_x = None
    for x, mid in path:
        if mid <= z + tol:
            entry_x = x
            break
    if entry_x is None:
        return None
    after = [(x, mid) for x, mid in path if x >= entry_x]
    if not after:
        return entry_x, entry_x, z
    bx, by = max(after, key=lambda p: p[1])
    return entry_x, bx, by


def review_window(conn, ws, legs, include_unfilled):
    outcome = conn.execute("SELECT resolved_outcome FROM windows WHERE window_start=?",
                           (ws,)).fetchone()
    outcome = outcome[0] if outcome else "?"
    use = [l for l in legs if include_unfilled or _f(l["buy_filled"]) >= 1]
    if not use:
        return None
    sides = sorted({l["side"] for l in use})

    fig, ax = plt.subplots(figsize=(9, 5))
    xmax = WINDOW / 60.0

    # TARGETS: one dashed line per distinct expected-sell price, labeled at the right.
    for T in sorted({_f(l["sell_T"]) for l in use}):
        ax.hlines(T, 0, xmax, color="purple", ls="--", lw=0.8, alpha=0.85, zorder=3)
        ax.annotate(f"{T:.2f}", (xmax, T), textcoords="offset points", xytext=(-2, 1),
                    ha="right", va="bottom", fontsize=7, color="purple")

    pnl_total = 0.0
    reached = entered = 0
    for side in sides:
        path = path_for(conn, ws, side)
        if path:
            ax.plot([x for x, _ in path], [m for _, m in path],
                    color=SIDE_COLOR.get(side, "gray"), lw=1.3, label=f"{side} price", zorder=2)
        for leg in (l for l in use if l["side"] == side):
            z, T = _f(leg["entry_z"]), _f(leg["sell_T"])
            pnl_total += _f(leg["realized_pnl"])
            eb = entry_and_best(path, z) if path else None
            if eb is None:
                continue
            ex, bx, by = eb
            entered += 1
            if by >= T - 1e-9:
                reached += 1
            # entry -> best-reachable connector + the two dots (no text; the legend
            # and y-axis carry the meaning, keeps clustered rounds readable)
            ax.plot([ex, bx], [z, by], color="orange", lw=0.7, alpha=0.35, zorder=4)
            ax.scatter([ex], [z], color="green", s=30, zorder=6, edgecolor="black", linewidth=0.3)
            ax.scatter([bx], [by], color="orange", s=30, zorder=6, edgecolor="black", linewidth=0.3)

    ax.set_xlim(0, xmax)
    ax.set_ylim(0, 1)
    ax.set_xlabel("minutes into round")
    ax.set_ylabel("price")
    ax.set_title(f"round {ws}  —  resolved {outcome}  —  paper pnl {pnl_total:+.2f}  "
                 f"—  targets reached {reached}/{entered}")
    ax.grid(True, alpha=0.2)
    handles = [Line2D([], [], color=SIDE_COLOR.get(s, "gray"), lw=1.3, label=f"{s} price")
               for s in sides]
    handles += [
        Line2D([], [], marker="o", color="w", markerfacecolor="green",
               markeredgecolor="black", markersize=7, label="buy fill (entry)"),
        Line2D([], [], marker="o", color="w", markerfacecolor="orange",
               markeredgecolor="black", markersize=7, label="best sell reachable after entry"),
        Line2D([], [], color="purple", ls="--", lw=0.8, label="target (expected sell)"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8)
    os.makedirs(OUTDIR, exist_ok=True)
    outpath = os.path.join(OUTDIR, f"round_{ws}.png")
    fig.savefig(outpath, bbox_inches="tight", dpi=110)
    plt.close(fig)
    return outpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=LEDGER)
    ap.add_argument("--last", type=int, default=20, help="render the most recent N rounds")
    ap.add_argument("--include-unfilled", action="store_true",
                    help="also render rounds where nothing filled")
    args = ap.parse_args()

    if not os.path.exists(args.ledger) or os.path.getsize(args.ledger) == 0:
        print(f"no paper ledger at {args.ledger} — run the Phase-2 paper executor (menu 12) first.")
        return
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}.")
        return

    by_win = load_legs(args.ledger)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    windows = sorted(by_win, reverse=True)[:args.last]
    made = 0
    for ws in sorted(windows):
        out = review_window(conn, ws, by_win[ws], args.include_unfilled)
        if out:
            made += 1
            print(f"  {os.path.basename(out)}")
    conn.close()
    if made:
        print(f"\n  {made} round review(s) -> {OUTDIR}")
    else:
        print("  no rounds with fills to review "
              "(use --include-unfilled to render them anyway).")


if __name__ == "__main__":
    main()

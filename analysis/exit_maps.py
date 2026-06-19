"""Exit-opportunity maps — one scatter per entry price, per side.

For every entry price z (1c..99c) and each side (up/down), plot one dot per window:
  x = WHEN you entered (the first moment that window's token price hit z), in
      minutes into the 5-minute round (0..5).
  y = the realized EXIT value: the best price you could have SOLD at afterward in
      the same window (highest mid after entry), OR -- if there was no real bounce
      above entry -- the resolution value: 1.0 if that side won, 0.0 if it lost.
      So a "couldn't sell" loss sits at 0 (complete loss), a held win at 1.0.
  color = the window's final outcome: green = resolved Up, red = resolved Down.

Output: exit_maps/up/entry_NNc.png and exit_maps/down/entry_NNc.png  (99 each).

Reference lines per chart: dashed at y=z (sell breakeven) and dotted at y=2z.
y is the best MID (a mild upper bound; real sells hit the bid). Exploratory only.

    python -m analysis.exit_maps
"""

import os
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import panel

WINDOW = 300.0
SELL_THRESHOLD = 0.01   # the price must clear entry by this much to count as a real exit
EXEC_DELAY_SEC = 0.4    # signal->execution latency: ignore price action this soon after entry
BUY_WIN_MIN_WIDTH = 0.5   # minutes; the best buy-time window must be >= this (30s)
BUY_WIN_MIN_DOTS = 5      # require this many entries in a window to trust it
BUY_WIN_STEP = 0.25       # minutes; grid for scanning window boundaries
OUTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "exit_maps")


def load_windows(conn):
    """Per settled window: outcome + chronological (elapsed_min, mid) for each side."""
    out = []
    for ws, outcome in conn.execute(
            "SELECT window_start, resolved_outcome FROM windows "
            "WHERE resolved_outcome IN ('Up','Down') ORDER BY window_start"):
        rows = conn.execute(
            "SELECT time_left, up_mid, down_mid FROM snapshots WHERE window_start=? "
            "AND up_mid IS NOT NULL ORDER BY ts", (ws,)).fetchall()
        if not rows:
            continue
        up, dn = [], []
        for tl, um, dm in rows:
            elapsed_min = max(0.0, (WINDOW - tl) / 60.0)
            up.append((elapsed_min, um))
            if dm is not None:
                dn.append((elapsed_min, dm))
        out.append({"outcome": outcome, "up": up, "down": dn})
    return out


def entry_and_exit(path, cent, won):
    """First entry into the 1c bucket for `cent`, then the realized EXIT value:
      - if the price later rose above entry by >= SELL_THRESHOLD, you could have
        sold the bounce -> exit = that best subsequent mid;
      - otherwise there was no sellable bounce, so you hold to resolution ->
        exit = 1.0 if this side won, else 0.0 (a complete loss sits at zero).
    Returns (entry_elapsed_min, exit_value) or None.
    floor into a uniform 1c bucket [cent, cent+1) -- NOT round(), whose banker's
    rounding (.5 -> even) leaves odd-cent charts artificially empty."""
    idx = None
    for i, (_, mid) in enumerate(path):
        if int(mid * 100 + 1e-6) == cent:
            idx = i
            break
    if idx is None:
        return None
    entry_x, entry_p = path[idx]
    # only look for an exit AFTER the signal->execution latency (you can't react
    # to price action in the first EXEC_DELAY_SEC after the entry signal fires)
    delay_min = EXEC_DELAY_SEC / 60.0
    after = [mid for x, mid in path[idx + 1:] if x >= entry_x + delay_min]
    best_after = max(after) if after else entry_p
    if best_after >= entry_p + SELL_THRESHOLD:
        return entry_x, best_after            # a real bounce you could sell into
    return entry_x, (1.0 if won else 0.0)     # no exit -> resolution (0 = loss)


def _wilson_lb(k, n, z=1.96):
    """95% Wilson lower bound on a win-rate k/n -- high only when the rate is high
    AND well-sampled, so a 3-of-3 fluke scores below a 40-of-45."""
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h)


def best_buy_window(dots, z):
    """Best contiguous entry-time window (>= BUY_WIN_MIN_WIDTH wide) to buy at z.
    A 'win' = exit value above the entry price z. Chosen for winning CONSISTENCY
    first (Wilson lower bound on win-rate), then ROI, then width.
    Returns (t1, t2, mean_exit, win_rate, lb, roi, n) or None."""
    if len(dots) < BUY_WIN_MIN_DOTS:
        return None
    grid = [round(i * BUY_WIN_STEP, 2) for i in range(int(5 / BUY_WIN_STEP) + 1)]
    best = None
    for a in range(len(grid)):
        for b in range(a + 1, len(grid)):
            t1, t2 = grid[a], grid[b]
            if t2 - t1 < BUY_WIN_MIN_WIDTH - 1e-9:
                continue
            inside = [d for d in dots if t1 <= d[0] <= t2]
            n = len(inside)
            if n < BUY_WIN_MIN_DOTS:
                continue
            wins = sum(1 for d in inside if d[1] > z + 1e-9)
            wr = wins / n
            lb = _wilson_lb(wins, n)
            mean_exit = sum(d[1] for d in inside) / n
            roi = (mean_exit - z) / z if z > 0 else 0.0
            key = (round(lb, 4), round(roi, 4), t2 - t1)
            if best is None or key > best[0]:
                best = (key, t1, t2, mean_exit, wr, lb, roi, n)
    if best is None:
        return None
    _, t1, t2, mean_exit, wr, lb, roi, n = best
    return t1, t2, mean_exit, wr, lb, roi, n


def make_plot(side, cent, dots, outpath):
    z = cent / 100.0
    fig, ax = plt.subplots(figsize=(6.2, 4.2), dpi=85)
    if dots:
        gx = [x for x, y, c in dots if c == "g"]
        gy = [y for x, y, c in dots if c == "g"]
        rx = [x for x, y, c in dots if c == "r"]
        ry = [y for x, y, c in dots if c == "r"]
        ax.scatter(rx, ry, s=22, c="#e5534b", alpha=0.6, edgecolors="none",
                   label=f"Down ({len(rx)})")
        ax.scatter(gx, gy, s=22, c="#3fb950", alpha=0.6, edgecolors="none",
                   label=f"Up ({len(gx)})")
    ax.axhline(z, ls="--", lw=1, color="#888", label=f"entry {cent}c")
    if 2 * z <= 1.0:
        ax.axhline(2 * z, ls=":", lw=1, color="#bbb", label=f"2x ({2*cent}c)")
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 1)
    ax.set_xlabel("entry time (min into the 5-min round)")
    ax.set_ylabel("exit value (sell bounce, else 1=win / 0=loss at resolution)")
    ax.set_title(f"{side.upper()} token  |  entry @ {cent}c  |  n={len(dots)}")

    # best buy-time window (consistency first): shade it, draw a line at the
    # expected exit price, and print the expected ROI on the left.
    bw = best_buy_window(dots, z)
    if bw:
        t1, t2, mean_exit, wr, lb, roi, n = bw
        ax.axvspan(t1, t2, color="#3fb950", alpha=0.08, zorder=0)
        ax.plot([t1, t2], [mean_exit, mean_exit], color="#8957e5", lw=2.6, zorder=4,
                solid_capstyle="butt", label="best buy-window")
        ax.text(0.02, 0.035,
                f"BUY {t1:.2g}-{t2:.2g} min   win {wr:.0%}   EV {roi:+.0%}   n={n}",
                transform=ax.transAxes, fontsize=8, color="#5a32a3", weight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#8957e5", alpha=0.92))

    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, alpha=0.15)
    fig.tight_layout()
    fig.savefig(outpath)
    plt.close(fig)


def main():
    conn = panel.connect()
    windows = load_windows(conn)
    conn.close()
    nonempty = {"up": 0, "down": 0}
    for side in ("up", "down"):
        sd = os.path.join(OUTDIR, side)
        os.makedirs(sd, exist_ok=True)
        for cent in range(1, 100):
            dots = []
            for w in windows:
                won = (w["outcome"] == "Up") if side == "up" else (w["outcome"] == "Down")
                eb = entry_and_exit(w[side], cent, won)
                if eb is None:
                    continue
                x, y = eb
                color = "g" if w["outcome"] == "Up" else "r"
                dots.append((x, y, color))
            if dots:
                nonempty[side] += 1
            make_plot(side, cent, dots, os.path.join(sd, f"entry_{cent:02d}c.png"))
        print(f"  {side}: wrote 99 charts ({nonempty[side]} with data) -> {sd}")
    print(f"done. {len(windows)} settled windows. open exit_maps/up and exit_maps/down")


if __name__ == "__main__":
    main()

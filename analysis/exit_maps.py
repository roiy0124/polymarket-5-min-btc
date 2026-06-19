"""Exit-opportunity maps — one scatter per entry price, per side.

For every entry price z (1c..99c) and each side (up/down), plot one dot per window:
  x = WHEN you entered (the first moment that window's token price hit z), in
      minutes into the 5-minute round (0..5).
  y = the BEST price you could have sold at afterward in the SAME window
      (the highest mid reached after entry, before the round ended).
  color = the window's final outcome: green = resolved Up, red = resolved Down.

Output: exit_maps/up/entry_NNc.png and exit_maps/down/entry_NNc.png  (99 each).

Reference lines per chart: dashed at y=z (sell breakeven) and dotted at y=2z.
y is the best MID (a mild upper bound; real sells hit the bid). Exploratory only.

    python -m analysis.exit_maps
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import panel

WINDOW = 300.0
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


def entry_and_best(path, cent):
    """First entry into the 1c bucket for `cent`, then max mid afterward.
    Returns (entry_elapsed_min, best_mid) or None."""
    idx = None
    for i, (_, mid) in enumerate(path):
        # floor into a uniform 1c bucket [cent, cent+1) -- NOT round(), whose
        # banker's rounding (.5 -> even) leaves odd-cent charts artificially empty.
        if int(mid * 100 + 1e-6) == cent:
            idx = i
            break
    if idx is None:
        return None
    best = max(mid for _, mid in path[idx:])
    return path[idx][0], best


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
    ax.set_ylabel("best sell price after entry (same window)")
    ax.set_title(f"{side.upper()} token  |  entry @ {cent}c  |  n={len(dots)}")
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
                eb = entry_and_best(w[side], cent)
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

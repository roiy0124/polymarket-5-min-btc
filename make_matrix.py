"""Tile the per-coin graphs into MATRIX / montage grids for at-a-glance comparison.

For each coin it combines the many individual PNGs in a category into ONE grid image, so
you see related graphs side by side instead of opening 99 files:

  exit_maps/<coin>/up                    -> matrix/<coin>/exit_up.png         (TIME: exit vs entry-time)
  exit_maps/<coin>/down                  -> matrix/<coin>/exit_down.png
  exit_maps/<coin>/up_margin             -> matrix/<coin>/margin_up.png       (PRICE: exit vs gap-from-strike)
  exit_maps/<coin>/down_margin           -> matrix/<coin>/margin_down.png
  exit_maps/<coin>/up_margin_filtered    -> matrix/<coin>/margin_up_filtered.png
  exit_maps/<coin>/down_margin_filtered  -> matrix/<coin>/margin_down_filtered.png
  round_charts/<coin>                    -> matrix/<coin>/rounds.png          (ROUND: per-round price path)

    python make_matrix.py                 # all coins, all categories
    python make_matrix.py --coin sol
    python make_matrix.py --cols 12 --max 150

Reads the PNGs that exit_maps / chart_capture already produced (generate those first). Stdlib
+ matplotlib only.
"""

import os
import sys
import glob
import math
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import coins

HERE = os.path.dirname(os.path.abspath(__file__))

# Grouped by SHARED CONTEXT (the user's ask): each montage tiles graphs that are related by
# the same x-axis context -> TIME, STOCK-PRICE(gap), or ROUND. (montage name, source folder)
CATEGORIES = [
    # TIME context: exit value vs entry-TIME (one tile per entry price)
    ("time_up",            "exit_maps/{c}/up"),
    ("time_down",          "exit_maps/{c}/down"),
    # STOCK-PRICE context: exit value vs the price GAP from strike (one tile per entry price)
    ("price_up",           "exit_maps/{c}/up_margin"),
    ("price_down",         "exit_maps/{c}/down_margin"),
    ("price_up_filtered",  "exit_maps/{c}/up_margin_filtered"),
    ("price_down_filtered","exit_maps/{c}/down_margin_filtered"),
    # ROUND context: the per-round price path (one tile per round)
    ("rounds",             "round_charts/{c}"),
]

# which montages each generator owns (so building is automatic + scoped)
EXIT_NAMES = ["time_up", "time_down", "price_up", "price_down",
              "price_up_filtered", "price_down_filtered"]
ROUND_NAMES = ["rounds"]


def montage(pngs, outpath, cols, title, maxn):
    pngs = sorted(pngs)
    if maxn and len(pngs) > maxn:
        pngs = pngs[-maxn:]          # keep the most recent / highest-numbered
    n = len(pngs)
    if n == 0:
        return 0
    rows = math.ceil(n / cols)
    fig = plt.figure(figsize=(cols * 2.0, rows * 1.5))
    for i, p in enumerate(pngs):
        ax = fig.add_subplot(rows, cols, i + 1)
        ax.axis("off")
        try:
            ax.imshow(plt.imread(p))
        except Exception:
            continue
        ax.set_title(os.path.basename(p)[:-4], fontsize=3)
    fig.suptitle(f"{title}  (n={n})", fontsize=10)
    fig.savefig(outpath, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return n


def build(coin, names=None, cols=10, maxn=120, quiet=False):
    """(Re)build the matrix montages for one coin. `names` limits to a subset of
    CATEGORIES (e.g. EXIT_NAMES or ROUND_NAMES) so each generator rebuilds only its
    own montages. Returns how many were written. Safe to call from other scripts."""
    if coin not in coins.COINS:
        return 0
    outdir = os.path.join(HERE, "matrix", coin)
    os.makedirs(outdir, exist_ok=True)
    made = 0
    for name, tmpl in CATEGORIES:
        if names is not None and name not in names:
            continue
        pngs = glob.glob(os.path.join(HERE, tmpl.format(c=coin), "*.png"))
        if not pngs:
            continue
        out = os.path.join(outdir, f"{name}.png")
        if montage(pngs, out, cols, f"{coin.upper()} {name}", maxn):
            made += 1
            if not quiet:
                print(f"  {coin}/{name}: {len(pngs)} graphs -> {os.path.relpath(out, HERE)}")
    return made


def main():
    ap = argparse.ArgumentParser(description="tile per-coin graphs into matrix montages")
    ap.add_argument("--coin", default="all", help="coin or 'all' (default)")
    ap.add_argument("--cols", type=int, default=10, help="grid columns")
    ap.add_argument("--max", type=int, default=120, dest="maxn",
                    help="cap images per montage (most recent kept)")
    args = ap.parse_args()

    cl = list(coins.ENABLED) if args.coin == "all" else [args.coin]
    for c in cl:
        if c not in coins.COINS:
            print(f"  skip unknown coin {c}"); continue
        if build(c, cols=args.cols, maxn=args.maxn) == 0:
            print(f"  {c}: no source PNGs found (generate exit maps / round charts first)")
    print("\ndone. open matrix/<coin>/ for the side-by-side grids.")


if __name__ == "__main__":
    main()

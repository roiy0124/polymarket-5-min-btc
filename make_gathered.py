"""GATHERED cross-coin montages: the SAME graph across ALL coins, side by side.

The opposite of matrix/<coin>/ (one coin, many entry prices). Here we FIX the graph and vary the
COIN, so you compare the same signal / same round across coins (the cross-asset view):

  gathered/exit_maps/up/entry_54c.png            = every coin's UP 54c exit map, side by side
  gathered/exit_maps/down/entry_54c.png          = every coin's DOWN 54c map
  gathered/exit_maps/up_margin/entry_54c.png     = every coin's UP 54c price-gap map
  ...(down_margin, *_margin_filtered too)...
  gathered/round_charts/<round>.png              = every coin's chart for the SAME round

It works by gathering, for each FILENAME, the same-named PNG from each coin's folder (the
filenames are identical across coins) and tiling them in coin order, each tile titled with the
coin's name in its color. Build the per-coin graphs first (exit_maps / round_charts).

    python make_gathered.py                 # exit maps + round charts
    python make_gathered.py --what exit
    python make_gathered.py --what round --min-coins 2

Stdlib + matplotlib only.
"""

import os
import sys
import glob
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
EXIT_CATS = ["up", "down", "up_margin", "down_margin",
             "up_margin_filtered", "down_margin_filtered"]


def _montage(items, outpath, title, cols):
    """items: list of (coin, png_path) in coin order. One tile per coin, titled in its color."""
    n = len(items)
    if n == 0:
        return False
    rows = (n + cols - 1) // cols
    fig = plt.figure(figsize=(cols * 2.7, rows * 2.1))
    for i, (coin, p) in enumerate(items):
        ax = fig.add_subplot(rows, cols, i + 1)
        ax.axis("off")
        try:
            ax.imshow(plt.imread(p))
        except Exception:
            continue
        ax.set_title(coin.upper(), fontsize=9, color=coins.color(coin), fontweight="bold")
    fig.suptitle(title, fontsize=9)
    fig.savefig(outpath, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return True


def _gather(src_of, out_dir, title_of, cols, min_coins):
    """For each filename present across coins, montage the coins that have it.
    src_of(coin) -> that coin's source folder; title_of(fname) -> montage title."""
    names = set()
    for c in coins.ENABLED:
        for p in glob.glob(os.path.join(src_of(c), "*.png")):
            names.add(os.path.basename(p))
    if not names:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    for fn in sorted(names):
        items = [(c, os.path.join(src_of(c), fn)) for c in coins.ENABLED
                 if os.path.exists(os.path.join(src_of(c), fn))]
        if len(items) < min_coins:
            continue
        if _montage(items, os.path.join(out_dir, fn), title_of(fn), cols):
            made += 1
    return made


def gather_exit(cols=6, min_coins=2):
    total = 0
    for cat in EXIT_CATS:
        made = _gather(lambda c, cat=cat: os.path.join(HERE, "exit_maps", c, cat),
                       os.path.join(HERE, "gathered", "exit_maps", cat),
                       lambda fn, cat=cat: f"exit_maps / {cat} / {fn[:-4]}  -  all coins",
                       cols, min_coins)
        if made:
            print(f"  gathered/exit_maps/{cat}: {made} cross-coin montages")
        total += made
    return total


def gather_round(cols=6, min_coins=2):
    made = _gather(lambda c: os.path.join(HERE, "round_charts", c),
                   os.path.join(HERE, "gathered", "round_charts"),
                   lambda fn: f"round {fn[:-4]}  -  all coins",
                   cols, min_coins)
    if made:
        print(f"  gathered/round_charts: {made} cross-coin montages")
    return made


def build(what="all", cols=6, min_coins=2):
    n = 0
    if what in ("all", "exit"):
        n += gather_exit(cols, min_coins)
    if what in ("all", "round"):
        n += gather_round(cols, min_coins)
    return n


def main():
    ap = argparse.ArgumentParser(description="cross-coin gathered montages")
    ap.add_argument("--what", default="all", choices=["all", "exit", "round"])
    ap.add_argument("--cols", type=int, default=6, help="tiles per row (default 6 = one row)")
    ap.add_argument("--min-coins", type=int, default=2, dest="min_coins",
                    help="only gather a graph present in >= this many coins")
    args = ap.parse_args()
    n = build(args.what, args.cols, args.min_coins)
    print(f"\ndone: {n} gathered montage(s) -> gathered/  (open gathered/exit_maps/<side>/ "
          f"and gathered/round_charts/)")


if __name__ == "__main__":
    main()

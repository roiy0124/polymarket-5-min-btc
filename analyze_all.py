"""Run the per-coin analysis suite for several coins, into per-coin output folders.

For each coin it generates:
  * exit maps           -> exit_maps/<coin>/{up,down,up_margin,down_margin,...}
  * round-chart backfill -> round_charts/<coin>/

Each coin reads ONLY its own data/<coin>/ DB (via ANALYSIS_COIN), so nothing clobbers.
Honors BTC_ANALYSIS_DAYS for the data window (merges that coin's live + archives).

    python analyze_all.py                       # all enabled coins
    python analyze_all.py --coins btc,eth,sol   # a subset
    BTC_ANALYSIS_DAYS=2 python analyze_all.py    # scope to the last 2 days
    python analyze_all.py --no-charts            # exit maps only (skip chart backfill)
"""

import os
import sys
import argparse
import subprocess

import coins

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def _run(cmd, coin):
    env = dict(os.environ)
    env["ANALYSIS_COIN"] = coin          # belt-and-suspenders alongside --coin
    print(f"  $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=HERE, env=env)


def main():
    ap = argparse.ArgumentParser(description="run exit maps + round charts for many coins")
    ap.add_argument("--coins", default=",".join(coins.ENABLED),
                    help="comma-separated coins (default: all enabled)")
    ap.add_argument("--no-charts", action="store_true", help="skip round-chart backfill")
    ap.add_argument("--no-maps", action="store_true", help="skip exit maps")
    args = ap.parse_args()

    sel = [c.strip() for c in args.coins.split(",") if c.strip() in coins.COINS]
    if not sel:
        print("no valid coins selected."); return
    print(f"analyzing {len(sel)} coin(s): {', '.join(sel)}"
          f"   (scope: BTC_ANALYSIS_DAYS={os.environ.get('BTC_ANALYSIS_DAYS', 'current-only')})")

    for c in sel:
        print(f"\n===== {c} =====", flush=True)
        if not args.no_maps:
            _run([PY, "-m", "analysis.exit_maps", "--coin", c], c)
        if not args.no_charts:
            _run([PY, "chart_capture.py", "--coin", c, "--once"], c)

    print(f"\ndone: {len(sel)} coin(s). "
          f"exit maps -> exit_maps/<coin>/ , charts -> round_charts/<coin>/")


if __name__ == "__main__":
    main()

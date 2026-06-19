"""Analysis layer for the collected BTC up/down data.

Stdlib-only scaffolding so it runs today without pandas/numpy (install those from
requirements-analysis.txt when you go deeper). Apply DATA-ANALYSIS-TOOLKIT.md
discipline (walk-forward, count trials, robust stats) before trusting any result.

  panel.py     - build a per-window feature/outcome table from the DB
  calibrate.py - reliability diagram + Brier (is the market's Up price calibrated?)
  reversion.py - unconditional dip->recover scan (first look at the user's idea)
"""

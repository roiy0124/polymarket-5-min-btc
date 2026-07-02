"""experiments/ — the on-market experiment harnesses (see experiments/README.md).

Importing this package puts BOTH the repo root and this folder on sys.path, so the
experiment modules' sibling imports (`from experiment_fear_dip import ...`) and their
root imports (`import coins`, `from analysis import stats`) resolve no matter whether a
script is run directly (`python experiments/foo.py`) or imported as a package module
(`from experiments.foo import ...`).
"""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

"""Coin registry + per-coin data paths for the multi-coin up/down collectors.

Each coin's data lives in its OWN folder under data/<coin>/ (live.db + archive/),
so the high-frequency writers never contend on a single SQLite file and each coin
can be retained/pruned independently. The schema inside every DB is identical
(storage.SCHEMA) — a coin is identified by its FOLDER, not a column, so none of
the existing per-window queries (keyed on window_start) need to change.

Cross-asset analysis reads several coins by ATTACH-ing their DBs and joining on
window_start (the slug timestamp is shared across coins for the same 5-min window).

Legacy fallback: before the one-time migration, BTC data still lives at the repo
root (btc_updown.db + old_dbs/). live_db()/archive_dbs() transparently fall back to
those if data/btc/ doesn't exist yet, so every reader keeps working until the
cutover moves the files. After the move, the new location is found automatically.
"""

import os
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(HERE, "data")


class Coin:
    __slots__ = ("key", "slug_prefix", "binance")

    def __init__(self, key, slug_prefix, binance):
        self.key = key
        self.slug_prefix = slug_prefix      # Gamma slug = f"{slug_prefix}-{window_start}"
        self.binance = binance              # Binance symbol, e.g. BTCUSDT


# the markets all share the {coin}-updown-5m-{ts} slug pattern (verified live)
COINS = {
    "btc":  Coin("btc",  "btc-updown-5m",  "BTCUSDT"),
    "eth":  Coin("eth",  "eth-updown-5m",  "ETHUSDT"),
    "sol":  Coin("sol",  "sol-updown-5m",  "SOLUSDT"),
    "xrp":  Coin("xrp",  "xrp-updown-5m",  "XRPUSDT"),
    "doge": Coin("doge", "doge-updown-5m", "DOGEUSDT"),
    "bnb":  Coin("bnb",  "bnb-updown-5m",  "BNBUSDT"),
}

# coins the supervisor launches a collector pair for. Trim this to collect fewer.
ENABLED = ["btc", "eth", "sol", "xrp", "doge", "bnb"]

_LEGACY_LIVE = os.path.join(HERE, "btc_updown.db")
_LEGACY_ARCHIVE = os.path.join(HERE, "old_dbs")


def get(coin):
    return COINS[coin]


def binance_symbol(coin):
    return COINS[coin].binance


def slug_prefix(coin):
    return COINS[coin].slug_prefix


def coin_dir(coin):
    return os.path.join(DATA_ROOT, coin)


def archive_dir(coin):
    return os.path.join(coin_dir(coin), "archive")


def live_db(coin="btc"):
    """Path to the coin's live DB. Falls back to the legacy btc_updown.db for
    BTC until the migration creates data/btc/live.db."""
    p = os.path.join(coin_dir(coin), "live.db")
    if coin == "btc" and not os.path.exists(p) and os.path.exists(_LEGACY_LIVE):
        return _LEGACY_LIVE
    return p


def archive_dbs(coin="btc"):
    """Sorted list of archived DBs for the coin (legacy old_dbs/ fallback for BTC)."""
    dbs = sorted(glob.glob(os.path.join(archive_dir(coin), "*.db")))
    if coin == "btc" and not dbs and os.path.isdir(_LEGACY_ARCHIVE):
        dbs = sorted(glob.glob(os.path.join(_LEGACY_ARCHIVE, "*.db")))
    return dbs


def all_dbs(coin="btc"):
    """Live DB (first) + archives, existing files only — for merged reads."""
    out = []
    lv = live_db(coin)
    if os.path.exists(lv):
        out.append(lv)
    out += archive_dbs(coin)
    return out


def ensure_dirs(coin):
    os.makedirs(archive_dir(coin), exist_ok=True)

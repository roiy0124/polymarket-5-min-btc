"""Persistent FREE spot-history data layer (Binance public 1s klines).

Authoritative local store of free historical spot data for ALL coins, kept in the
project so every future experiment can reuse it (lead-lag, reversion, fair-value,
idiosyncratic-spike, label-robustness, ...). NOT Polymarket data -- this is the deep
spot side that lets us test a signal's EXISTENCE far further back than our ~weeks of
collected token quotes. See memory `spot-history-two-stage-validation`.

Source: https://data.binance.vision (free, no login, no rate-limit). 1s klines are
available for all six symbols back to ~2021-01 (BTC/ETH to 2017 if you push --start).

Layout (gitignored, see .gitignore `data/spot/`):
  data/spot/<SYMBOL>/<SYMBOL>-1s-<period>.zip   raw provider file (authoritative)
  data/spot/<SYMBOL>/<SYMBOL>-1s-<period>.npz   parsed cache (fast reload)
where <period> is YYYY-MM (completed months) or YYYY-MM-DD (current month, daily).

CLI (bulk fetch + cache, run once, resumable -- skips what exists):
  python -m analysis.spot_data --coins all --start 2021-01
  python -m analysis.spot_data --coins sol,doge --start 2024-01

Programmatic:
  from analysis import spot_data
  d = spot_data.load_range("SOLUSDT", "2025-07")   # -> {sec, close, high, low, vol}
"""
from __future__ import annotations
import argparse, csv, io, os, sys, zipfile
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import numpy as np

COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
SYMBOL = {"btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT",
          "xrp": "XRPUSDT", "doge": "DOGEUSDT", "bnb": "BNBUSDT"}
SYM2COIN = {v: k for k, v in SYMBOL.items()}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOT_DIR = os.path.join(REPO, "data", "spot")
BASE = "https://data.binance.vision/data/spot"
UA = {"User-Agent": "Mozilla/5.0 (spot_data research)"}


def sym_dir(sym: str) -> str:
    d = os.path.join(SPOT_DIR, sym)
    os.makedirs(d, exist_ok=True)
    return d


def _iter_months(start: str, end_excl: datetime):
    y, m = int(start[:4]), int(start[5:7])
    while datetime(y, m, 1, tzinfo=timezone.utc) < end_excl.replace(day=1):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y += 1; m = 1


def periods(sym: str, start: str):
    """List of dicts {key,url,zip,npz} for every monthly file >= start plus daily
    files for the running (incomplete) month through yesterday."""
    now = datetime.now(timezone.utc)
    cur = now.strftime("%Y-%m")
    d = sym_dir(sym)
    out = []
    for ym in _iter_months(start, now):
        if ym == cur:
            continue
        out.append(dict(key=ym,
                        url=f"{BASE}/monthly/klines/{sym}/1s/{sym}-1s-{ym}.zip",
                        zip=os.path.join(d, f"{sym}-1s-{ym}.zip"),
                        npz=os.path.join(d, f"{sym}-1s-{ym}.npz")))
    day = now.replace(hour=0, minute=0, second=0, microsecond=0, day=1)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < today:
        ds = day.strftime("%Y-%m-%d")
        out.append(dict(key=ds,
                        url=f"{BASE}/daily/klines/{sym}/1s/{sym}-1s-{ds}.zip",
                        zip=os.path.join(d, f"{sym}-1s-{ds}.zip"),
                        npz=os.path.join(d, f"{sym}-1s-{ds}.npz")))
        day += timedelta(days=1)
    return out


# ----------------------------------------------------------------- download
def _fetch(url: str, path: str):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path, True, "cached"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
            data = r.read()
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return path, True, "ok"
    except urllib.error.HTTPError as e:
        return path, False, f"HTTP{e.code}"
    except Exception as e:
        return path, False, type(e).__name__


def download(sym: str, start: str, workers: int = 8, quiet: bool = False):
    jobs = [(p["url"], p["zip"]) for p in periods(sym, start)]
    got = new = 0; errs = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_fetch, u, p) for u, p in jobs]
        for fu in as_completed(futs):
            _, ok, msg = fu.result()
            if ok:
                got += 1; new += (msg == "ok")
            else:
                errs[msg] = errs.get(msg, 0) + 1
    if not quiet:
        em = "  ".join(f"{k}:{v}" for k, v in errs.items())
        print(f"  [{sym}] {got}/{len(jobs)} present ({new} new){'  miss '+em if errs else ''}",
              file=sys.stderr)
    return got, errs


def download_all(coins, start, workers: int = 8):
    for c in coins:
        download(SYMBOL[c], start, workers=workers)


# -------------------------------------------------------------------- parse
def _norm_ts(t) -> float:
    t = float(t)
    if t > 1e15:      # microseconds (Binance spot, 2025-01-01+)
        return t / 1e6
    if t > 1e12:      # milliseconds
        return t / 1e3
    return t


def _parse_zip(zip_path: str):
    sec, c, hi, lo, vol = [], [], [], [], []
    with zipfile.ZipFile(zip_path) as z:
        with z.open(z.namelist()[0]) as fh:
            for row in csv.reader(io.TextIOWrapper(fh, "utf-8")):
                try:
                    t = int(_norm_ts(row[0]))
                    o_h, o_l, o_c = float(row[2]), float(row[3]), float(row[4])
                    v = float(row[5])
                except (ValueError, IndexError):
                    continue   # header / malformed
                sec.append(t); c.append(o_c); hi.append(o_h); lo.append(o_l); vol.append(v)
    return (np.asarray(sec, np.int64), np.asarray(c, np.float64),
            np.asarray(hi, np.float32), np.asarray(lo, np.float32),
            np.asarray(vol, np.float32))


def _load_one(p: dict):
    """Return arrays for one period, building the .npz cache from the .zip once."""
    if os.path.exists(p["npz"]):
        try:
            z = np.load(p["npz"])
            return z["sec"], z["close"], z["high"], z["low"], z["vol"]
        except (OSError, zipfile.BadZipFile, KeyError):
            pass  # corrupt cache -> rebuild
    if not (os.path.exists(p["zip"]) and os.path.getsize(p["zip"]) > 0):
        return None
    try:
        sec, c, hi, lo, vol = _parse_zip(p["zip"])
    except (zipfile.BadZipFile, OSError):
        print(f"  bad zip skipped: {os.path.basename(p['zip'])}", file=sys.stderr)
        return None
    tmp = p["npz"] + ".tmp.npz"
    np.savez_compressed(tmp, sec=sec, close=c, high=hi, low=lo, vol=vol)
    os.replace(tmp, p["npz"])
    return sec, c, hi, lo, vol


def load_range(sym: str, start: str, end: str | None = None, fields=("sec", "close")):
    """Concatenate cached 1s data for `sym` over months >= start (and < end if given,
    YYYY-MM exclusive). Returns dict of numpy arrays, deduped to last value per second
    and sorted by time. Parses+caches any period not yet cached."""
    parts = {"sec": [], "close": [], "high": [], "low": [], "vol": []}
    for p in periods(sym, start):
        if end is not None and p["key"][:7] >= end:
            continue
        got = _load_one(p)
        if got is None:
            continue
        sec, c, hi, lo, vol = got
        parts["sec"].append(sec); parts["close"].append(c)
        parts["high"].append(hi); parts["low"].append(lo); parts["vol"].append(vol)
    if not parts["sec"]:
        raise SystemExit(f"No 1s data for {sym} from {start}; run "
                         f"`python -m analysis.spot_data --coins {SYM2COIN.get(sym, sym)} "
                         f"--start {start}` first.")
    sec = np.concatenate(parts["sec"])
    order = np.argsort(sec, kind="stable")
    sec = sec[order]
    keep = np.empty(sec.shape, bool); keep[:-1] = sec[:-1] != sec[1:]; keep[-1] = True
    out = {"sec": sec[keep]}
    for f in ("close", "high", "low", "vol"):
        if f in fields or fields == "all":
            arr = np.concatenate(parts[f])[order][keep]
            out[f] = arr
    return out


def main():
    ap = argparse.ArgumentParser(description="Bulk-download + cache free Binance 1s spot history.")
    ap.add_argument("--coins", default="all", help="'all' or comma list e.g. sol,doge")
    ap.add_argument("--start", default="2021-01", help="earliest month YYYY-MM (1s exists ~2021-01)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--build-cache", action="store_true",
                    help="also parse every zip into its .npz now (slow once, fast forever)")
    a = ap.parse_args()
    coins = COINS if a.coins == "all" else [c.strip() for c in a.coins.split(",")]
    print(f"store: {SPOT_DIR}", file=sys.stderr)
    for c in coins:
        download(SYMBOL[c], a.start, workers=a.workers)
        if a.build_cache:
            n = 0
            for p in periods(SYMBOL[c], a.start):
                if _load_one(p) is not None:
                    n += 1
            print(f"  [{SYMBOL[c]}] cache built for {n} periods", file=sys.stderr)
    print("done.", file=sys.stderr)


if __name__ == "__main__":
    main()

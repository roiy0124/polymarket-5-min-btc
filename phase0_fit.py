"""PHASE 0 — does each TIMESPAN's market price track the maker's Φ formula? (cross-timespan Signature-5)

The user's shortcut: instead of collecting going forward, LIVE-TEST whether longer-timespan markets are priced by
the same Φ fair-value bot — using each market's EXISTING price-history vs the coin's spot-history.

If mid_t = Φ(ln(spot_t/strike)/(σ·√t)) holds, then Φ⁻¹(mid_t) is LINEAR in  x_t = ln(spot_t/strike)/√(τ_t)
with slope 1/σ. So per market we regress  Φ⁻¹(mid) ~ x  and read R²:
  - R² near the 5-min bot's ~0.91  => the SAME sharp Φ maker prices this timespan = SAME WALL.
  - low R²                         => the price drifts off the formula = a weaker/different opponent (a candidate).

Pulls: market mid-history (Polymarket CLOB prices-history) + spot 1-min klines (Binance public) + strike (spot at
window open). No forward collection. Charges nothing, risks nothing — pure measurement.

    python phase0_fit.py [--per-span 8]
"""
import argparse
import json
import sys
import urllib.request

import numpy as np
from scipy import stats as ss

import feeds

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PHIINV = ss.norm.ppf
GE = "https://gamma-api.polymarket.com/events"
GM = "https://gamma-api.polymarket.com/markets"
SYM = {"bitcoin": "BTCUSDT", "btc": "BTCUSDT", "ethereum": "ETHUSDT", "eth": "ETHUSDT",
       "solana": "SOLUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT", "doge": "DOGEUSDT", "bnb": "BNBUSDT"}
DUR = {"5m": 300, "15m": 900, "4h": 14400}


def klines(symbol, start_s, end_s):
    """Binance public 1-min closes over [start,end] (paginated). -> sorted [(sec, close)]."""
    out = []
    t = int(start_s) * 1000
    end_ms = int(end_s) * 1000
    while t < end_ms:
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m"
               f"&startTime={t}&endTime={end_ms}&limit=1000")
        try:
            data = feeds._get_json(url)
        except Exception:
            break
        if not data:
            break
        for k in data:
            out.append((int(k[0]) // 1000, float(k[4])))
        t = int(data[-1][0]) + 60000
        if len(data) < 1000:
            break
    return out


def span_of(slug, title):
    s = (slug + " " + title).lower()
    for sp in ("5m", "15m", "4h"):
        if f"updown-{sp}" in s:
            return sp
    if "up-or-down-on" in s:
        return "daily"
    if "am-et" in s or "pm-et" in s:
        return "hourly"
    return "?"


def market_params(slug, title, end_iso):
    """Derive (symbol, strike_ts, start_s, end_s, span)."""
    span = span_of(slug, title)
    sym = next((v for k, v in SYM.items() if k in (slug + " " + title).lower()), None)
    if span in DUR:
        ws = int(slug.rsplit("-", 1)[-1]); return sym, ws, ws, ws + DUR[span], span
    import datetime as dt
    end = int(dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
    dur = 86400 if span == "daily" else 3600
    return sym, end - dur, end - dur, end, span


def fit_market(token, sym, strike_ts, start_s, end_s):
    """R² of Φ⁻¹(mid) ~ ln(spot/strike)/√τ over the market's life, + implied σ + n usable points."""
    spot = klines(sym, start_s - 120, end_s + 60)
    if len(spot) < 5:
        return None
    st = np.array([s for s, _ in spot]); sp = np.array([c for _, c in spot])
    strike = float(sp[np.argmin(np.abs(st - strike_ts))])
    try:
        mh = feeds.fetch_price_history(token, start_s, end_s, fidelity=5)
    except Exception:
        return None
    xs, ys = [], []
    for t, mid in mh:
        if not (0.03 < mid < 0.97):           # Φ⁻¹ blows up at 0/1; need a live, moving market
            continue
        tau = end_s - t
        if tau < 30:
            continue
        s = float(sp[np.argmin(np.abs(st - t))])
        if s <= 0 or strike <= 0:
            continue
        xs.append(np.log(s / strike) / np.sqrt(tau)); ys.append(PHIINV(mid))
    if len(xs) < 8 or np.std(xs) == 0:
        return None
    xs, ys = np.array(xs), np.array(ys)
    b1, b0, r, p, se = ss.linregress(xs, ys)
    sigma = 1.0 / b1 if b1 > 0 else float("nan")
    return dict(r2=r ** 2, sigma=sigma, n=len(xs), moneyness_range=float(xs.max() - xs.min()))


def _gamma_market(slug):
    """Fetch one event by slug -> (slug, title, endDate, up_token) or None."""
    try:
        d = feeds._get_json(f"{GE}?slug={slug}")
    except Exception:
        return None
    if not isinstance(d, list) or not d:
        return None
    e = d[0]; m = (e.get("markets") or [{}])[0]
    toks = json.loads(m.get("clobTokenIds") or "[]")
    if not toks:
        return None
    return (slug, e.get("title") or m.get("question") or "", m.get("endDate"), toks[0])


def discover(per_span):
    """Build TARGETED recent-resolved slugs per timespan (HF from window-start grid; daily from past dates)."""
    import time, datetime as dt
    from collections import defaultdict
    now = int(time.time())
    by = defaultdict(list)
    # HF spans on btc + eth: walk the window grid backwards (skip the 1-2 most recent = maybe unresolved)
    for sp, secs in DUR.items():
        base = (now // secs) * secs
        for coin in ("btc", "eth"):
            for i in range(2, 2 + per_span * 2):
                if len(by[sp]) >= per_span:
                    break
                r = _gamma_market(f"{coin}-updown-{sp}-{base - secs * i}")
                if r:
                    by[sp].append(r)
    # daily: past dates (resolved), btc + eth
    today = dt.datetime.now(dt.timezone.utc).date()
    for coin in ("bitcoin", "ethereum"):
        for dback in range(1, per_span + 2):
            if len(by["daily"]) >= per_span:
                break
            day = today - dt.timedelta(days=dback)
            r = _gamma_market(f"{coin}-up-or-down-on-{day.strftime('%B').lower()}-{day.day}-{day.year}")
            if r:
                by["daily"].append(r)
    return by


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--per-span", type=int, default=8); args = ap.parse_args()
    print("discovering recent closed crypto up/down markets per timespan ...")
    by = discover(args.per_span)
    print({k: len(v) for k, v in by.items()})
    print(f"\n{'span':6} {'markets':>7} {'median R²':>9} {'R² range':>16} {'median σ-impl':>13} {'median n':>9}")
    print("=" * 70)
    summary = {}
    for sp in ["5m", "15m", "4h", "hourly", "daily"]:
        fits = []
        for slug, title, end, tok in by.get(sp, []):
            sym, kt, ss_, es, _ = market_params(slug, title, end)
            if not sym:
                continue
            f = fit_market(tok, sym, kt, ss_, es)
            if f and f["n"] >= 8 and f["moneyness_range"] > 0:
                fits.append(f)
        if not fits:
            print(f"{sp:6} {'(no usable / no price-moving markets)':>40}")
            continue
        r2 = sorted(x["r2"] for x in fits)
        sg = sorted(x["sigma"] for x in fits if np.isfinite(x["sigma"]))
        n = sorted(x["n"] for x in fits)
        summary[sp] = float(np.median(r2))
        print(f"{sp:6} {len(fits):>7} {np.median(r2):>9.3f} {f'[{r2[0]:.2f},{r2[-1]:.2f}]':>16} "
              f"{(np.median(sg) if sg else float('nan')):>13.2e} {int(np.median(n)):>9}")
    print("\nREAD: a timespan whose median R² ~ the 5-min bot's = the SAME sharp Φ maker (same wall).")
    print("A timespan with markedly LOWER R² = the price drifts off the formula = a weaker/different opponent")
    print("(the candidate). This is Signature 5; a low-R² timespan then earns Phase 1 (collect) + the residual test.")


if __name__ == "__main__":
    main()

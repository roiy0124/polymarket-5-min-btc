"""SCOUT — Polymarket favorite-longshot (FLB) reliability, the NO-CAPITAL first step.

The weak-opponent recon (RESEARCH-EXTERNAL.md PHASE 4 / memory weak-opponent-scout) ranked the favorite-longshot
fade as the #1 pond: rest as a MAKER buying favorites on thin, objectively-resolved event markets, hold to
resolution; the opponent is BIASED retail (the sharp odds-compiler is at the sportsbook, NOT in this order book), so
it is NON-adversarial. Unique virtue: it is CONFIRMABLE FOR FREE on resolved history BEFORE risking a cent. The user
trades on POLYMARKET (non-invasive, crypto-funded), so we test the Polymarket variant.

WHAT THIS DOES (terrain measurement, NOT a trade): pull resolved BINARY (Yes/No), NON-crypto Polymarket markets;
take each YES contract's price 24h BEFORE resolution (strictly causal — you could have entered then and held), and
its 0/1 outcome. Build the favorite-longshot RELIABILITY DIAGRAM (realized win-rate vs price) and route the favorite
band through analysis.stats.assess (fee-aware net-EV, event-clustered, deflated, n_loss>=30). This is SIGNATURE 4 of
the scouting checklist + the terminating gate.

THE THREE KILL-GATES (all must pass to keep the pond alive):
  (a) FAVORITE-BAND residual (won - price) > 0 AND stats.assess SURVIVES (deflated p<0.05, cluster-CI>0, n_loss>=30);
  (b) it SURVIVES in the TOP VOLUME QUINTILE (else it's just illiquidity, not a harvestable crowd bias);
  (c) it is INDEPENDENT of the SHARP price — proxied here, with NO sportsbook data, by the SHARP-CONVERGENCE control:
      does the favorite residual measured at 24h SURVIVE when measured at 1h before close (the market's own sharpest
      price)? If the late price subsumes it, the 24h "edge" is just the market not finished pricing = you're slow =
      ABORT. (A true sportsbook-closing-line control is the Stage-2 follow-up.)

LOCKED constants (pre-registered; do NOT tune on this data). Taker fee is charged as the CONSERVATIVE case — the real
strategy is a fee-free MAKER, so if the taker version clears the gate the maker version is strictly better; if even
the maker (fee=0) residual is <=0, the pond is dead.

    python scout_flb.py collect [--max 8000]     # resumable; caches to data/scout/polymarket_flb.db
    python scout_flb.py analyze                   # reliability diagram + the 3 gates (run anytime on what's cached)

VERDICT (2026-06-28, n=1384 resolved binary non-crypto Polymarket markets) — ABORT. The FLB tilt is REAL (textbook
reliability curve: longshots overpriced, favorites underpriced), and the favorite band's RAW signal is the strongest
this project has seen (+0.080 residual, win 97.7% vs 90.3% breakeven, raw cluster-p=0.006, CI excl 0). But it dies on
THREE independent disqualifiers, all surfaced for FREE in ~1h with zero capital:
  (a) LOSS-LIGHT: n_loss=3 in the favorite band → INSUFFICIENT (the exact degenerate-CI trap that killed the 5-min
      favorite-tail; 3 more losers flips it). Top-volume quintile n_loss=0. Cannot confirm the +0.08 isn't noise.
  (c) SHARP-CONVERGENCE COLLAPSE (the decisive gate): residual +0.080 at 24h → +0.0015 at the market's OWN 1h price;
      robust ex-FDV (+0.073 → +0.0018). The favorites are CALIBRATED at the sharp (late) price — the 24h "edge" is the
      price drifting up as resolution nears (informational latency), NOT a standing crowd bias a patient maker harvests.
  (+) LOOK-AHEAD contamination: entry was anchored on closedTime, which is OUTCOME-dependent for early-resolving
      markets ("hit $X before 2027" resolves YES at the trigger), inflating the raw 24h residual. Gate (c) is immune.
CONCLUSION: the FLB bias exists but is priced at the sharp horizon + loss-light + latency-driven = the same efficiency
wall, found cheaply. The new process WORKED: it caught a seductive +0.08/97.7%-win/p=0.006 false positive before a
cent. ABORT the Polymarket favorite-buy pond; scout the next checklist pond (combinatorial arb) if continuing.
"""
import argparse
import os
import sqlite3
import sys
import time

import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import feeds
from analysis import stats as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"
DB = os.path.join("data", "scout", "polymarket_flb.db")

# ---- LOCKED pre-registered constants ----
TAU_ENTRY = 24 * 3600     # causal entry: price this many seconds BEFORE resolution
TAU_LATE = 1 * 3600       # the market's own sharper late price (for the convergence control)
WINDOW = 3 * 3600         # tolerance window when picking the nearest price point
FAV_LO, FAV_HI = 0.80, 0.97   # favorite band (>=0.97 ~certain, adds nothing; <0.80 not a "favorite")
LONG_LO, LONG_HI = 0.03, 0.20  # longshot band (for the reliability picture)
MIN_VOL = 5000.0          # tradable / real price
MIN_LIFE = (TAU_ENTRY + WINDOW + 3600)   # market must have existed long enough for a 24h-before price

# crypto up/down + hourly/short-fuse markets are the EFFICIENT ones we already walled — exclude them
CRYPTO_SKIP = ("up or down", "updown", "-5m-", "higher or lower", "touch ")


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS markets(
        cond_id TEXT PRIMARY KEY, slug TEXT, question TEXT, event_id TEXT, category TEXT,
        yes_token TEXT, won_yes INTEGER, volume REAL, end_ts INTEGER,
        entry_price REAL, late_price REAL, fetched INTEGER DEFAULT 0)""")
    c.commit()
    return c


def _parse_ts(s):
    """Parse Polymarket timestamps: 'closedTime'='2024-11-06 15:17:41+00', 'endDate'='2024-11-05T12:00:00Z',
    'startDate'='2024-01-04T22:58:00Z'. Returns unix seconds (UTC) or None."""
    if not s:
        return None
    import datetime as dt
    s = s.strip().replace("Z", "").replace(" ", "T", 1)
    s = s.split("+")[0].split(".")[0]   # drop tz suffix + fractional seconds
    try:
        return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp())
    except Exception:
        return None


def _end_ts(m):
    """The ACTUAL resolution time: closedTime (markets can resolve EARLY, so endDate may be a far-future
    nominal date) with endDate as the fallback."""
    return _parse_ts(m.get("closedTime")) or _parse_ts(m.get("endDate"))


def _is_binary_resolved(m):
    import json as _j
    try:
        outs = _j.loads(m.get("outcomes") or "[]")
        ops = _j.loads(m.get("outcomePrices") or "[]")
        toks = _j.loads(m.get("clobTokenIds") or "[]")
    except Exception:
        return None
    if sorted([o.lower() for o in outs]) != ["no", "yes"] or len(toks) != 2:
        return None
    # outcomes order: [Yes, No] (Polymarket convention); won_yes from the Yes price
    yi = 0 if outs[0].lower() == "yes" else 1
    if ops[yi] not in ("0", "1") or ops[1 - yi] not in ("0", "1"):
        return None
    return toks[yi], int(ops[yi] == "1")


def collect(max_markets):
    c = init_db()
    seen = {r[0] for r in c.execute("SELECT cond_id FROM markets")}
    print(f"collect: {len(seen)} markets already cached; pulling resolved binary markets...")
    added = 0
    offset = 0
    PAGE = 100   # Gamma hard-caps the page at 100 regardless of limit
    while len(seen) + added < max_markets:
        url = (f"{GAMMA_MARKETS}?closed=true&limit={PAGE}&offset={offset}"
               f"&order=endDate&ascending=false")
        try:
            page = feeds._get_json(url)
        except Exception as e:
            print(f"  page offset={offset} err {type(e).__name__}; stopping pagination"); break
        if not page:
            print("  no more markets"); break
        offset += len(page)
        for m in page:
            cond = m.get("conditionId")
            if not cond or cond in seen:
                continue
            q = (m.get("question") or "") + " " + (m.get("slug") or "")
            if any(k in q.lower() for k in CRYPTO_SKIP):
                continue
            try:
                vol = float(m.get("volumeNum") or m.get("volume") or 0)
            except Exception:
                vol = 0.0
            if vol < MIN_VOL:
                continue
            end_ts = _end_ts(m)
            start_ts = _parse_ts(m.get("startDate"))
            if not end_ts or (start_ts and end_ts - start_ts < MIN_LIFE):
                continue
            b = _is_binary_resolved(m)
            if not b:
                continue
            yes_tok, won_yes = b
            ev = ""
            try:
                evs = m.get("events") or []
                ev = (evs[0].get("ticker") or evs[0].get("slug") or "") if evs else ""
            except Exception:
                pass
            c.execute("INSERT OR IGNORE INTO markets(cond_id,slug,question,event_id,category,yes_token,"
                      "won_yes,volume,end_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                      (cond, m.get("slug"), m.get("question"), ev, ev.split("-")[0] if ev else "",
                       yes_tok, won_yes, vol, end_ts))
            seen.add(cond); added += 1
        c.commit()
        print(f"  offset {offset}: cached {len(seen)+0} markets ({added} new this run)")
        if len(page) < PAGE:
            break
    # now fetch entry/late prices for any market lacking them
    rows = c.execute("SELECT cond_id,yes_token,end_ts FROM markets WHERE fetched=0").fetchall()
    print(f"fetching entry prices for {len(rows)} markets...")
    done = 0
    for cond, tok, end_ts in rows:
        ep = _price_at(tok, end_ts - TAU_ENTRY)
        lp = _price_at(tok, end_ts - TAU_LATE)
        c.execute("UPDATE markets SET entry_price=?, late_price=?, fetched=1 WHERE cond_id=?",
                  (ep, lp, cond))
        done += 1
        if done % 50 == 0:
            c.commit(); print(f"    priced {done}/{len(rows)}  (last entry={ep})")
        time.sleep(0.05)
    c.commit()
    print(f"collect done: {done} priced this run.")


def _price_at(token, target_ts):
    """Causal nearest price within WINDOW of target_ts (a price you could have traded at)."""
    try:
        h = feeds.fetch_price_history(token, target_ts - WINDOW, target_ts + WINDOW, fidelity=10)
    except Exception:
        return None
    if not h:
        return None
    t, p = min(h, key=lambda tp: abs(tp[0] - target_ts))
    return float(p) if abs(t - target_ts) <= WINDOW else None


def _reliability(price, won, lo=0.0, hi=1.0, bins=10):
    edges = np.linspace(lo, hi, bins + 1)
    out = []
    for i in range(bins):
        m = (price >= edges[i]) & (price < edges[i + 1])
        if m.sum() >= 10:
            out.append((0.5 * (edges[i] + edges[i + 1]), int(m.sum()), int(won[m].sum()),
                        float(won[m].mean()), float((won[m] - price[m]).mean())))
    return out


def analyze():
    c = init_db()
    rows = c.execute("SELECT entry_price, late_price, won_yes, volume, event_id FROM markets "
                     "WHERE fetched=1 AND entry_price IS NOT NULL").fetchall()
    if len(rows) < 50:
        print(f"only {len(rows)} priced markets cached — run `python scout_flb.py collect` first."); return
    price = np.array([r[0] for r in rows], float)
    late = np.array([r[1] if r[1] is not None else np.nan for r in rows], float)
    won = np.array([r[2] for r in rows], float)
    vol = np.array([r[3] for r in rows], float)
    ev = np.array([r[4] or "?" for r in rows])
    n = len(price)
    print(f"\nPOLYMARKET FLB RELIABILITY  (YES contracts, entry = price {TAU_ENTRY//3600}h before resolution)")
    print(f"  n={n} resolved binary non-crypto markets   overall Yes-rate {won.mean():.3f}   "
          f"events {len(np.unique(ev))}")
    print("=" * 92)
    print("  RELIABILITY DIAGRAM (the favorite-longshot curve):")
    print("    price-bin   n   won   win-rate   residual(won-price)   [FLB: favorites>0, longshots<0]")
    for mid, nn, k, wr, resid in _reliability(price, won, bins=10):
        flag = "  <- FAVORITE band" if mid >= FAV_LO else ("  <- longshot band" if mid <= LONG_HI else "")
        print(f"    {mid:.2f}      {nn:>4}  {k:>4}   {wr:.3f}      {resid:+.4f}{flag}")

    # --- GATE (a): favorite band through the fee-aware deflated gate ---
    fav = (price >= FAV_LO) & (price < FAV_HI)
    print(f"\n  GATE (a) FAVORITE band [{FAV_LO},{FAV_HI}): n={int(fav.sum())}  "
          f"mean price {price[fav].mean():.3f}  win {won[fav].mean():.3f}  "
          f"raw residual {(won[fav]-price[fav]).mean():+.4f}")
    a = S.assess(price[fav], won[fav], ev[fav], n_trials=20, label="FLB favorite-tail (taker, hold)")
    S.print_assess(a)

    # --- GATE (b): top-volume quintile ---
    if fav.sum() >= 20:
        thr = np.quantile(vol[fav], 0.8)
        hv = fav & (vol >= thr)
        print(f"\n  GATE (b) TOP-VOLUME QUINTILE of the favorite band (vol>={thr:,.0f}): n={int(hv.sum())}")
        if hv.sum() >= 10:
            b = S.assess(price[hv], won[hv], ev[hv], n_trials=20, label="FLB favorite, top-vol quintile")
            S.print_assess(b)
            print("    (if the edge VANISHES here vs the full band, it was illiquidity, not a harvestable bias)")
        else:
            print("    too few high-volume favorites yet — collect more.")

    # --- GATE (c): sharp-convergence control (24h residual vs the market's own 1h price) ---
    havel = fav & np.isfinite(late)
    if havel.sum() >= 20:
        r24 = (won[havel] - price[havel]).mean()
        r1 = (won[havel] - late[havel]).mean()
        print(f"\n  GATE (c) SHARP-CONVERGENCE control (favorites with a 1h-before price, n={int(havel.sum())}):")
        print(f"    residual at 24h (won-entry) {r24:+.4f}   vs  residual at 1h (won-late) {r1:+.4f}")
        print(f"    late price already moved toward the favorite by {(late[havel]-price[havel]).mean():+.4f} on avg")
        verdict = ("SURVIVES — favorite still underpriced at the market's OWN sharpest price (a standing bias)"
                   if r1 > 0.005 else
                   "COLLAPSES — the late price subsumes the edge = you were just early/slow, not beating a sharp price")
        print(f"    => {verdict}")

    print("\n  READ vs the 3 KILL-GATES: keep the pond alive only if (a) the favorite band SURVIVES the deflated")
    print("  fee-aware gate with n_loss>=30, (b) it SURVIVES the top-volume quintile, and (c) it does NOT collapse")
    print("  under sharp-convergence. Taker fee is charged here (conservative); the real play is a fee-free maker.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["collect", "analyze"])
    ap.add_argument("--max", type=int, default=8000, help="collect: cap total cached markets")
    args = ap.parse_args()
    if args.mode == "collect":
        collect(args.max)
    else:
        analyze()


if __name__ == "__main__":
    main()

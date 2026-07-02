"""COPY-TRADING TEST — can we copy consistently-profitable wallets on Polymarket CRYPTO markets? (the user's idea)

Reconstructs per-wallet realized PnL across many resolved crypto Up/Down markets from Polymarket's PUBLIC trade feed
(data-api.polymarket.com/trades), then runs the two decisive tests the copy-trading thesis must pass:
  (1) EXISTENCE   — are there wallets with many trades AND clearly positive PnL?
  (2) PERSISTENCE — split the period in half; does a wallet's EARLY PnL predict its LATE PnL? (Spearman rank corr)
      If NO persistence -> the "profitable" wallets are LUCKY (survivorship) -> copying them is copying soon-to-
      regress noise. Per the random-walk finding, crypto direction is unpredictable, so persistence SHOULD be ~0.
Plus a copyability read: are the top-PnL wallets net BUYERS-of-cheap-that-resolved-rich (directional, copyable) or
liquidity providers / sellers (maker-like, NOT copyable as a taker)?

PnL reconstruction (per wallet, per market): BUY outcome X @p size s -> cash -= p*s, shares[X]+=s; SELL -> cash+=p*s,
shares[X]-=s; at resolution cash += shares[winning_outcome]. (The feed reports one wallet+side per trade = the visible
copyable taker side.)

    python copytrade_test.py [--days 20] [--min-trades 15]

NOTE: a copier also pays the 0.07*(1-p) taker fee and fills AFTER the wallet (worse price) — so realized PnL here is
an OPTIMISTIC UPPER BOUND on a copier. If even the upper bound doesn't persist, copy-trading is dead.
"""
import argparse
import datetime as dt
import json
import sys
from collections import defaultdict

import numpy as np
from scipy import stats as ss

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
import feeds

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GE = "https://gamma-api.polymarket.com/events"
TRADES = "https://data-api.polymarket.com/trades"


def get(u):
    try:
        return feeds._get_json(u)
    except Exception:
        return None


def daily_markets(days):
    """Recent resolved daily BTC/ETH Up/Down markets: (cond_id, won_outcome, end_ts)."""
    out = []
    today = dt.datetime.now(dt.timezone.utc).date()
    for coin in ("bitcoin", "ethereum"):
        for d in range(1, days + 1):
            day = today - dt.timedelta(days=d)
            slug = f"{coin}-up-or-down-on-{day.strftime('%B').lower()}-{day.day}-{day.year}"
            e = get(f"{GE}?slug={slug}")
            if not isinstance(e, list) or not e:
                continue
            m = (e[0].get("markets") or [{}])[0]
            cond = m.get("conditionId")
            try:
                ops = json.loads(m.get("outcomePrices") or "[]")
                outs = json.loads(m.get("outcomes") or "[]")
            except Exception:
                continue
            if not cond or ops not in (["1", "0"], ["0", "1"]):
                continue
            won = outs[0] if ops[0] == "1" else outs[1]
            end = m.get("endDate")
            ets = int(dt.datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()) if end else 0
            out.append((cond, won, ets, slug))
    return out


def all_trades(cond, cap=6000):
    out = []
    off = 0
    while len(out) < cap:
        d = get(f"{TRADES}?market={cond}&limit=500&offset={off}")
        if not isinstance(d, list) or not d:
            break
        out += d
        off += len(d)
        if len(d) < 500:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--min-trades", type=int, default=15)
    args = ap.parse_args()

    print(f"gathering resolved daily BTC/ETH markets (last {args.days} days x2 coins)...")
    mkts = daily_markets(args.days)
    print(f"  {len(mkts)} resolved markets")
    if not mkts:
        print("no markets"); return
    mid_ts = np.median([m[2] for m in mkts])   # split early/late by market resolution time

    # per-wallet, per-half accumulators: cash + winning-share payout
    pnl_all = defaultdict(float); n_all = defaultdict(int)
    pnl_h = {0: defaultdict(float), 1: defaultdict(float)}; n_h = {0: defaultdict(int), 1: defaultdict(int)}
    buy_cheap_win = defaultdict(float); total_signed = defaultdict(float)
    ntr = 0
    for ci, (cond, won, ets, slug) in enumerate(mkts):
        tr = all_trades(cond)
        ntr += len(tr)
        half = 0 if ets <= mid_ts else 1
        # accumulate this market's per-wallet shares + cash
        cash = defaultdict(float); shares = defaultdict(lambda: defaultdict(float)); wn = defaultdict(int)
        for t in tr:
            try:
                w = t["proxyWallet"]; side = t["side"]; oc = t["outcome"]
                p = float(t["price"]); s = float(t["size"])
            except (KeyError, ValueError, TypeError):
                continue
            sgn = -1.0 if side == "BUY" else 1.0
            cash[w] += sgn * p * s
            shares[w][oc] += (-sgn) * s
            wn[w] += 1
            # copyability proxy: a BUY of the eventual WINNER at a cheap price = directional/copyable
            if side == "BUY" and oc == won:
                buy_cheap_win[w] += (1.0 - p) * s
            total_signed[w] += abs(p * s)
        for w in cash:
            pnl = cash[w] + shares[w][won] * 1.0
            pnl_all[w] += pnl; n_all[w] += wn[w]
            pnl_h[half][w] += pnl; n_h[half][w] += wn[w]
        if (ci + 1) % 10 == 0:
            print(f"  ...{ci+1}/{len(mkts)} markets, {ntr:,} trades")
    print(f"  total {ntr:,} trades across {len(pnl_all):,} distinct wallets")

    # (1) EXISTENCE
    active = {w: pnl_all[w] for w in pnl_all if n_all[w] >= args.min_trades}
    prof = {w: v for w, v in active.items() if v > 0}
    print(f"\n(1) EXISTENCE  (wallets with >= {args.min_trades} trades): n={len(active)}  "
          f"profitable={len(prof)} ({100*len(prof)/max(1,len(active)):.0f}%)  "
          f"median PnL ${np.median(list(active.values())):+.1f}  total ${sum(active.values()):+.0f} (zero-sum-ish minus fees)")
    top = sorted(active.items(), key=lambda kv: -kv[1])[:8]
    print("  top wallets by PnL:  (PnL$ | n_trades | buy-cheap-winner$ vs total$ = directional share)")
    for w, v in top:
        ds = buy_cheap_win[w] / max(1.0, total_signed[w])
        print(f"    {w[:14]}  ${v:+9.1f}  n{n_all[w]:>4}   dir-share {ds:.2f}")

    # (2) PERSISTENCE — early vs late PnL across wallets active (>=min/2) in BOTH halves
    both = [w for w in pnl_all if n_h[0][w] >= args.min_trades // 2 and n_h[1][w] >= args.min_trades // 2]
    print(f"\n(2) PERSISTENCE  (wallets active in BOTH halves: n={len(both)}):")
    if len(both) >= 10:
        e = np.array([pnl_h[0][w] for w in both]); l = np.array([pnl_h[1][w] for w in both])
        rho, p = ss.spearmanr(e, l)
        # does being a top-half-1 wallet predict positive half-2?
        topq = e >= np.quantile(e, 0.75)
        print(f"    Spearman corr(early PnL, late PnL) = {rho:+.3f}  (p={p:.3f})   "
              f"{'PERSISTS' if rho > 0.2 and p < 0.05 else 'NO PERSISTENCE = survivorship/luck'}")
        print(f"    top-quartile-early wallets' mean LATE PnL: ${l[topq].mean():+.1f}  vs rest ${l[~topq].mean():+.1f}")
    else:
        print("    too few two-half wallets; increase --days")

    print("\n  READ: copy-trading is alive ONLY if profitable wallets PERSIST (rho>0 sig) AND are directional/copyable")
    print("  (high dir-share). No persistence => luck/survivorship => copying = copying noise (the random-walk")
    print("  prediction). Even persistence is an UPPER BOUND: a real copier pays the fee + fills after them (worse).")


if __name__ == "__main__":
    main()

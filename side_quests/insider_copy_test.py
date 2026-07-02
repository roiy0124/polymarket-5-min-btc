"""INSIDER-COPY TEST — can you HUNT smart/insider wallets on Polymarket EVENT markets and COPY them? (user's idea)

This is NOT the crypto copy-test we already killed. That failed because the 5-min crypto outcome is a random walk
(no skill to copy -> nothing persists). EVENT markets are different: real information asymmetry exists, so genuinely-
informed wallets COULD exist to find -- and Polymarket is the one venue where every wallet/trade is public, so the
idea is cheaply + decisively testable on resolved history BEFORE risking a cent.

The thesis must clear THREE killers (built in as gates):
  (1) SURVIVORSHIP. Across thousands of wallets betting binaries, some look brilliant by LUCK. The only honest test is
      out-of-sample PERSISTENCE: identify "smart" wallets using ONLY the EARLY half of markets, then ask if they stay
      profitable in the LATE half (Spearman + copy-forward mean). No persistence => you'd be copying soon-to-regress
      noise (exactly what crypto showed).
  (2) FOLLOW-LAG / PRICE IMPACT (the killer specific to COPYING). Even a true insider buys at 0.40 and their trade
      moves a thin market to 0.55; you copy at 0.55 and get only the leftover. We measure BOTH:
        - "follow at THEIR price" (hold to resolution) = the upper bound (their entry informedness), AND
        - "follow at the REALISTIC fill" (next same-side trade price after theirs = the impact you eat).
      If even the upper bound fails the gate, copying is dead regardless of slippage.
  (3) MAKER-vs-DIRECTIONAL. Many top wallets are makers/arbs whose single legs you can't copy as a taker (what crypto
      showed). We characterize the persistent winners by dir-share (bought-cheap-winners $ / total $).

Event markets carry NO trading fee (the 0.07 was the crypto product), so the honest object is the FEE-FREE residual
(won - fill), gated by analysis.stats.deflated_resid_p (cluster by market, deflated for multiplicity, n_loss>=30).

Reuses: scout_flb's cached resolved-binary-event universe (data/scout/polymarket_flb.db) + copytrade_test.all_trades
(public data-api feed) + analysis.stats (the gate).

    python insider_copy_test.py pull   [--max-markets 700] [--cap 10000] [--vmin 10000] [--vmax 3000000]
    python insider_copy_test.py analyze [--min-half 6] [--smart-q 0.75]

Trades are cached to data/scout/insider_trades.db (resumable; re-run pull to extend). Only FULLY-captured markets
(n_trades < cap) are analyzed, because the feed is newest-first and a truncated market gives wrong reconstructed PnL.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict

import numpy as np
from scipy import stats as ss

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
from analysis import stats as S
from copytrade_test import all_trades

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UNIVERSE = os.path.join("data", "scout", "polymarket_flb.db")
TRADES_DB = os.path.join("data", "scout", "insider_trades.db")
BAND_LO, BAND_HI = 0.05, 0.95     # tradeable price band (drop near-resolved trivial fills)


# ----------------------------------------------------------------- pull (resumable trade cache)
def _open_trades_db():
    os.makedirs(os.path.dirname(TRADES_DB), exist_ok=True)
    c = sqlite3.connect(TRADES_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS mkt(
        cond_id TEXT PRIMARY KEY, won_yes INTEGER, end_ts INTEGER, volume REAL,
        n_trades INTEGER, capped INTEGER, trades TEXT)""")
    c.commit()
    return c


def pull(max_markets, cap, vmin, vmax):
    if not os.path.exists(UNIVERSE):
        print(f"no universe DB at {UNIVERSE}; run `python scout_flb.py collect` first."); return
    u = sqlite3.connect(UNIVERSE)
    rows = u.execute("SELECT cond_id, won_yes, end_ts, volume FROM markets "
                     "WHERE end_ts IS NOT NULL AND volume BETWEEN ? AND ? ORDER BY end_ts",
                     (vmin, vmax)).fetchall()
    # spread the sample across the whole time range (every k-th market) to populate both halves
    if len(rows) > max_markets:
        idx = np.linspace(0, len(rows) - 1, max_markets).round().astype(int)
        rows = [rows[i] for i in sorted(set(idx))]
    c = _open_trades_db()
    have = {r[0] for r in c.execute("SELECT cond_id FROM mkt")}
    todo = [r for r in rows if r[0] not in have]
    print(f"universe: {len(rows)} markets in vol band; {len(have)} already cached; pulling {len(todo)} ...")
    done = 0
    for cond, won_yes, end_ts, vol in todo:
        try:
            tr = all_trades(cond, cap=cap)
        except Exception as e:
            print(f"  {cond[:12]} err {type(e).__name__}; skip"); continue
        capped = 1 if len(tr) >= cap else 0
        # keep only the fields we need (shrink the blob)
        slim = [{"w": t.get("proxyWallet"), "s": t.get("side"), "o": t.get("outcome"),
                 "p": t.get("price"), "z": t.get("size"), "t": t.get("timestamp")}
                for t in tr]
        c.execute("INSERT OR REPLACE INTO mkt VALUES(?,?,?,?,?,?,?)",
                  (cond, won_yes, end_ts, vol, len(tr), capped, json.dumps(slim)))
        done += 1
        if done % 25 == 0:
            c.commit()
            full = c.execute("SELECT COUNT(*) FROM mkt WHERE capped=0").fetchone()[0]
            print(f"  pulled {done}/{len(todo)}  (cached full-history markets: {full})")
        time.sleep(0.03)
    c.commit()
    full = c.execute("SELECT COUNT(*) FROM mkt WHERE capped=0").fetchone()[0]
    capn = c.execute("SELECT COUNT(*) FROM mkt WHERE capped=1").fetchone()[0]
    print(f"pull done. cached {done} this run. fully-captured={full}  truncated(excluded)={capn}")


# ----------------------------------------------------------------- per-market PnL reconstruction
def _wallet_pnl(trades, won_str):
    """Realized PnL per wallet for one market (handles hedge/early-exit via cash flows + resolution payout).
    Returns dict w -> (pnl, n_trades, dir_$, tot_$). Also returns the raw per-trade rows for the follow test."""
    cash = defaultdict(float); sh = defaultdict(lambda: defaultdict(float)); nt = defaultdict(int)
    dirw = defaultdict(float); totw = defaultdict(float)
    for t in trades:
        w = t["w"]; side = t["s"]; oc = t["o"]
        try:
            p = float(t["p"]); z = float(t["z"])
        except (TypeError, ValueError):
            continue
        if not w or side not in ("BUY", "SELL"):
            continue
        sgn = -1.0 if side == "BUY" else 1.0
        cash[w] += sgn * p * z
        sh[w][oc] += (-sgn) * z
        nt[w] += 1
        totw[w] += abs(p * z)
        if side == "BUY" and oc == won_str:
            dirw[w] += (1.0 - p) * z
    out = {}
    for w in cash:
        pnl = cash[w] + sh[w][won_str] * 1.0
        out[w] = (pnl, nt[w], dirw[w], totw[w])
    return out


# ----------------------------------------------------------------- analyze
def analyze(min_half, smart_q):
    if not os.path.exists(TRADES_DB):
        print(f"no trade cache at {TRADES_DB}; run `python insider_copy_test.py pull` first."); return
    c = _open_trades_db()
    mkts = c.execute("SELECT cond_id, won_yes, end_ts, volume, trades FROM mkt WHERE capped=0").fetchall()
    print(f"{len(mkts)} fully-captured resolved binary EVENT markets")
    if len(mkts) < 40:
        print("too few markets; run `pull` with a larger --max-markets."); return
    ets = np.array([m[2] for m in mkts]); mid_ts = np.median(ets)

    # per-wallet, per-half accumulators
    pnl_h = {0: defaultdict(float), 1: defaultdict(float)}
    nt_h = {0: defaultdict(int), 1: defaultdict(int)}
    dir_h = {0: defaultdict(float), 1: defaultdict(float)}
    tot_h = {0: defaultdict(float), 1: defaultdict(float)}
    # late-half raw BUY trades per wallet (for the follow test), keyed by wallet
    late_buys = defaultdict(list)   # w -> list of (cond, price, size, won_dummy, next_same_side_price)

    total_trades = 0
    for cond, won_yes, end_ts, vol, blob in mkts:
        trades = json.loads(blob)
        total_trades += len(trades)
        won_str = "Yes" if won_yes == 1 else "No"
        half = 0 if end_ts <= mid_ts else 1
        wp = _wallet_pnl(trades, won_str)
        for w, (pnl, n, dw, tw) in wp.items():
            pnl_h[half][w] += pnl; nt_h[half][w] += n
            dir_h[half][w] += dw; tot_h[half][w] += tw
        if half == 1:
            # build follow-fill rows: for each BUY in band, the next same-side trade price after it (impact)
            tr_sorted = sorted(trades, key=lambda t: (t.get("t") or 0))
            for i, t in enumerate(tr_sorted):
                if t["s"] != "BUY":
                    continue
                try:
                    p = float(t["p"]); z = float(t["z"])
                except (TypeError, ValueError):
                    continue
                if not (BAND_LO <= p <= BAND_HI):
                    continue
                won_dummy = 1 if t["o"] == won_str else 0
                nxt = None
                for j in range(i + 1, min(i + 40, len(tr_sorted))):
                    tj = tr_sorted[j]
                    if tj["s"] == "BUY" and tj["o"] == t["o"]:
                        try:
                            nxt = float(tj["p"]); break
                        except (TypeError, ValueError):
                            pass
                late_buys[t["w"]].append((cond, p, z, won_dummy, nxt))

    # ---------- (1) EXISTENCE + PERSISTENCE (smart in EARLY half -> profitable in LATE half?) ----------
    both = [w for w in set(nt_h[0]) & set(nt_h[1]) if nt_h[0][w] >= min_half and nt_h[1][w] >= min_half]
    print(f"\n(1) PERSISTENCE  (wallets with >={min_half} trades in BOTH halves: n={len(both)}; "
          f"{total_trades:,} trades total)")
    if len(both) >= 10:
        e = np.array([pnl_h[0][w] for w in both]); l = np.array([pnl_h[1][w] for w in both])
        rho, pv = ss.spearmanr(e, l)
        verdict = "PERSISTS" if (rho > 0.15 and pv < 0.05) else "NO PERSISTENCE = luck/survivorship"
        print(f"    Spearman(early PnL, late PnL) = {rho:+.3f}  (p={pv:.3f})  => {verdict}")
        # copy-forward: pick smart wallets by EARLY half only, read their LATE half
        e_dir = np.array([dir_h[0][w] / max(1.0, tot_h[0][w]) for w in both])
        smart_thr = np.quantile(e, smart_q)
        smart = (e >= smart_thr) & (e_dir >= 0.4)            # top-PnL AND directional (copyable) in P1
        print(f"    'smart in EARLY' = top {int((1-smart_q)*100)}% P1 PnL AND dir-share>=0.4: n={int(smart.sum())}")
        if smart.sum() >= 5:
            print(f"      their mean LATE-half PnL: ${l[smart].mean():+,.0f}   "
                  f"vs the rest: ${l[~smart].mean():+,.0f}   "
                  f"({'follows through' if l[smart].mean() > 0 and l[smart].mean() > l[~smart].mean() else 'regresses'})")
            print(f"      late-half profitable rate among 'smart': {100*np.mean(l[smart] > 0):.0f}%  "
                  f"vs rest {100*np.mean(l[~smart] > 0):.0f}%")
    else:
        print("    too few two-half wallets; run pull with more markets.")
        smart, both = np.array([]), []

    # ---------- (2) FOLLOWABILITY (copy the EARLY-identified smart wallets' LATE trades) ----------
    print(f"\n(2) FOLLOWABILITY  (copy LATE-half BUYs of wallets identified smart from the EARLY half only):")
    smart_wallets = set(np.array(both)[smart].tolist()) if len(both) and smart.sum() else set()
    print(f"    following {len(smart_wallets)} smart wallets' late-half buys ...")
    rows = []   # (cond, their_price, realistic_fill, won_dummy)
    for w in smart_wallets:
        for cond, p, z, won_dummy, nxt in late_buys.get(w, []):
            fill = nxt if (nxt is not None and nxt >= p) else p     # you fill no better than them; impact only hurts
            rows.append((cond, p, fill, won_dummy))
    _follow_report("SMART-wallet late buys", rows)

    # control: follow ALL big late buys (size top-decile), regardless of wallet history (the naive 'whale-copy')
    print(f"\n(3) CONTROL — naive WHALE-COPY (follow ALL large late buys, no wallet vetting):")
    big = []
    sizes = [z for lst in late_buys.values() for (cond, p, z, wd, nxt) in lst]
    if sizes:
        zthr = np.quantile(sizes, 0.90)
        for lst in late_buys.values():
            for (cond, p, z, wd, nxt) in lst:
                if z >= zthr:
                    fill = nxt if (nxt is not None and nxt >= p) else p
                    big.append((cond, p, fill, wd))
        print(f"    big-buy size threshold (q0.90) = {zthr:,.0f} shares")
    _follow_report("big late buys (any wallet)", big)

    print("\n  READ: copying is ALIVE only if (1) smart wallets PERSIST early->late AND (2) the FOLLOW residual SURVIVES")
    print("  the gate at the REALISTIC fill (not just their price), with n_loss>=30. 'Their-price' is the upper bound;")
    print("  if even that fails, copying is dead. Event markets are FEE-FREE so the bar is just residual>0 after impact.")


def _follow_report(label, rows):
    if len(rows) < 30:
        print(f"    [{label}] too few rows (n={len(rows)}) -> INSUFFICIENT"); return
    conds = np.array([r[0] for r in rows])
    their = np.array([r[1] for r in rows], float)
    fill = np.array([r[2] for r in rows], float)
    won = np.array([r[3] for r in rows], float)
    n_loss = int((won == 0).sum())
    for tag, price in (("at THEIR price (upper bound)", their), ("at REALISTIC fill (impact)", fill)):
        resid = won - price
        mean, lo, hi, p1, pdef = S.deflated_resid_p(resid, conds, n_trials=20)
        ok = bool(np.isfinite(pdef) and pdef < 0.05 and lo > 0 and n_loss >= S.MIN_LOSS)
        v = "SURVIVES" if ok else ("INSUFFICIENT (n_loss<30)" if n_loss < S.MIN_LOSS else "FAILS")
        print(f"    [{label}] {tag}: n={len(rows)} (loss {n_loss})  win {100*won.mean():.1f}%  "
              f"mean resid {mean:+.4f}  CI[{lo:+.4f},{hi:+.4f}]  deflated-p {pdef:.3f}  => {v}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    pp = sub.add_parser("pull"); pp.add_argument("--max-markets", type=int, default=700)
    pp.add_argument("--cap", type=int, default=10000); pp.add_argument("--vmin", type=float, default=10000)
    pp.add_argument("--vmax", type=float, default=3000000)
    ap_an = sub.add_parser("analyze"); ap_an.add_argument("--min-half", type=int, default=6)
    ap_an.add_argument("--smart-q", type=float, default=0.75)
    args = ap.parse_args()
    if args.mode == "pull":
        pull(args.max_markets, args.cap, args.vmin, args.vmax)
    else:
        analyze(args.min_half, args.smart_q)


if __name__ == "__main__":
    main()

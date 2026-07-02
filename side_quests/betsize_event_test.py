"""BET-SIZE EDGE on NON-ROULETTE (event/prediction) markets — does the SIZE of a bet carry edge we can RELY on?

The user's question (refined): in NON-roulette fields (real-information EVENT markets — sports/politics/news,
NOT the 5-min crypto random walk) does the SIZE of a bet predict its price-beating residual, and is it a measure
we can rely on inside a copy-position SCORE?

DATA: the sibling whale-monitor DB (READ-ONLY): ~14.8M whale BUY/SELL TRADE rows on Polymarket EVENT markets joined
to 144k market_resolutions. NOTE the data is range-restricted to WHALES (already-large bettors), so this answers
"among large bettors, does even-bigger size = more edge" with a huge sample. The full small-vs-big contrast needs
full order flow (a separate fresh pull); see betsize_flow_pull.py.

HONEST OBJECT (quant + data-detective): the RESIDUAL of a BUY = (won?1:0) - price. Event markets are FEE-FREE so the
bar is residual>0 AFTER market(condition_id)-clustering, multiplicity-deflation, n_loss>=30. "Predicts the outcome"
(win-rate) is NOT the object: a 0.95 favorite wins 95% with zero edge.

TESTS:
  (0) terrain: counts, size distribution, overall residual, crypto-roulette exclusion.
  (1) SIZE -> RESIDUAL raw: residual by usdc_size quintile + Spearman/Pearson(log size, resid).
  (2) PRICE-CONTROLLED: same within price bands (joint-control vs the obviously-priced variable).
  (3) WITHIN-WALLET: demean resid & log-size within wallet -> does a wallet's OWN bigger bets beat its smaller ones?
      (isolates bet-SIZE conviction from wallet-SKILL — the cleanest "size = information" test).
  (4) FOLLOW-BIG gate: top size-decile BUYs -> S.deflated_resid_p, market-clustered. AT THEIR PRICE = the
      informedness UPPER BOUND (a copier fills no better; impact only hurts). If even this fails, size is unreliable.
  (5) BY CATEGORY: sports / politics / other -> is size informed where insiders are likelier?

    python betsize_event_test.py [--min-price 0.05] [--max-price 0.95] [--max-rows 4000000] [--B 4000]
"""
import argparse
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
from scipy import stats as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
from analysis import stats as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WHALE_DB = r"C:\Users\roiy0\Desktop\polymarket project\data\polymarket.db"
# short-fuse crypto "roulette" exclusion (the walled random-walk product)
SKIP = ["%up or down%", "%updown%", "%-5m-%", "%-1h-%", "%higher or lower%", "%touch %", "% dip to %"]


def connect():
    c = sqlite3.connect(f"file:{WHALE_DB.replace(os.sep, '/')}?mode=ro", uri=True, timeout=120)
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-200000")  # ~200MB page cache
    c.execute("CREATE TEMP TABLE res AS SELECT condition_id, winning_outcome_index "
              "FROM market_resolutions WHERE resolved=1 AND winning_outcome_index IS NOT NULL")
    c.execute("CREATE INDEX temp.ix_res ON res(condition_id)")
    return c


def categorize(title):
    t = (title or "").lower()
    if any(k in t for k in (" vs.", " vs ", "total sets", "o/u", "over/under", "moneyline", "spread",
                            "to win", "game ", "match", "score", "championship", "league", "cup ",
                            "nba", "nfl", "mlb", "nhl", "ufc", "atp", "wta", "soccer", "tennis")):
        return "sports"
    if any(k in t for k in ("election", "president", "senate", "governor", "primary", "nominee",
                            "parliament", "prime minister", "win the", "approval", "poll", "congress")):
        return "politics"
    if any(k in t for k in ("bitcoin", "ethereum", "btc", "eth", "solana", "price of", "$", "hit ",
                            "reach ", "all-time high", "ath")):
        return "crypto-priceLevel"
    return "other"


def gate(label, resid, conds, n_trials=200, B=2500, cap_rows=150_000, seed=3):
    """fee-free residual gate (event markets) via the rigor module. The cluster-bootstrap costs ~B*rows, so when
    rows are large we subsample WHOLE markets (preserves clustering; CI depends on #clusters, of which we keep
    thousands) to keep it fast and honest."""
    resid = np.asarray(resid, float); conds = np.asarray(conds)
    n = len(resid); n_loss = int((resid < 0).sum())  # a BUY 'loses' (won=0) iff resid = -price < 0
    if n < 30 or len(np.unique(conds)) < 5:
        print(f"    [{label}] n={n} too few -> INSUFFICIENT"); return None
    full_n, full_loss = n, n_loss
    if n > cap_rows:
        uniq = np.unique(conds); rng = np.random.default_rng(seed)
        rng.shuffle(uniq)
        keep, tot = set(), 0
        cnt = {}
        for cc, k in zip(*np.unique(conds, return_counts=True)):
            cnt[cc] = k
        for cc in uniq:
            keep.add(cc); tot += cnt[cc]
            if tot >= cap_rows:
                break
        msk = np.isin(conds, list(keep))
        resid, conds = resid[msk], conds[msk]
        n_loss = int((resid < 0).sum())
    mean, lo, hi, p1, pdef = S.deflated_resid_p(resid, conds, n_trials=n_trials, B=B)
    ok = bool(np.isfinite(pdef) and pdef < 0.05 and lo > 0 and n_loss >= S.MIN_LOSS)
    v = "SURVIVES" if ok else ("INSUFFICIENT (n_loss<30)" if n_loss < S.MIN_LOSS else "FAILS")
    sub = f" [boot on {len(resid):,} of {full_n:,}]" if full_n > cap_rows else ""
    print(f"    [{label}] n={full_n:,} (loss {full_loss:,}){sub}  mean resid {mean:+.4f}  "
          f"cluster-CI[{lo:+.4f},{hi:+.4f}]  deflated-p {pdef:.3f}  => {v}")
    return dict(mean=mean, lo=lo, hi=hi, pdef=pdef, n=full_n, n_loss=full_loss, ok=ok)


def quintile_table(size, resid, price, won, label="size"):
    qs = np.quantile(size, [0, .2, .4, .6, .8, 1.0])
    print(f"    {label} quintile           n        mean$       resid(won-price)   win    meanPrice")
    for i in range(5):
        m = (size >= qs[i]) & (size <= qs[i + 1]) if i == 4 else (size >= qs[i]) & (size < qs[i + 1])
        if m.sum() == 0:
            continue
        print(f"    Q{i+1} [{qs[i]:>8.0f},{qs[i+1]:>9.0f}]  {m.sum():>7,}  {size[m].mean():>9.0f}   "
              f"{resid[m].mean():>+8.4f}          {won[m].mean():.3f}  {price[m].mean():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-price", type=float, default=0.05)
    ap.add_argument("--max-price", type=float, default=0.95)
    ap.add_argument("--max-rows", type=int, default=4_000_000)
    ap.add_argument("--B", type=int, default=4000)
    args = ap.parse_args()

    if not os.path.exists(WHALE_DB):
        print(f"whale DB not found at {WHALE_DB}"); return
    c = connect()
    where_skip = " AND ".join([f"LOWER(a.title||' '||a.slug) NOT LIKE '{p}'" for p in SKIP])
    base = (f"FROM whale_activity a JOIN res r ON a.condition_id=r.condition_id "
            f"WHERE a.type='TRADE' AND a.side='BUY' AND a.outcome_index IS NOT NULL "
            f"AND a.price BETWEEN {args.min_price} AND {args.max_price} AND COALESCE(a.usdc_size,0)>0 "
            f"AND {where_skip}")

    print("counting filtered event BUY trades (resolved, non-roulette, price band) ...")
    n_tot, n_mkt = c.execute(f"SELECT COUNT(*), COUNT(DISTINCT a.condition_id) {base}").fetchone()
    print(f"  {n_tot:,} BUY trades across {n_mkt:,} markets")
    step = max(1, n_tot // args.max_rows)   # systematic subsample if huge (id % step == 0)
    samp = f" AND a.id % {step} = 0" if step > 1 else ""
    if step > 1:
        print(f"  subsampling 1/{step} (id%{step}==0) to cap ~{args.max_rows:,} rows for the in-memory analysis")

    print("  pulling rows ...")
    rows = c.execute(
        f"SELECT a.usdc_size, a.price, "
        f"(CASE WHEN a.outcome_index=r.winning_outcome_index THEN 1.0 ELSE 0.0 END) AS won, "
        f"a.condition_id, a.proxy_wallet, a.title, a.timestamp {base}{samp}").fetchall()
    print(f"  pulled {len(rows):,} rows")
    if len(rows) < 1000:
        print("too few; aborting"); return

    size = np.array([r[0] for r in rows], float)
    price = np.array([r[1] for r in rows], float)
    won = np.array([r[2] for r in rows], float)
    cond = np.array([r[3] for r in rows])
    wal = np.array([r[4] for r in rows])
    cat = np.array([categorize(r[5]) for r in rows])
    resid = won - price
    lsz = np.log(size + 1.0)

    print(f"\n(0) TERRAIN: {len(rows):,} BUY trades  {len(np.unique(cond)):,} markets  {len(np.unique(wal)):,} wallets")
    print(f"    overall win {won.mean():.3f}   mean residual {resid.mean():+.4f}   "
          f"(positive resid pooled = whales buy underpriced winners on average)")
    print(f"    size $: median {np.median(size):.0f}  mean {size.mean():.0f}  "
          f"p90 {np.quantile(size,.9):.0f}  p99 {np.quantile(size,.99):.0f}")
    print("    category mix:", {k: int((cat == k).sum()) for k in ("sports", "politics", "crypto-priceLevel", "other")})

    # ---------------- (1) SIZE -> RESIDUAL raw ----------------
    print("\n(1) SIZE -> RESIDUAL (raw, all event BUYs):")
    quintile_table(size, resid, price, won)
    print(f"    Spearman(size, resid) = {ss.spearmanr(size, resid)[0]:+.4f}   "
          f"Pearson(log size, resid) = {S.pearson(lsz, resid):+.4f}   (want >0 = bigger bets land beyond price)")

    # ---------------- (2) PRICE-CONTROLLED ----------------
    print("\n(2) PRICE-CONTROLLED (size->resid WITHIN price bands = joint-control vs the priced variable):")
    for lo, hi in ((0.05, 0.35), (0.35, 0.65), (0.65, 0.95)):
        m = (price >= lo) & (price < hi)
        if m.sum() < 1000:
            continue
        sp = ss.spearmanr(size[m], resid[m])[0]
        # top vs bottom size half within the band
        med = np.median(size[m])
        big = m & (size >= med); sml = m & (size < med)
        print(f"    price[{lo:.2f},{hi:.2f}): n={m.sum():>8,}  Spearman(size,resid)={sp:+.4f}  "
              f"resid big-half {resid[big].mean():+.4f} vs small-half {resid[sml].mean():+.4f}  "
              f"(Δ {resid[big].mean()-resid[sml].mean():+.4f})")

    # ---------------- (3) WITHIN-WALLET ----------------
    print("\n(3) WITHIN-WALLET (does a wallet's OWN bigger bets beat its smaller ones? isolates size from skill):")
    # demean resid & log-size within wallet, keep wallets with >=20 trades
    by = defaultdict(list)
    for i in range(len(rows)):
        by[wal[i]].append(i)
    dr, dz, keepc = [], [], []
    for w, idxs in by.items():
        if len(idxs) < 20:
            continue
        idxs = np.array(idxs)
        dr.append(resid[idxs] - resid[idxs].mean())
        dz.append(lsz[idxs] - lsz[idxs].mean())
        keepc.append(cond[idxs])
    if dr:
        dr = np.concatenate(dr); dz = np.concatenate(dz); keepc = np.concatenate(keepc)
        print(f"    wallets with >=20 trades contribute {len(dr):,} demeaned obs")
        print(f"    within-wallet Pearson(Δlog size, Δresid) = {S.pearson(dz, dr):+.4f}  "
              f"Spearman = {ss.spearmanr(dz, dr)[0]:+.4f}  (>0 = sizing-up conveys conviction/info)")
        # top vs bottom within-wallet size tercile
        hi_m = dz >= np.quantile(dz, 0.66); lo_m = dz <= np.quantile(dz, 0.34)
        print(f"    Δresid on a wallet's BIGGER-than-own-usual bets {dr[hi_m].mean():+.4f}  "
              f"vs its SMALLER {dr[lo_m].mean():+.4f}")
    else:
        print("    too few multi-trade wallets")

    # ---------------- (4) FOLLOW-BIG gate ----------------
    print("\n(4) FOLLOW-BIG gate (top size-decile BUYs, AT THEIR PRICE = upper bound; market-clustered, fee-free):")
    thr9 = np.quantile(size, 0.90); thr99 = np.quantile(size, 0.99)
    for lab, m in (("top size DECILE (q90)", size >= thr9),
                   ("top size PCTILE (q99) — the biggest", size >= thr99),
                   ("ALL event BUYs (baseline)", np.ones(len(size), bool))):
        gate(lab, resid[m], cond[m], B=args.B)

    # ---------------- (5) BY CATEGORY ----------------
    print("\n(5) BY CATEGORY — is size informed where insiders are likelier? (top size-decile, per category):")
    for k in ("sports", "politics", "crypto-priceLevel", "other"):
        m = (cat == k)
        if m.sum() < 1000:
            print(f"    {k}: too few"); continue
        sp = ss.spearmanr(size[m], resid[m])[0]
        bigm = m & (size >= np.quantile(size[m], 0.90))
        print(f"  {k}: n={m.sum():>8,}  Spearman(size,resid)={sp:+.4f}")
        gate(f"  {k} top-decile follow", resid[bigm], cond[bigm], B=args.B)

    print("\n  READ: bet size is a RELIABLE copy-input ONLY if (a) resid RISES with size (corr>0), (b) it survives")
    print("  WITHIN price band (not just a favorite/longshot artifact), (c) it survives WITHIN wallet (size=conviction,")
    print("  not just smart-wallet), and (d) the top-decile follow SURVIVES the clustered+deflated gate. This is the")
    print("  optimistic UPPER BOUND (at their price); a real copier fills after them (impact) so confirm on full flow.")


if __name__ == "__main__":
    main()

"""COPY-SCORE PROTOTYPE — the "smart indicator", computed on real data (read-only).

Demonstrates the redesign in SCORING-REDESIGN.md: promote the price-beating RESIDUAL to be the driver of who is
copyable, instead of the win-rate-flavored `whale.score`. Computes, per tracked wallet, the honest reliability score

    W_hat = shrink( $-weighted residual (won - entry_price), n )   gated by n_loss>=30 and copyable-style,
            trusted only to the degree EARLY residual predicts LATE (the persistence factor)

and shows: (1) how badly the current `score` ranks residual, (2) how many high-W_hat wallets the current
`eligible` rule excludes (the style->eligibility leak), (3) the NEW copyable ranking. Event markets, fee-free.

    python copy_score_proto.py [--min-n 40] [--shrink-k 30]
"""
import argparse
import os
import sqlite3
import sys

import numpy as np
from scipy import stats as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (moved into subfolder)
from analysis import stats as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WHALE_DB = r"C:\Users\roiy0\Desktop\polymarket project\data\polymarket.db"
SKIP = ["%up or down%", "%updown%", "%-5m-%", "%-1h-%", "%higher or lower%", "%touch %", "% dip to %"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=40, help="min resolved buys to score a wallet")
    ap.add_argument("--shrink-k", type=float, default=30.0)
    args = ap.parse_args()

    c = sqlite3.connect(f"file:{WHALE_DB.replace(os.sep, '/')}?mode=ro", uri=True, timeout=120)
    c.execute("PRAGMA temp_store=MEMORY"); c.execute("PRAGMA cache_size=-200000")
    c.execute("CREATE TEMP TABLE res AS SELECT condition_id, winning_outcome_index "
              "FROM market_resolutions WHERE resolved=1 AND winning_outcome_index IS NOT NULL")
    c.execute("CREATE INDEX temp.ix_res ON res(condition_id)")
    where_skip = " AND ".join([f"LOWER(a.title||' '||a.slug) NOT LIKE '{p}'" for p in SKIP])

    print("computing per-wallet residual (early/late halves, market counts) over resolved event BUYs ...")
    q = f"""
    WITH base AS (
      SELECT a.proxy_wallet w, a.timestamp ts, a.usdc_size usd, a.price p, a.condition_id cond,
        (CASE WHEN a.outcome_index=r.winning_outcome_index THEN 1.0 ELSE 0.0 END) won
      FROM whale_activity a JOIN res r ON a.condition_id=r.condition_id
      WHERE a.type='TRADE' AND a.side='BUY' AND a.outcome_index IS NOT NULL
        AND a.price BETWEEN 0.05 AND 0.95 AND COALESCE(a.usdc_size,0)>0 AND {where_skip}
    ), split AS (
      SELECT w, usd, p, won, cond, NTILE(2) OVER (PARTITION BY w ORDER BY ts) - 1 AS half FROM base
    )
    SELECT w,
      COUNT(*) n, COUNT(DISTINCT cond) nmkt, SUM(usd) usd,
      SUM(usd*(won-p))/SUM(usd) resid_wt, AVG(won-p) resid_eq,
      SUM(CASE WHEN won=0 THEN 1 ELSE 0 END) nloss,
      SUM(CASE WHEN half=0 THEN usd*(won-p) ELSE 0 END)/NULLIF(SUM(CASE WHEN half=0 THEN usd ELSE 0 END),0) e_resid,
      SUM(CASE WHEN half=1 THEN usd*(won-p) ELSE 0 END)/NULLIF(SUM(CASE WHEN half=1 THEN usd ELSE 0 END),0) l_resid,
      SUM(CASE WHEN half=0 THEN 1 ELSE 0 END) e_n, SUM(CASE WHEN half=1 THEN 1 ELSE 0 END) l_n
    FROM split GROUP BY w
    """
    rows = c.execute(q).fetchall()

    # current score/style/eligible from the whales table
    meta = {w: (sc, st, el) for (w, sc, st, el) in
            c.execute("SELECT proxy_wallet, score, style, eligible FROM whales")}

    W = []
    for (w, n, nmkt, usd, rwt, req, nloss, e_resid, l_resid, e_n, l_n) in rows:
        if n < args.min_n or rwt is None:
            continue
        what = rwt * n / (n + args.shrink_k)            # shrink toward 0 for low n
        sc, style, el = meta.get(w, (None, None, None))
        W.append(dict(w=w, n=n, nmkt=nmkt, usd=usd, resid=rwt, resid_eq=req, what=what, nloss=nloss,
                      e_resid=e_resid, l_resid=l_resid, e_n=e_n or 0, l_n=l_n or 0,
                      score=sc, style=style, eligible=bool(el)))
    print(f"  {len(W)} wallets with >= {args.min_n} resolved event buys\n")
    if len(W) < 20:
        print("too few; lower --min-n"); return

    what = np.array([x["what"] for x in W])
    resid = np.array([x["resid"] for x in W])
    score = np.array([x["score"] if x["score"] is not None else np.nan for x in W])
    nloss = np.array([x["nloss"] for x in W])
    elig = np.array([x["eligible"] for x in W])

    # (1) does the CURRENT score rank the residual?
    have = np.isfinite(score)
    print("(1) DOES THE CURRENT `score` RANK EDGE (residual)?")
    if have.sum() > 10:
        print(f"    Spearman(score, W_hat residual) = {ss.spearmanr(score[have], what[have])[0]:+.3f}   "
              f"(near 0 => score does NOT rank edge; the redesign replaces it)")

    # (2) the eligibility leak: high-W_hat wallets that are NOT currently eligible
    gated = np.array([x["nloss"] >= S.MIN_LOSS for x in W])     # n_loss>=30 (the honest gate)
    newcopyable = gated & (what > 0)
    print(f"\n(2) ELIGIBILITY LEAK — wallets that BEAT THE PRICE (W_hat>0, n_loss>=30) but are NOT 'eligible' today:")
    leak = [x for x in W if x["nloss"] >= S.MIN_LOSS and x["what"] > 0 and not x["eligible"]]
    leak.sort(key=lambda x: -x["what"])
    print(f"    {int(newcopyable.sum())} wallets are copyable under the NEW rule; "
          f"{int((newcopyable & ~elig).sum())} of them are EXCLUDED by the current `eligible` flag.")
    print(f"    top excluded high-edge wallets (the ones today's style->eligibility leak drops):")
    print(f"    {'wallet':14} {'n':>5} {'nmkt':>5} {'W_hat':>8} {'resid':>8} {'nloss':>6} {'score':>7} {'style':10}")
    for x in leak[:10]:
        print(f"    {x['w'][:12]+'..':14} {x['n']:>5} {x['nmkt']:>5} {x['what']:>+8.4f} {x['resid']:>+8.4f} "
              f"{x['nloss']:>6} {(x['score'] if x['score'] is not None else float('nan')):>7.3f} {str(x['style'])[:10]:10}")

    # (3) the NEW copyable ranking (top W_hat, gated) + their OOS late residual
    print(f"\n(3) NEW COPYABLE RANKING (top W_hat, n_loss>=30) — with OOS check (early->late residual):")
    elig_pool = [x for x in W if x["nloss"] >= S.MIN_LOSS and x["what"] > 0]
    elig_pool.sort(key=lambda x: -x["what"])
    print(f"    {'wallet':14} {'n':>5} {'W_hat':>8} {'resid':>8} {'early':>8} {'late':>8} {'nloss':>6} {'score':>7} {'elig?':5}")
    for x in elig_pool[:15]:
        er = x["e_resid"] if x["e_resid"] is not None else float("nan")
        lr = x["l_resid"] if x["l_resid"] is not None else float("nan")
        print(f"    {x['w'][:12]+'..':14} {x['n']:>5} {x['what']:>+8.4f} {x['resid']:>+8.4f} "
              f"{er:>+8.4f} {lr:>+8.4f} {x['nloss']:>6} "
              f"{(x['score'] if x['score'] is not None else float('nan')):>7.3f} {str(x['eligible']):5}")

    # pool-level OOS: do top-W_hat (by early) wallets stay positive late?
    both = [x for x in W if x["e_n"] >= 12 and x["l_n"] >= 12 and x["e_resid"] is not None and x["l_resid"] is not None]
    if len(both) >= 20:
        e = np.array([x["e_resid"] for x in both]); l = np.array([x["l_resid"] for x in both])
        rho, p = ss.spearmanr(e, l)
        topq = e >= np.quantile(e, 0.75)
        print(f"\n    OOS persistence (n={len(both)} wallets w/ both halves): Spearman(early,late resid) = {rho:+.3f} (p={p:.3f})")
        print(f"    top-quartile-EARLY wallets' LATE residual {np.mean(l[topq]):+.4f} vs rest {np.mean(l[~topq]):+.4f}  "
              f"=> trust factor should be {'MODEST' if rho>0.1 else 'LOW (shrink hard)'}")

    print("\n  READ: the redesign sorts/eligibilizes on W_hat (residual, shrunk, n_loss-gated), recovering the excluded")
    print("  high-edge wallets and dropping the favorite-buyers the win-rate score over-ranks. The OOS Spearman sets how")
    print("  much to TRUST W_hat: low => shrink hard + require large n (copy-persistence is weak, per the program).")


if __name__ == "__main__":
    main()

"""WHALE PERSISTENCE — does a wallet's PAST price-beating residual predict its FUTURE? (the "consistent performance"
parameter of the copy-score). The honest object is the residual (won - entry_price), market-clustered, split
WITHIN each wallet's own history (NTILE(2) by time) so we ask the actual copy question: if I rank wallets on their
EARLY residual, do they keep beating the price LATE?

Reads the sibling whale-monitor DB READ-ONLY. Event markets only (crypto roulette excluded), fee-free.

    python whale_persistence.py [--min-half 15]
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


def shrink(resid, n, k=30.0):
    return resid * n / (n + k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-half", type=int, default=15, help="min resolved buys per wallet-half")
    args = ap.parse_args()

    c = sqlite3.connect(f"file:{WHALE_DB.replace(os.sep, '/')}?mode=ro", uri=True, timeout=120)
    c.execute("PRAGMA temp_store=MEMORY"); c.execute("PRAGMA cache_size=-200000")
    c.execute("CREATE TEMP TABLE res AS SELECT condition_id, winning_outcome_index "
              "FROM market_resolutions WHERE resolved=1 AND winning_outcome_index IS NOT NULL")
    c.execute("CREATE INDEX temp.ix_res ON res(condition_id)")
    where_skip = " AND ".join([f"LOWER(a.title||' '||a.slug) NOT LIKE '{p}'" for p in SKIP])

    print("aggregating per-wallet EARLY/LATE residual (NTILE(2) within each wallet's own history)...")
    q = f"""
    WITH base AS (
      SELECT a.proxy_wallet w, a.timestamp ts, a.usdc_size usd, a.price p,
        (CASE WHEN a.outcome_index=r.winning_outcome_index THEN 1.0 ELSE 0.0 END) won
      FROM whale_activity a JOIN res r ON a.condition_id=r.condition_id
      WHERE a.type='TRADE' AND a.side='BUY' AND a.outcome_index IS NOT NULL
        AND a.price BETWEEN 0.05 AND 0.95 AND COALESCE(a.usdc_size,0)>0 AND {where_skip}
    ), split AS (
      SELECT w, usd, p, won, NTILE(2) OVER (PARTITION BY w ORDER BY ts) - 1 AS half FROM base
    )
    SELECT w, half, COUNT(*) n, SUM(usd) usd,
           SUM(usd*(won-p))/SUM(usd) resid_wt, AVG(won-p) resid_eq,
           SUM(CASE WHEN won=0 THEN 1 ELSE 0 END) nloss
    FROM split GROUP BY w, half
    """
    rows = c.execute(q).fetchall()
    d = {}
    for w, half, n, usd, rwt, req, nloss in rows:
        d.setdefault(w, {})[half] = dict(n=n, usd=usd, rwt=rwt, req=req, nloss=nloss)

    both = [w for w, h in d.items() if 0 in h and 1 in h
            and h[0]["n"] >= args.min_half and h[1]["n"] >= args.min_half]
    print(f"  {len(d)} wallets; {len(both)} with >= {args.min_half} resolved buys in BOTH halves\n")
    if len(both) < 20:
        print("too few; lower --min-half"); return

    e = np.array([d[w][0]["rwt"] for w in both])       # early $-wt residual
    l = np.array([d[w][1]["rwt"] for w in both])        # late  $-wt residual
    e_eq = np.array([d[w][0]["req"] for w in both])
    l_eq = np.array([d[w][1]["req"] for w in both])
    en = np.array([d[w][0]["n"] for w in both])
    e_sh = np.array([shrink(d[w][0]["rwt"], d[w][0]["n"]) for w in both])

    print("(A) PERSISTENCE — does EARLY residual predict LATE residual across wallets?")
    rho, p = ss.spearmanr(e, l); rho2, p2 = ss.spearmanr(e_eq, l_eq)
    print(f"    Spearman(early $-wt resid, late $-wt resid) = {rho:+.3f}  (p={p:.4f})")
    print(f"    Spearman(early eq-wt resid, late eq-wt resid) = {rho2:+.3f}  (p={p2:.4f})")
    print(f"    Pearson(early, late) = {S.pearson(e, l):+.3f}   n_wallets={len(both)}")
    print(f"    => {'PERSISTS (past residual predicts future)' if rho > 0.15 and p < 0.05 else 'WEAK/NO persistence (past residual barely predicts future)'}")

    print("\n(B) COPY-FORWARD — rank wallets on EARLY (shrunk) residual; read their LATE residual:")
    for qlab, qq in (("top decile", 0.90), ("top quartile", 0.75), ("top half", 0.50)):
        thr = np.quantile(e_sh, qq); top = e_sh >= thr
        late_top = l[top]; late_rest = l[~top]
        # $-weight the late residual by late usd for a portfolio read
        print(f"    {qlab:12} (early-resid>={thr:+.4f}, n={int(top.sum())}): "
              f"LATE mean $-wt resid {np.mean(late_top):+.4f}  vs rest {np.mean(late_rest):+.4f}  "
              f"({'follows through' if np.mean(late_top) > max(0, np.mean(late_rest)) else 'regresses'})")

    print("\n(C) DECAY — by how much does the edge shrink early->late (top-quartile-early wallets)?")
    thr = np.quantile(e_sh, 0.75); top = e_sh >= thr
    print(f"    top-quartile-early: early $-wt resid {np.mean(e[top]):+.4f}  ->  late {np.mean(l[top]):+.4f}  "
          f"(retained {100*np.mean(l[top])/max(1e-9, np.mean(e[top])):.0f}% of the edge)")
    print(f"    bottom-quartile-early: early {np.mean(e[e_sh <= np.quantile(e_sh,0.25)]):+.4f} -> "
          f"late {np.mean(l[e_sh <= np.quantile(e_sh,0.25)]):+.4f}")

    print("\n  READ: a wallet's residual is a RELIABLE copy-input only to the degree EARLY predicts LATE. If Spearman")
    print("  is small (<~0.15) the right design SHRINKS hard toward 0 and needs large n — past performance is mostly")
    print("  regression-to-mean (the OOS copy-persistence wall). The shrink factor n/(n+30) encodes exactly this.")


if __name__ == "__main__":
    main()

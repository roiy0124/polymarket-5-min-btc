"""Data-quality audit — is the collector capturing reliably and often enough?

Checks: liveness now, time-coverage gaps (downtime / restarts), per-window
completeness, missing 5-min windows, sampling cadence, and WebSocket-freeze gaps.

    python -m analysis.data_quality
"""

import time
from datetime import datetime, timezone

from . import panel


def utc(ts):
    return "-" if ts is None else datetime.fromtimestamp(float(ts), tz=timezone.utc)\
        .strftime("%m-%d %H:%M:%S")


def q1(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def gap_stats(conn, table, tscol):
    """(n, span, max_gap, count>2s, count>5s, count>30s, downtime_sec) using LAG."""
    n = q1(conn, f"SELECT COUNT(*) FROM {table}")
    if not n or n < 2:
        return n or 0, 0, 0, 0, 0, 0, 0
    lo = q1(conn, f"SELECT MIN({tscol}) FROM {table}")
    hi = q1(conn, f"SELECT MAX({tscol}) FROM {table}")
    base = (f"SELECT {tscol} - LAG({tscol}) OVER (ORDER BY {tscol}) AS d "
            f"FROM {table}")
    mx = q1(conn, f"SELECT MAX(d) FROM ({base})")
    g2 = q1(conn, f"SELECT COUNT(*) FROM ({base}) WHERE d > 2")
    g5 = q1(conn, f"SELECT COUNT(*) FROM ({base}) WHERE d > 5")
    g30 = q1(conn, f"SELECT COUNT(*) FROM ({base}) WHERE d > 30")
    downtime = q1(conn, f"SELECT COALESCE(SUM(d-1),0) FROM ({base}) WHERE d > 2")
    return n, hi - lo, mx, g2, g5, g30, downtime


def main():
    conn = panel.connect()
    now = time.time()

    print("=" * 64)
    print("DATA-QUALITY AUDIT")
    print("=" * 64)

    # --- liveness ------------------------------------------------------------
    last = q1(conn, "SELECT MAX(ts) FROM snapshots")
    print(f"\n[LIVE NOW?]")
    print(f"  last snapshot: {utc(last)} UTC  ({now-last:.1f}s ago)  "
          f"-> {'OK' if now-last < 5 else 'STALLED?'}")
    for tbl, col in (("snapshots", "ts"), ("book_events", "recv_ts"),
                     ("trades", "recv_ts"), ("price_ticks", "recv_ts")):
        try:
            c = q1(conn, f"SELECT COUNT(*) FROM {tbl} WHERE {col} > ?", (now - 60,))
            print(f"  {tbl:>12}: {c:>6} rows in last 60s  ({c/60:.1f}/s)")
        except Exception:
            print(f"  {tbl:>12}: (table missing)")

    # --- snapshot coverage + downtime ---------------------------------------
    n, span, mx, g2, g5, g30, downtime = gap_stats(conn, "snapshots", "ts")
    print(f"\n[REST SNAPSHOT COVERAGE]  (target ~1/sec)")
    if span:
        hours = span / 3600
        cov = n / span * 100  # ~snapshots per second as %
        print(f"  rows: {n:,}  span: {hours:.1f}h  avg cadence: {span/n:.2f}s/snapshot")
        print(f"  gaps >2s: {g2}   >5s: {g5}   >30s: {g30}   largest gap: {mx:.0f}s")
        print(f"  est. downtime (sum of gaps): {downtime/60:.1f} min "
              f"({downtime/span*100:.2f}% of span)")
        # top 5 gaps
        rows = conn.execute(
            "SELECT t, d FROM (SELECT ts t, ts - LAG(ts) OVER (ORDER BY ts) d "
            "FROM snapshots) WHERE d > 5 ORDER BY d DESC LIMIT 5").fetchall()
        if rows:
            print("  largest stalls:")
            for t, d in rows:
                print(f"    {utc(t)} UTC  gap {d:.0f}s")

    # --- per-window completeness --------------------------------------------
    print(f"\n[PER-WINDOW COMPLETENESS]  (a full window ~300-350 snapshots)")
    perwin = conn.execute(
        "SELECT window_start, COUNT(*) c FROM snapshots GROUP BY window_start").fetchall()
    counts = sorted(c for _, c in perwin)
    if counts:
        nwin = len(counts)
        med = counts[nwin // 2]
        thin = sum(1 for c in counts if c < 250)
        print(f"  windows with snapshots: {nwin}   per-window min/median/max: "
              f"{counts[0]}/{med}/{counts[-1]}")
        print(f"  thin windows (<250 snaps, partial/joined or downtime): {thin}")
    nostrike = q1(conn, "SELECT COUNT(*) FROM windows WHERE strike_binance IS NULL")
    nofinal = q1(conn, "SELECT COUNT(*) FROM windows WHERE final_binance IS NULL "
                       "AND window_end < ?", (now,))
    settled = q1(conn, "SELECT COUNT(*) FROM windows WHERE resolved_outcome IS NOT NULL")
    totwin = q1(conn, "SELECT COUNT(*) FROM windows")
    print(f"  windows total: {totwin}   settled: {settled}   "
          f"missing strike: {nostrike}   missing final (closed): {nofinal}")

    # --- missing 5-min windows ----------------------------------------------
    ws = [r[0] for r in conn.execute(
        "SELECT DISTINCT window_start FROM windows ORDER BY window_start")]
    missing = []
    for a, b in zip(ws, ws[1:]):
        step = b - a
        if step != 300:
            missing.append((a, b, step // 300 - 1))
    print(f"\n[WINDOW SEQUENCE]  ({len(ws)} windows tracked)")
    if not missing:
        print("  no gaps — every consecutive 5-min window was captured.")
    else:
        tot = sum(m[2] for m in missing)
        print(f"  {len(missing)} sequence breaks, ~{tot} missing windows:")
        for a, b, k in missing[:6]:
            print(f"    after {utc(a)} UTC -> next {utc(b)} ({k} window(s) skipped)")

    # --- cadence in the tail (where it matters most) ------------------------
    tail = q1(conn, "SELECT COUNT(*) FROM snapshots WHERE time_left <= 20")
    tailwin = q1(conn, "SELECT COUNT(DISTINCT window_start) FROM snapshots WHERE time_left <= 20")
    if tailwin:
        print(f"\n[TAIL CADENCE]  (last 20s of each window, target ~0.3s)")
        print(f"  {tail} snapshots across {tailwin} windows = {tail/tailwin:.0f}/window "
              f"(~{20*tailwin/tail:.2f}s each; 20s/0.3 ~ 66 ideal)")

    # --- WS freeze detection -------------------------------------------------
    print(f"\n[WEBSOCKET HEALTH]")
    for tbl in ("book_events", "trades", "price_ticks"):
        try:
            n2, span2, mx2, _, g5b, g30b, _ = gap_stats(conn, tbl, "recv_ts")
            if span2:
                print(f"  {tbl:>12}: {n2:,} rows, {n2/span2:.1f}/s avg, "
                      f"largest silence {mx2:.0f}s (gaps>30s: {g30b})")
        except Exception:
            print(f"  {tbl:>12}: (missing)")
    print("\n(>120s book_events silence would indicate the documented WS freeze; the")
    print(" ws_collector watchdog reconnects at 120s and REST snapshots cover the gap.)")
    conn.close()


if __name__ == "__main__":
    main()

"""Walk-forward OUT-OF-SAMPLE backtest (experiment, not in the menu).

Tests the hypothesis: with a denser-dot / lower-ROI / still-positive-EV config and
30-min signal refresh, do FRESHLY generated signals actually pay -- on data they
were never fit on? This is the deliberate version of the accidental test we ran
overnight, with NO look-ahead:

  * Generate signals AS-OF a past time T using only windows that closed before T
    (lookbacks 6h/12h/24h measured backward from T).
  * Trade the next REFRESH_MIN minutes of windows with those signals, filling
    against the REAL recorded trade prints via the same RiskAverse PaperBroker the
    live path uses.
  * Step forward REFRESH_MIN and re-fit. Repeat across the last SIM_HOURS hours.

Every leg is stamped with the generation that produced it, so each refresh is its
own epoch. Because we trade only the 30 min after each fit, every leg's signal age
is < REFRESH_MIN -- this isolates "are fresh signals profitable?" from decay.

    python experiment_walkforward.py                       # defaults below
    python experiment_walkforward.py --min-frac 0.4 --min-roi 0.1 --min-ev 0.05 \
        --sim-hours 10 --refresh-min 30

Reads historical data directly from the DB with the most resolved windows (the
archive in old_dbs/ after a reset). Writes walkforward_trades.csv. Read-only on data.

CAVEATS (honest): the RiskAverse sim is optimistic on adverse selection; ~2 days of
data is small; every config you try is a multiple-comparison -- treat a single
positive run as suggestive, not proof.
"""

import os
import csv
import glob
import argparse
import sqlite3

from analysis.signals import (load, dots_for, find_signal, map_admit_threshold,
                              LOOKBACKS)
from analysis.backtest import queue_ahead
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "btc_updown.db")
OLD_DBS = os.path.join(HERE, "old_dbs")
OUT_CSV = os.path.join(HERE, "walkforward_trades.csv")
WINDOW = 300.0


def pick_db():
    """The DB with the most resolved windows (the archive, after a reset)."""
    cands = [DB_PATH] + sorted(glob.glob(os.path.join(OLD_DBS, "*.db")))
    best, best_n = None, -1
    for p in cands:
        if not os.path.exists(p):
            continue
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            n = c.execute("SELECT COUNT(*) FROM windows WHERE resolved_outcome "
                          "IN ('Up','Down')").fetchone()[0]
            c.close()
        except sqlite3.Error:
            n = -1
        if n > best_n:
            best, best_n = p, n
    return best, best_n


def open_merged():
    """Attach EVERY source DB (live + all archives) read-only and expose UNION views
    so unqualified `windows`/`snapshots`/`trades`/`book_events` queries see ALL data
    continuously. Fixes the post-reset split where new data lives in a separate DB
    from the archive. Returns (conn, [db paths])."""
    dbs = []
    for p in [DB_PATH] + sorted(glob.glob(os.path.join(OLD_DBS, "*.db"))):
        if not os.path.exists(p):
            continue
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            n = c.execute("SELECT COUNT(*) FROM windows WHERE resolved_outcome "
                          "IN ('Up','Down')").fetchone()[0]
            c.close()
        except sqlite3.Error:
            n = 0
        if n > 0:
            dbs.append(p)
    conn = sqlite3.connect("file::memory:", uri=True)
    for i, p in enumerate(dbs):
        conn.execute(f"ATTACH DATABASE 'file:{os.path.abspath(p)}?mode=ro' AS db{i}")
    for tbl in ("windows", "snapshots", "trades", "book_events"):
        union = " UNION ALL ".join(f"SELECT * FROM db{i}.{tbl}" for i in range(len(dbs)))
        conn.execute(f"CREATE TEMP VIEW {tbl} AS {union}")
    return conn, dbs


def generate_signals(windows, cuts, cfg):
    """Replicate analysis.signals.main's assembly, but on a TIME-BOUNDED window set
    and cuts relative to the as-of time. Returns a ranked signal list."""
    lo = max(1, int(round(cfg["min_entry"] * 100)))
    longest_cut = cuts[-1][1]
    cached, totals = {}, []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d = dots_for(windows, side, cent)
            cached[(side, cent)] = d
            totals.append(sum(1 for dd in d if dd[2] >= longest_cut))
    admit = map_admit_threshold(totals)
    sigs = []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d = cached[(side, cent)]
            if sum(1 for dd in d if dd[2] >= longest_cut) < admit:
                continue
            z = cent / 100.0
            sig = find_signal(d, z, cuts, cfg["min_win"], cfg["min_roi"],
                              cfg["min_dots"], cfg["min_frac"], cfg["alpha"], cfg["power"])
            if sig and sig["ev"] > cfg["min_ev"]:
                sig.update({"side": side, "entry": z, "shares": round(cfg["usd"] / z, 2)})
                sigs.append(sig)
    sigs.sort(key=lambda s: -s["ev"])
    return sigs


def replay_leg(conn, ws, token, side, sig, outcome, scfg):
    """Rest a paper BUY at the signal's entry for its buy-window, replay the real
    trade prints, auto-sell at target, settle remainder at the official outcome.
    Returns (filled, pnl) or None if the order was rejected / no token."""
    if not token:
        return None
    z, T = sig["entry"], sig["sell"]
    place_ts = ws + sig["t1"] * 60.0
    cancel_ts = ws + sig["t2"] * 60.0
    end_ts = ws + WINDOW
    broker = PaperBroker(scfg)
    mgr = OrderManager(broker, scfg, logger=lambda m: None)
    qa = queue_ahead(conn, token, z, place_ts)
    order = mgr.place_entry(token, price=z, size=sig["shares"], exit_price=T,
                            window_start=ws, queue_ahead=qa)
    if order.status.value == "REJECTED":
        return None
    canceled = False
    for price, sz, tside, rts in conn.execute(
            "SELECT price, size, side, recv_ts FROM trades WHERE asset_id=? AND "
            "recv_ts>=? AND recv_ts<=? ORDER BY recv_ts", (token, place_ts, end_ts)):
        if not canceled and rts > cancel_ts and order.filled_size <= 1e-9:
            mgr.cancel(order.intent.client_id)
            canceled = True
        if price is None or sz is None:
            continue
        broker.on_trade(token, float(price), float(sz), tside)
    won = (side == "up" and outcome == "Up") or (side == "down" and outcome == "Down")
    payout = 1.0 if won else 0.0
    pos = broker.position.get(token, 0.0)
    pnl = broker.realized_pnl + pos * payout - broker.cost.get(token, 0.0)
    return (order.filled_size > 1e-9, pnl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-frac", type=float, default=0.40, dest="min_frac",
                    help="min dot-SHARE of the map a buy-window must hold (was 0.20)")
    ap.add_argument("--min-roi", type=float, default=0.10, dest="min_roi",
                    help="min ROI floor (was 0.30)")
    ap.add_argument("--min-ev", type=float, default=0.05, dest="min_ev",
                    help="min confidence-adjusted EV/$1 (must stay > 0)")
    ap.add_argument("--min-win", type=float, default=0.70, dest="min_win")
    ap.add_argument("--min-dots", type=int, default=8, dest="min_dots")
    ap.add_argument("--min-entry", type=float, default=0.10, dest="min_entry")
    ap.add_argument("--usd", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.80)
    ap.add_argument("--sim-hours", type=float, default=10.0, dest="sim_hours")
    ap.add_argument("--refresh-min", type=float, default=30.0, dest="refresh_min")
    ap.add_argument("--lookbacks", default="6,12,24",
                    help="comma-separated lookback HOURS for the robustness check "
                         "(e.g. '8,12,16' to drop stale >16h data). Longest = primary sample.")
    args = ap.parse_args()
    cfg = vars(args)
    lb_hours = sorted(float(x) for x in args.lookbacks.split(","))
    lb_set = [(f"{h:g}h", h * 3600.0) for h in lb_hours]

    db, nres = pick_db()
    if not db or nres <= 0:
        print("no DB with resolved windows found.")
        return
    print(f"data DB: {os.path.basename(db)}  ({nres} resolved windows)")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    windows = load(conn)
    tokens = {ws: (tu, td) for ws, tu, td in conn.execute(
        "SELECT window_start, token_up, token_down FROM windows "
        "WHERE token_up IS NOT NULL")}
    outcomes = {w["ws"]: w["outcome"] for w in windows}
    if not windows:
        print("no windows loaded.")
        return

    all_ws = sorted(w["ws"] for w in windows)
    t_end = all_ws[-1] + WINDOW
    t_start = t_end - args.sim_hours * 3600
    refresh = args.refresh_min * 60.0
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)

    print(f"walk-forward: {args.sim_hours:g}h, refresh {args.refresh_min:g}min, "
          f"lookbacks={args.lookbacks}h, "
          f"config min_frac={args.min_frac} min_roi={args.min_roi} min_ev={args.min_ev} "
          f"min_win={args.min_win}")
    print("=" * 84)
    print(f"  {'gen (HH:MM)':>11} {'sigs':>4} {'legs':>4} {'fill':>5} {'win':>5} "
          f"{'pnl':>8} {'cumPnl':>9}")

    rows_out = []
    cum = 0.0
    tot_legs = tot_fill = tot_win = 0
    tot_stake_fill = 0.0
    import time as _t
    T = t_start
    while T < t_end:
        past = [w for w in windows if w["ws"] + WINDOW <= T]
        cuts = [(name, T - secs) for name, secs in lb_set]
        sigs = generate_signals(past, cuts, cfg) if past else []
        traded = [ws for ws in all_ws if T <= ws < T + refresh and ws + WINDOW <= t_end]
        g_legs = g_fill = g_win = 0
        g_pnl = 0.0
        for ws in traded:
            outcome = outcomes.get(ws)
            if outcome not in ("Up", "Down"):
                continue
            tu, td = tokens.get(ws, (None, None))
            for s in sigs:
                token = tu if s["side"] == "up" else td
                r = replay_leg(conn, ws, token, s["side"], s, outcome, scfg)
                if r is None:
                    continue
                filled, pnl = r
                g_legs += 1
                g_pnl += pnl
                if filled:
                    g_fill += 1
                    tot_stake_fill += s["shares"] * s["entry"]
                    if pnl > 1e-9:
                        g_win += 1
                rows_out.append({"gen_ts": round(T, 1), "window_start": ws,
                                 "side": s["side"], "entry": s["entry"], "sell": s["sell"],
                                 "filled": int(filled), "pnl": round(pnl, 4),
                                 "ev_pred": round(s["ev"], 4)})
        cum += g_pnl
        tot_legs += g_legs
        tot_fill += g_fill
        tot_win += g_win
        hhmm = _t.strftime("%H:%M", _t.localtime(T))
        wr = (g_win / g_fill * 100) if g_fill else 0
        print(f"  {hhmm:>11} {len(sigs):>4} {g_legs:>4} {g_fill:>5} {wr:>4.0f}% "
              f"{g_pnl:>+8.2f} {cum:>+9.2f}")
        T += refresh

    conn.close()
    if rows_out:
        with open(OUT_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
            w.writeheader()
            w.writerows(rows_out)

    print("=" * 84)
    fillpct = (tot_fill / tot_legs * 100) if tot_legs else 0
    winpct = (tot_win / tot_fill * 100) if tot_fill else 0
    ev_fill = (cum / tot_stake_fill) if tot_stake_fill > 0 else 0.0
    print(f"OVERALL: legs {tot_legs}  filled {tot_fill} ({fillpct:.0f}%)  "
          f"win {tot_win}/{tot_fill} ({winpct:.0f}%)  total PnL {cum:+.2f}  "
          f"EV/$1-on-fill {ev_fill:+.2f}")
    print(f"  (out-of-sample: every leg traded on windows AFTER its signal was fit)")
    print(f"  detail -> {os.path.basename(OUT_CSV)}")


if __name__ == "__main__":
    main()

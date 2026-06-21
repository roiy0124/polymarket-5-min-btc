"""Per-period config brute-force (experiment, not in the menu).

Question: should the signal config be STATIC or DYNAMIC? Split the last 20h into
four 5h blocks. For each block, brute-force (research lookback x line-config) and
keep the combo that best TRADES that block (signals generated at block start from
the lookback = data strictly before the block; no look-ahead). Then compare the
four winners: if the best config is stable across blocks, static is plausible; if
it jumps around, either it's regime-dependent or it's noise -- we then look for a
cause.

    python experiment_config_sweep.py

Grids (edit constants to widen): lookback {4,6,8,12,16,24}h x min_frac {0.20,0.35,
0.50} x min_roi {0.05,0.10,0.20}; min_ev fixed > 0. Fills use the SAME RiskAverse
PaperBroker as live. Reads the DB with the most resolved windows (the archive).

HONEST CAVEAT: per-block argmax over ~54 combos on ~60 windows is heavy multiple-
comparisons -- the winners' PnL is overfit/optimistic. The SIGNAL is the stability
pattern of the winning config, not its PnL. Differences are only meaningful if they
are large AND line up with a real market variable.
"""

import os
import csv
import time
import sqlite3
import argparse
import statistics
import itertools

from analysis.signals import load, dots_for, find_signal, map_admit_threshold
from analysis.backtest import queue_ahead
from exec_engine.config import SafetyConfig
from exec_engine.broker import PaperBroker
from exec_engine.order_manager import OrderManager
from experiment_walkforward import open_merged

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "config_sweep.csv")
WINDOW = 300.0

# grids
LOOKBACKS_H = [4, 6, 8, 12, 16, 24]
FRACS = [0.20, 0.35, 0.50]
ROIS = [0.05, 0.10, 0.20]
MIN_EV, MIN_WIN, MIN_DOTS, MIN_ENTRY, USD, ALPHA, POWER = 0.05, 0.70, 8, 0.10, 2.0, 0.05, 0.80
# a fixed reference config tracked across blocks -> clean regime signal (the
# per-block ARGMAX is noisy, especially on small blocks; this is the honest read)
REF = (12, 0.35, 0.10)   # (lookback_h, min_frac, min_roi)


def market_conditions(conn, bs, be):
    """Per-block: avg spread, avg BTC 5-min range/window, avg trade volume/window."""
    snaps = conn.execute("SELECT window_start, up_spread, down_spread, btc_binance "
                         "FROM snapshots WHERE ts>=? AND ts<? AND up_mid IS NOT NULL",
                         (bs, be)).fetchall()
    if not snaps:
        return (0.0, 0.0, 0.0)
    spr = statistics.mean([((s[1] or 0) + (s[2] or 0)) / 2 for s in snaps])
    byw = {}
    for ws, _, _, btc in snaps:
        if btc:
            byw.setdefault(ws, []).append(btc)
    rng = statistics.mean([max(v) - min(v) for v in byw.values() if len(v) > 1]) if byw else 0
    nwin = max(1, len(byw))
    vol = conn.execute("SELECT COALESCE(SUM(size),0) FROM trades WHERE recv_ts>=? AND "
                       "recv_ts<?", (bs, be)).fetchone()[0]
    return (spr, rng, vol / nwin)


def compute_maps(windows, longest_cut):
    """Dots per (side,cent) + the per-map admission floor. Depends only on the data
    window (block + lookback), so we cache it across configs."""
    lo = max(1, int(round(MIN_ENTRY * 100)))
    cached, totals = {}, []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d = dots_for(windows, side, cent)
            cached[(side, cent)] = d
            totals.append(sum(1 for dd in d if dd[2] >= longest_cut))
    return cached, map_admit_threshold(totals)


def fit_signals(cached, admit, cut, frac, roi):
    lo = max(1, int(round(MIN_ENTRY * 100)))
    cuts = [cut]
    sigs = []
    for side in ("up", "down"):
        for cent in range(lo, 50):
            d = cached[(side, cent)]
            if sum(1 for dd in d if dd[2] >= cut[1]) < admit:
                continue
            z = cent / 100.0
            sig = find_signal(d, z, cuts, MIN_WIN, roi, MIN_DOTS, frac, ALPHA, POWER)
            if sig and sig["ev"] > MIN_EV:
                sig.update({"side": side, "entry": z, "shares": round(USD / z, 2)})
                sigs.append(sig)
    return sigs


def replay(ws, token, side, sig, outcome, scfg, trades, qa):
    z, T = sig["entry"], sig["sell"]
    place_ts, cancel_ts = ws + sig["t1"] * 60.0, ws + sig["t2"] * 60.0
    broker = PaperBroker(scfg)
    mgr = OrderManager(broker, scfg, logger=lambda m: None)
    order = mgr.place_entry(token, price=z, size=sig["shares"], exit_price=T,
                            window_start=ws, queue_ahead=qa)
    if order.status.value == "REJECTED":
        return None
    canceled = False
    for price, sz, tside, rts in trades:
        if rts < place_ts:
            continue
        if not canceled and rts > cancel_ts and order.filled_size <= 1e-9:
            mgr.cancel(order.intent.client_id)
            canceled = True
        if price is None or sz is None:
            continue
        broker.on_trade(token, float(price), float(sz), tside)
    won = (side == "up" and outcome == "Up") or (side == "down" and outcome == "Down")
    pos = broker.position.get(token, 0.0)
    pnl = broker.realized_pnl + pos * (1.0 if won else 0.0) - broker.cost.get(token, 0.0)
    return (order.filled_size > 1e-9, pnl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim-hours", type=float, default=20.0, dest="sim_hours")
    ap.add_argument("--block-hours", type=float, default=5.0, dest="block_hours")
    ap.add_argument("--end-ts", type=float, default=None, dest="end_ts",
                    help="pin the window end (unix ts); default = latest window. Use the "
                         "same value for two runs to compare block sizes on identical data.")
    args = ap.parse_args()
    sim_hours, block_hours = args.sim_hours, args.block_hours
    conn, dbs = open_merged()
    if not dbs:
        print("no DB with resolved windows.")
        return
    nres = conn.execute("SELECT COUNT(*) FROM windows WHERE resolved_outcome "
                        "IN ('Up','Down')").fetchone()[0]
    print(f"data: {len(dbs)} db(s) merged, {nres} resolved windows")
    windows = load(conn)
    tokens = {ws: (tu, td) for ws, tu, td in conn.execute(
        "SELECT window_start, token_up, token_down FROM windows WHERE token_up IS NOT NULL")}
    outcomes = {w["ws"]: w["outcome"] for w in windows}
    all_ws = sorted(w["ws"] for w in windows)
    t_end = args.end_ts if args.end_ts else all_ws[-1] + WINDOW
    print(f"window: {time.strftime('%m-%d %H:%M', time.localtime(t_end - sim_hours*3600))} "
          f"-> {time.strftime('%m-%d %H:%M', time.localtime(t_end))} (end_ts={t_end:.0f})")
    scfg = SafetyConfig(min_order_usd=0.5, max_order_usd=1e9)

    n_blocks = int(round(sim_hours / block_hours))
    trade_cache, qa_cache = {}, {}     # (ws,token)->trades ; (token,int ts)->queue

    def get_trades(ws, token):
        key = (ws, token)
        if key not in trade_cache:
            trade_cache[key] = conn.execute(
                "SELECT price, size, side, recv_ts FROM trades WHERE asset_id=? AND "
                "recv_ts>=? AND recv_ts<=? ORDER BY recv_ts",
                (token, ws, ws + WINDOW)).fetchall()
        return trade_cache[key]

    def get_qa(token, price, place_ts):
        key = (token, round(price, 2), int(place_ts))
        if key not in qa_cache:
            qa_cache[key] = queue_ahead(conn, token, price, place_ts)
        return qa_cache[key]

    rows, winners = [], []
    for b in range(n_blocks):
        b_start = t_end - sim_hours * 3600 + b * block_hours * 3600
        b_end = b_start + block_hours * 3600
        block_ws = [ws for ws in all_ws if b_start <= ws < b_end and ws + WINDOW <= t_end]
        label = time.strftime("%m-%d %H:%M", time.localtime(b_start))
        print(f"\n=== Block {b+1}/{n_blocks}  {label}  ({len(block_ws)} windows) ===")
        replay_memo = {}
        best = None
        ref_rec = None
        for lb in LOOKBACKS_H:
            cut = (f"{lb}g", b_start - lb * 3600.0)
            past = [w for w in windows if w["ws"] + WINDOW <= b_start and w["ws"] >= cut[1]]
            if not past:
                continue
            cached, admit = compute_maps(past, cut[1])
            for frac, roi in itertools.product(FRACS, ROIS):
                sigs = fit_signals(cached, admit, cut, frac, roi)
                legs = fills = wins = 0
                pnl = stake = 0.0
                for ws in block_ws:
                    outcome = outcomes.get(ws)
                    if outcome not in ("Up", "Down"):
                        continue
                    tu, td = tokens.get(ws, (None, None))
                    for s in sigs:
                        token = tu if s["side"] == "up" else td
                        if not token:
                            continue
                        mk = (ws, s["side"], round(s["entry"], 2), round(s["sell"], 2),
                              s["t1"], s["t2"])
                        if mk not in replay_memo:
                            qa = get_qa(token, s["entry"], ws + s["t1"] * 60.0)
                            replay_memo[mk] = replay(ws, token, s["side"], s, outcome,
                                                     scfg, get_trades(ws, token), qa)
                        r = replay_memo[mk]
                        if r is None:
                            continue
                        filled, lpnl = r
                        legs += 1
                        pnl += lpnl
                        if filled:
                            fills += 1
                            stake += s["shares"] * s["entry"]
                            if lpnl > 1e-9:
                                wins += 1
                ev_fill = (pnl / stake) if stake > 0 else 0.0
                wr = (wins / fills) if fills else 0.0
                rec = {"block": b + 1, "block_start": label, "lookback_h": lb,
                       "min_frac": frac, "min_roi": roi, "n_signals": len(sigs),
                       "legs": legs, "fills": fills, "win_rate": round(wr, 3),
                       "pnl": round(pnl, 2), "ev_fill": round(ev_fill, 3)}
                rows.append(rec)
                if (lb, frac, roi) == REF:
                    ref_rec = rec
                # rank by ev_fill, require some fills so it's not an empty winner
                key = (ev_fill, pnl) if fills >= 5 else (-9, -9)
                if best is None or key > best[0]:
                    best = (key, rec)
        spr, rng, vol = market_conditions(conn, b_start, b_end)
        if best:
            w = dict(best[1])
            w["ref_ev"] = ref_rec["ev_fill"] if ref_rec else None
            w["ref_win"] = ref_rec["win_rate"] if ref_rec else None
            w["ref_pnl"] = ref_rec["pnl"] if ref_rec else None
            w["spread"], w["btc_rng"], w["vol"] = round(spr, 3), round(rng, 1), round(vol, 0)
            winners.append(w)
            refev = w["ref_ev"] if w["ref_ev"] is not None else 0.0
            refpnl = w["ref_pnl"] if w["ref_pnl"] is not None else 0.0
            print(f"  BEST: lb={w['lookback_h']}h frac={w['min_frac']} roi={w['min_roi']} "
                  f"EV/fill={w['ev_fill']:+.2f} pnl={w['pnl']:+.2f} win={w['win_rate']:.0%} | "
                  f"REF EV/fill={refev:+.2f} pnl={refpnl:+.2f} | vol/win={w['vol']:.0f} "
                  f"btc_rng={w['btc_rng']:.0f}")
    conn.close()

    if rows:
        with open(OUT_CSV, "w", newline="") as f:
            wcsv = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wcsv.writeheader()
            wcsv.writerows(rows)

    print("\n" + "=" * 108)
    print(f"PER BLOCK: best-config (argmax, NOISY) vs fixed REF{REF} (clean) | EV, PnL, conditions")
    print(f"  {'blk':>3} {'start':>11} {'bestEV':>7} {'bestPnl':>8} {'REF_EV':>7} "
          f"{'REF_pnl':>8} {'cumREF':>8} {'REF_win':>7} {'vol/win':>8} {'btc_rng':>7}")
    cumref = 0.0
    for w in winners:
        refev = w["ref_ev"] if w["ref_ev"] is not None else 0.0
        refwin = w["ref_win"] if w["ref_win"] is not None else 0.0
        refpnl = w["ref_pnl"] if w["ref_pnl"] is not None else 0.0
        cumref += refpnl
        print(f"  {w['block']:>3} {w['block_start']:>11} {w['ev_fill']:>+7.2f} "
              f"{w['pnl']:>+8.2f} {refev:>+7.2f} {refpnl:>+8.2f} {cumref:>+8.2f} "
              f"{refwin:>6.0%} {w['vol']:>8.0f} {w['btc_rng']:>7.0f}")
    print(f"\n  full grid -> {os.path.basename(OUT_CSV)}")
    print("  REF columns = one fixed config across blocks (the clean regime/PnL signal);")
    print("  best* = argmax-overfit. cumREF = running PnL of the fixed config.")


if __name__ == "__main__":
    main()

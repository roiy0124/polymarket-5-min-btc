"""Live local dashboard for the BTC up/down collector. Zero dependencies.

    python viewer.py            # serves http://127.0.0.1:8765  (Ctrl-C to stop)
    python viewer.py 9000       # custom port

Open the URL in a browser. The page auto-refreshes every few seconds and shows:
overall + live activity stats, the current live window, recent settled windows
(strike/final/outcome), and the latest trade prints. Read-only — safe to run
while both collectors are writing.
"""

import os
import sys
import time
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import coins
DB_PATH = coins.live_db("btc")
REFRESH_SECONDS = 5


def _utc(ts):
    if ts is None:
        return "-"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _hm(ts):
    if ts is None:
        return "-"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%H:%M:%S")


def _num(v, nd=2):
    return "-" if v is None else f"{v:.{nd}f}"


def _db_size_mb():
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(DB_PATH + suffix)
        except OSError:
            pass
    return total / 1e6


def _q1(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def gather():
    """Return a dict of everything the page needs (or an error string)."""
    if not os.path.exists(DB_PATH):
        return {"error": f"database not found at {DB_PATH} — start collector.py first"}
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        now = time.time()
        d = {"now": now, "error": None}
        d["snapshots"] = _q1(conn, "SELECT COUNT(*) FROM snapshots") or 0
        d["windows"] = _q1(conn, "SELECT COUNT(*) FROM windows") or 0
        d["settled"] = _q1(conn, "SELECT COUNT(*) FROM windows WHERE resolved_outcome IS NOT NULL") or 0
        # WS activity (range counts on indexed recv_ts are fast even on huge tables)
        for key, table, span in (("book_60s", "book_events", 60),
                                  ("trade_300s", "trades", 300),
                                  ("btc_60s", "btc_ticks", 60)):
            try:
                d[key] = _q1(conn, f"SELECT COUNT(*) FROM {table} WHERE recv_ts > ?", (now - span,)) or 0
                d[key + "_total"] = _q1(conn, f"SELECT MAX(id) FROM {table}") or 0
            except sqlite3.OperationalError:
                d[key] = d[key + "_total"] = None
        d["db_mb"] = _db_size_mb()

        # live window = latest snapshot
        d["live"] = conn.execute(
            """SELECT ts_utc, window_start, time_left, up_bid, up_ask, up_mid,
                      down_mid, btc_binance, btc_pyth
               FROM snapshots ORDER BY ts DESC LIMIT 1""").fetchone()

        # outcome split
        d["outcomes"] = dict(conn.execute(
            "SELECT resolved_outcome, COUNT(*) FROM windows "
            "WHERE resolved_outcome IS NOT NULL GROUP BY resolved_outcome").fetchall())

        # recent windows
        d["recent_windows"] = conn.execute(
            """SELECT window_start, strike_binance, final_binance, our_outcome,
                      resolved_outcome, partial
               FROM windows ORDER BY window_start DESC LIMIT 20""").fetchall()

        # asset -> Up/Down map for labeling trades
        amap = {}
        for ws_start, up, down in conn.execute(
                "SELECT window_start, token_up, token_down FROM windows").fetchall():
            if up:
                amap[up] = "Up"
            if down:
                amap[down] = "Down"
        d["amap"] = amap
        try:
            d["recent_trades"] = conn.execute(
                """SELECT recv_ts, asset_id, price, size, side
                   FROM trades ORDER BY recv_ts DESC LIMIT 20""").fetchall()
        except sqlite3.OperationalError:
            d["recent_trades"] = []
        return d
    finally:
        conn.close()


CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#0d1117; color:#c9d1d9; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }
.wrap { max-width:1100px; margin:0 auto; padding:24px; }
h1 { font-size:20px; margin:0 0 4px; color:#f0f6fc; }
.sub { color:#8b949e; font-size:12px; margin-bottom:20px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }
.card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:14px; }
.card .k { color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
.card .v { font-size:22px; font-weight:600; color:#f0f6fc; margin-top:4px; }
.card .v small { font-size:12px; color:#8b949e; font-weight:400; }
.live { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px 18px; margin-bottom:24px; }
.live .row { display:flex; flex-wrap:wrap; gap:24px; align-items:baseline; }
.live .big { font-size:30px; font-weight:700; color:#58a6ff; }
.live .lbl { color:#8b949e; font-size:11px; text-transform:uppercase; }
h2 { font-size:14px; color:#f0f6fc; margin:24px 0 8px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:right; padding:6px 10px; border-bottom:1px solid #21262d; }
th { color:#8b949e; font-weight:500; font-size:11px; text-transform:uppercase; }
td:first-child,th:first-child { text-align:left; }
.up { color:#3fb950; } .down { color:#f85149; }
.tag { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px; font-weight:600; }
.tag.up { background:rgba(63,185,80,.15); } .tag.down { background:rgba(248,81,73,.15); }
.err { background:#21262d; border:1px solid #f85149; border-radius:8px; padding:16px; color:#f85149; }
.dot { height:8px;width:8px;border-radius:50%;background:#3fb950;display:inline-block;margin-right:6px;
       animation:pulse 1.6s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
"""


def _card(k, v):
    return f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>'


def render(d):
    if d.get("error"):
        return f'<div class="wrap"><h1>BTC Up/Down — Records</h1><div class="err">{d["error"]}</div></div>'

    # cards
    cards = [
        _card("Windows", d["windows"]),
        _card("Settled", d["settled"]),
        _card("REST snapshots", f'{d["snapshots"]:,}'),
        _card("Book events <small>/60s</small>",
              "-" if d["book_60s"] is None else f'{d["book_60s"]:,}'),
        _card("Trades <small>/5m</small>",
              "-" if d["trade_300s"] is None else f'{d["trade_300s"]:,}'),
        _card("BTC ticks <small>/60s</small>",
              "-" if d["btc_60s"] is None else f'{d["btc_60s"]:,}'),
        _card("DB size", f'{d["db_mb"]:.0f} <small>MB</small>'),
    ]
    o = d["outcomes"]
    if o:
        cards.append(_card("Resolved", f'<span class="up">{o.get("Up",0)}↑</span> '
                                       f'<span class="down">{o.get("Down",0)}↓</span>'))
    cards_html = '<div class="cards">' + "".join(cards) + "</div>"

    # live window
    lv = d["live"]
    if lv:
        ts_utc, wstart, tleft, ubid, uask, umid, dmid, bnc, pyth = lv
        live_html = f"""<div class="live">
          <div class="lbl">Live window &nbsp; {_utc(wstart)} UTC &nbsp;→&nbsp; resolves {_hm((wstart or 0)+300)}</div>
          <div class="row" style="margin-top:8px">
            <div><div class="lbl">Time left</div><div class="big">{_num(tleft,0)}s</div></div>
            <div><div class="lbl">Up bid / ask / mid</div><div class="big">{_num(ubid)} / {_num(uask)} / {_num(umid)}</div></div>
            <div><div class="lbl">Down mid</div><div class="big">{_num(dmid)}</div></div>
            <div><div class="lbl">BTC binance / pyth</div><div class="big">{_num(bnc,1)} / {_num(pyth,1)}</div></div>
          </div>
          <div class="sub" style="margin:8px 0 0">last snapshot: {ts_utc}</div>
        </div>"""
    else:
        live_html = '<div class="live">no snapshots yet — is collector.py running?</div>'

    # recent windows table
    rw = ['<h2>Recent windows</h2><table><tr><th>Window (UTC)</th><th>Strike</th>'
          '<th>Final</th><th>Ours</th><th>Official</th><th>Partial</th></tr>']
    for ws_start, strike, final, ours, official, partial in d["recent_windows"]:
        def tag(x):
            if x == "Up":
                return '<span class="tag up">Up</span>'
            if x == "Down":
                return '<span class="tag down">Down</span>'
            return "-"
        rw.append(f'<tr><td>{_utc(ws_start)}</td><td>{_num(strike,1)}</td>'
                  f'<td>{_num(final,1)}</td><td>{tag(ours)}</td><td>{tag(official)}</td>'
                  f'<td>{"yes" if partial else ""}</td></tr>')
    rw.append("</table>")

    # recent trades table
    tr = ['<h2>Recent trades</h2><table><tr><th>Time (UTC)</th><th>Outcome</th>'
          '<th>Side</th><th>Price</th><th>Size</th></tr>']
    amap = d["amap"]
    for recv_ts, asset, price, size, side in d["recent_trades"]:
        outcome = amap.get(asset, "?")
        ocls = "up" if outcome == "Up" else ("down" if outcome == "Down" else "")
        scls = "up" if side == "BUY" else ("down" if side == "SELL" else "")
        tr.append(f'<tr><td>{_hm(recv_ts)}</td><td class="{ocls}">{outcome}</td>'
                  f'<td class="{scls}">{side or "-"}</td><td>{_num(price)}</td>'
                  f'<td>{_num(size)}</td></tr>')
    tr.append("</table>")

    updated = datetime.fromtimestamp(d["now"], tz=timezone.utc).strftime("%H:%M:%S")
    return (f'<div class="wrap"><h1>BTC Up/Down — Records</h1>'
            f'<div class="sub"><span class="dot"></span>live · updated {updated} UTC · '
            f'auto-refresh {REFRESH_SECONDS}s</div>'
            + cards_html + live_html + "".join(rw) + "".join(tr) + "</div>")


def page():
    try:
        d = gather()
    except Exception as e:
        d = {"error": f"{type(e).__name__}: {e}"}
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">'
            f'<title>BTC Up/Down Records</title><style>{CSS}</style></head>'
            f'<body>{render(d)}</body></html>')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # quiet


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"viewer -> http://127.0.0.1:{port}   (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

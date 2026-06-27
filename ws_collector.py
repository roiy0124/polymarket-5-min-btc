"""Real-time WebSocket capture for the BTC up/down 5-minute markets.

This is the high-fidelity half of the hybrid architecture (see CLAUDE.md):

  * Polymarket CLOB *market channel* (public, no auth) -> every order-book
    event: full `book` snapshots, incremental `price_change` deltas, trade
    prints (`last_trade_price`), and `tick_size_change` resets.
  * Binance `@bookTicker` -> event-driven BTC best bid/ask on every change
    (proxy for the gated Chainlink settlement price).

It runs ALONGSIDE collector.py (the REST poller), which stays as the redundant
fallback — the market WS has a documented "silent freeze" mode where it stays
TCP/PING-healthy but stops sending data, so we never rely on it alone. A
data-inactivity watchdog here force-reconnects after INACTIVITY_TIMEOUT seconds.

Writes to the same btc_updown.db (tables: book_events, trades, price_ticks).
Raw event JSON is stored verbatim so the book can be reconstructed exactly
offline. Run:  python ws_collector.py   (Ctrl-C to stop)

Requires the `websockets` package (pip install -r requirements.txt).
"""

import json
import time
import asyncio
import argparse
from collections import deque
from datetime import datetime, timezone

import websockets

import coins
import feeds
import storage

# ---- config -----------------------------------------------------------------
# DB path + Binance stream are per-coin (resolved in main() from --coin).
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
BINANCE_WS_T = "wss://stream.binance.com:9443/ws/{}@bookTicker"
CHAINLINK_WS = "wss://ws-live-data.polymarket.com"   # Polymarket RTDS = the ACTUAL settlement oracle
WINDOW_SECONDS = 300
INACTIVITY_TIMEOUT = 20.0      # reconnect market WS after this many seconds of silence
PROACTIVE_RECONNECT = 60.0     # also cycle the market WS this often to pre-empt freezes
FLUSH_INTERVAL = 0.5           # how often buffered rows are committed to SQLite
PING_INTERVAL = 15.0
RECONNECT_BACKOFF = 2.0
# auto-retention: roll the high-volume WS tables off after this many days so the
# DB file plateaus instead of growing forever. trades/windows/snapshots are kept
# forever (see storage.prune_ws). Lower RETAIN_DAYS if disk is tight.
RETAIN_DAYS = 3.0
PRUNE_INTERVAL = 1800.0        # how often to run the prune (seconds)
# -----------------------------------------------------------------------------


def utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


def cur_window(ts):
    return int(ts // WINDOW_SECONDS * WINDOW_SECONDS)


class State:
    def __init__(self):
        self.running = True
        self.coin = "btc"
        self.db_path = None
        self.binance_ws = None
        self.market_ws = None
        # last two windows -> their (up, down) token ids; keeps the just-closed
        # window subscribed so we still capture tail trades after rollover.
        self.windows = deque(maxlen=2)        # [(window_start, (up, down)), ...]
        self.asset_window = {}                # asset_id -> window_start
        self.active_assets = []               # token ids currently subscribed
        self.cur_window = None
        # buffers (appended on the event loop, drained by the flusher)
        self.book_buf = []
        self.trade_buf = []
        self.btc_buf = []
        self.stats = {"book": 0, "trade": 0, "btc": 0, "chainlink": 0, "reconnects": 0, "proactive": 0}


def _subscribe_msg(assets):
    return json.dumps({"assets_ids": assets, "type": "market"})


async def _resubscribe(state):
    """Send the full current asset set on the live market connection."""
    if state.market_ws is not None and state.active_assets:
        try:
            await state.market_ws.send(_subscribe_msg(state.active_assets))
        except Exception:
            pass


# ---- window discovery -------------------------------------------------------

async def window_manager(state):
    """Every second: detect the live window, fetch its token ids, and keep the
    market-channel subscription pointed at the current (+ just-closed) window."""
    while state.running:
        now = time.time()
        start = cur_window(now)
        if start != state.cur_window:
            state.cur_window = start
            market = None
            for _ in range(3):
                try:
                    market = await asyncio.to_thread(feeds.fetch_market, start, state.coin)
                except Exception:
                    market = None
                if market:
                    break
                await asyncio.sleep(0.5)
            if market:
                up, down = market["token_up"], market["token_down"]
                state.windows.append((start, (up, down)))
                # rebuild active set + asset->window map from the live deque
                state.asset_window = {}
                assets = []
                for ws_start, (u, d) in state.windows:
                    state.asset_window[u] = ws_start
                    state.asset_window[d] = ws_start
                    assets += [u, d]
                state.active_assets = assets
                await _resubscribe(state)
                print(f"[{time.strftime('%H:%M:%S')}] ws subscribed window {start} "
                      f"({len(assets)} assets)", flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ws: market {start} not ready, "
                      f"will retry", flush=True)
        await asyncio.sleep(1.0)


# ---- market channel ---------------------------------------------------------

def _handle_market_event(state, ev, recv_ts, recv_utc):
    if not isinstance(ev, dict):
        return
    etype = ev.get("event_type")
    asset = ev.get("asset_id")
    win = state.asset_window.get(asset, cur_window(recv_ts))
    src_ts = ev.get("timestamp")
    raw = json.dumps(ev, separators=(",", ":"))
    if etype == "last_trade_price":
        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        state.trade_buf.append((recv_ts, recv_utc, win, asset,
                                _f(ev.get("price")), _f(ev.get("size")),
                                ev.get("side"), src_ts, raw))
        state.stats["trade"] += 1
    elif etype in ("book", "price_change", "tick_size_change"):
        state.book_buf.append((recv_ts, recv_utc, win, asset, etype,
                               src_ts, ev.get("hash"), raw))
        state.stats["book"] += 1
    # unknown event types are ignored (e.g. acks)


async def market_consumer(state):
    while state.running:
        proactive = False
        try:
            async with websockets.connect(MARKET_WS, ping_interval=PING_INTERVAL,
                                           ping_timeout=10, max_size=None) as ws:
                state.market_ws = ws
                await _resubscribe(state)
                conn_start = time.time()
                last_msg = conn_start
                while state.running:
                    if time.time() - conn_start > PROACTIVE_RECONNECT:
                        proactive = True
                        break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    except asyncio.TimeoutError:
                        if time.time() - last_msg > INACTIVITY_TIMEOUT:
                            print(f"[{time.strftime('%H:%M:%S')}] ws inactivity "
                                  f">{INACTIVITY_TIMEOUT:.0f}s -> reconnect", flush=True)
                            break
                        continue
                    last_msg = time.time()
                    recv_ts = last_msg
                    recv_utc = utc(recv_ts)
                    try:
                        data = json.loads(msg)
                    except (ValueError, TypeError):
                        continue
                    events = data if isinstance(data, list) else [data]
                    for ev in events:
                        _handle_market_event(state, ev, recv_ts, recv_utc)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] market ws error: {e!r}", flush=True)
        finally:
            state.market_ws = None
        if state.running:
            if proactive:
                state.stats["proactive"] += 1   # planned cycle -> reconnect immediately
            else:
                state.stats["reconnects"] += 1
                await asyncio.sleep(RECONNECT_BACKOFF)


# ---- Binance bookTicker -----------------------------------------------------

async def binance_consumer(state):
    while state.running:
        try:
            async with websockets.connect(state.binance_ws, ping_interval=PING_INTERVAL,
                                           ping_timeout=10) as ws:
                while state.running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    except asyncio.TimeoutError:
                        continue
                    recv_ts = time.time()
                    try:
                        d = json.loads(msg)
                        bid = float(d["b"]); ask = float(d["a"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    state.btc_buf.append((recv_ts, utc(recv_ts), "binance_bookticker",
                                          bid, ask, (bid + ask) / 2, d.get("u")))
                    state.stats["btc"] += 1
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] binance ws error: {e!r}", flush=True)
        if state.running:
            await asyncio.sleep(RECONNECT_BACKOFF)


# ---- Chainlink settlement oracle (Polymarket RTDS) --------------------------

async def chainlink_consumer(state):
    """Stream the ACTUAL settlement oracle: Polymarket RTDS `crypto_prices_chainlink` for this coin's
    <coin>/usd (~1/s, public, no auth). App-level PING every 5s. Writes to price_ticks with
    source='chainlink' (reuses the btc_buf -> insert_price_ticks path; pruned at RETAIN_DAYS like Binance.
    The DURABLE per-window strike/final Chainlink is recorded separately by collector.py into `windows`)."""
    pair = coins.chainlink_pair(state.coin)
    # NOTE: the `filters` value is a STRING the server compares whitespace-SENSITIVELY -> must be COMPACT
    # JSON ({"symbol":"btc/usd"}); json.dumps's default ", " / ": " separators add spaces that match NOTHING.
    sub = json.dumps({"action": "subscribe", "subscriptions": [
        {"topic": "crypto_prices_chainlink", "type": "*",
         "filters": json.dumps({"symbol": pair}, separators=(",", ":"))}]})
    while state.running:
        try:
            async with websockets.connect(CHAINLINK_WS, ping_interval=None, max_size=None) as ws:
                await ws.send(sub)
                last_ping = time.time()
                while state.running:
                    if time.time() - last_ping > 5.0:
                        try:
                            await ws.send("PING")
                        except Exception:
                            pass
                        last_ping = time.time()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=6.0)
                    except asyncio.TimeoutError:
                        continue
                    recv_ts = time.time()
                    try:
                        d = json.loads(msg)
                    except (ValueError, TypeError):
                        continue
                    if not (isinstance(d, dict) and d.get("topic") == "crypto_prices_chainlink"):
                        continue
                    # 'update' = single {symbol,value,timestamp}; the initial snapshot (payload.data=[...])
                    # is skipped — we want the live stream, not backfill.
                    if d.get("type") != "update":
                        continue
                    p = d.get("payload") or {}
                    val = p.get("value")
                    if val is None:
                        continue
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        continue
                    state.btc_buf.append((recv_ts, utc(recv_ts), "chainlink",
                                          None, None, val, p.get("timestamp")))
                    state.stats["chainlink"] += 1
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] chainlink ws error: {e!r}", flush=True)
        if state.running:
            await asyncio.sleep(RECONNECT_BACKOFF)


# ---- buffered writer --------------------------------------------------------

def _flush(state, conn):
    if state.book_buf:
        rows, state.book_buf = state.book_buf, []
        storage.insert_book_events(conn, rows)
    if state.trade_buf:
        rows, state.trade_buf = state.trade_buf, []
        storage.insert_trades(conn, rows)
    if state.btc_buf:
        rows, state.btc_buf = state.btc_buf, []
        storage.insert_price_ticks(conn, rows)
    conn.commit()


async def flusher(state, conn):
    last_report = time.time()
    while state.running:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            _flush(state, conn)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] flush error: {e!r}", flush=True)
        if time.time() - last_report >= 30:
            s = state.stats
            print(f"[{time.strftime('%H:%M:%S')}] events  book={s['book']}  "
                  f"trades={s['trade']}  price_ticks={s['btc']}  chainlink={s['chainlink']}  "
                  f"reconnects={s['reconnects']} proactive={s['proactive']}", flush=True)
            last_report = time.time()


# ---- auto-retention ---------------------------------------------------------

async def pruner(state):
    """Periodically roll off WS-stream rows older than RETAIN_DAYS so the DB
    file stabilizes. Runs on its own connection in a worker thread so it never
    blocks the event loop or the flusher."""
    while state.running:
        await asyncio.sleep(PRUNE_INTERVAL)
        cutoff = time.time() - RETAIN_DAYS * 86400.0
        try:
            n_book, n_btc = await asyncio.to_thread(storage.prune_ws, state.db_path, cutoff)
            if n_book or n_btc:
                print(f"[{time.strftime('%H:%M:%S')}] pruned book_events={n_book} "
                      f"price_ticks={n_btc} (older than {RETAIN_DAYS:.0f}d)", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] prune error: {e!r}", flush=True)


# ---- main -------------------------------------------------------------------

async def main(coin):
    db_path = coins.live_db(coin)
    coins.ensure_dirs(coin)
    conn = storage.connect(db_path)
    state = State()
    state.coin = coin
    state.db_path = db_path
    state.binance_ws = BINANCE_WS_T.format(coins.binance_symbol(coin).lower())
    print(f"ws_collector[{coin}] started -> {db_path}  (Ctrl-C to stop)", flush=True)
    tasks = [
        asyncio.create_task(window_manager(state)),
        asyncio.create_task(market_consumer(state)),
        asyncio.create_task(binance_consumer(state)),
        asyncio.create_task(chainlink_consumer(state)),
        asyncio.create_task(flusher(state, conn)),
        asyncio.create_task(pruner(state)),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        state.running = False
        for t in tasks:
            t.cancel()
        try:
            _flush(state, conn)        # persist whatever is buffered
        except Exception:
            pass
        conn.close()
        print("ws_collector stopped.", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="5-min up/down WebSocket collector (one coin)")
    ap.add_argument("--coin", default="btc", choices=list(coins.COINS),
                    help="which coin's market to capture (default btc)")
    _args = ap.parse_args()
    try:
        asyncio.run(main(_args.coin))
    except KeyboardInterrupt:
        pass

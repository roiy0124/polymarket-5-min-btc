"""BTC up/down 5-minute market data collector.

Continuously captures, for the *currently live* 5-minute BTC up/down market:
  - time left in the window
  - Up / Down odds (best bid/ask/mid/spread + top-10 order-book depth)
  - target price  (BTC price at window start  -> "strike")
  - current price (BTC price right now, Binance + Pyth)

Discovery is deterministic: the live window starts at floor(now/300)*300 and the
market slug is exactly that timestamp. When the 5-minute clock rolls over, the
collector automatically switches to the next live market and settles the one
that just closed (records final price + official Up/Down resolution).

Run:
    python collector.py
Stop with Ctrl-C. Data goes to btc_updown.db (SQLite). Inspect with peek.py.
"""

import os
import time
import signal
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import feeds
import storage

# ---- tunables ----------------------------------------------------------------
# Anchor the DB to this script's folder so it's the same file no matter what
# directory the collector / peek.py is launched from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btc_updown.db")
WINDOW_SECONDS = 300            # 5 minutes
POLL_INTERVAL = 1.0            # normal cadence (seconds)
TAIL_SECONDS = 20.0            # within this much of the close, poll faster
TAIL_INTERVAL = 0.3           # cadence inside the tail
STRIKE_MIN_LEFT = 298.0       # only trust strike if captured this close to start (<=2s)
SETTLE_RETRY_EVERY = 10.0     # how often to retry fetching official resolution
SETTLE_GIVEUP_AFTER = 600.0   # stop trying to settle a window after 10 min
# -----------------------------------------------------------------------------

_running = True


def _stop(*_):
    global _running
    _running = False
    print("\nstopping...", flush=True)


def now_window(t):
    start = int(t // WINDOW_SECONDS * WINDOW_SECONDS)
    return start, start + WINDOW_SECONDS


def fetch_tick(pool, market):
    """Fetch the four sources concurrently. Each may fail independently."""
    futs = {
        "up": pool.submit(feeds.fetch_book, market["token_up"]),
        "down": pool.submit(feeds.fetch_book, market["token_down"]),
        "binance": pool.submit(feeds.fetch_binance),
        "pyth": pool.submit(feeds.fetch_pyth),
    }
    out = {}
    for key, fut in futs.items():
        try:
            out[key] = fut.result()
        except Exception:
            out[key] = None
    return out


def main():
    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, AttributeError):
        pass

    conn = storage.connect(DB_PATH)
    pool = ThreadPoolExecutor(max_workers=4)

    cur_start = None
    market = None              # active market dict (or None until found)
    strike_set = False
    final_set = False
    pending_settle = {}        # window_start -> {"end":, "next_try":, "deadline":}

    # backfill: any window that closed but isn't settled yet (e.g. from a prior
    # run that was stopped before resolution was available) gets retried now.
    boot = time.time()
    for ws in storage.unsettled_windows(conn, boot):
        pending_settle[ws] = {
            "end": ws + WINDOW_SECONDS,
            "next_try": boot,
            "deadline": boot + SETTLE_GIVEUP_AFTER,
        }
    if pending_settle:
        print(f"backfilling settlement for {len(pending_settle)} closed window(s)", flush=True)

    print(f"collector started -> {DB_PATH}  (Ctrl-C to stop)", flush=True)

    while _running:
        loop_t = time.time()
        loop_utc = datetime.fromtimestamp(loop_t, tz=timezone.utc).isoformat(timespec="milliseconds")
        start, end = now_window(loop_t)
        time_left = end - loop_t

        # --- window rollover ---------------------------------------------------
        if start != cur_start:
            if cur_start is not None:
                # the window that just closed: try to settle it
                pending_settle[cur_start] = {
                    "end": cur_start + WINDOW_SECONDS,
                    "next_try": loop_t,
                    "deadline": loop_t + SETTLE_GIVEUP_AFTER,
                }
            cur_start = start
            strike_set = False
            final_set = False
            market = None
            # fetch the new live market's token ids (retry a few times)
            for attempt in range(3):
                try:
                    market = feeds.fetch_market(start)
                except Exception:
                    market = None
                if market:
                    break
                time.sleep(0.5)
            if market:
                joined_late = time_left < STRIKE_MIN_LEFT
                try:
                    storage.upsert_window(conn, market, end, loop_t)
                    if joined_late:
                        storage.mark_partial(conn, start)
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] window-register error: {e!r}", flush=True)
                print(f"[{time.strftime('%H:%M:%S')}] live window {start} "
                      f"({market.get('slug')})"
                      f"{'  [joined mid-window]' if joined_late else ''}", flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] window {start}: market not "
                      f"available yet, will retry next tick", flush=True)

        # --- capture a snapshot of the live market ----------------------------
        if market is None:
            # market wasn't ready at rollover; try again
            try:
                market = feeds.fetch_market(start)
                if market:
                    storage.upsert_window(conn, market, end, loop_t)
            except Exception:
                market = None

        try:
            if market is not None:
                tick = fetch_tick(pool, market)
                up = tick["up"] or {}
                down = tick["down"] or {}
                binance = tick["binance"]
                pyth = tick["pyth"]

                storage.insert_snapshot(conn, start, loop_t, loop_utc, time_left,
                                        up, down, binance, pyth)

                # strike = first reading near the start of the window
                if not strike_set and time_left >= STRIKE_MIN_LEFT and binance is not None:
                    storage.set_strike(conn, start, binance, pyth, loop_t)
                    strike_set = True

                # final = last reading just before the close
                if not final_set and time_left <= 1.0 and binance is not None:
                    storage.set_final(conn, start, binance, pyth, loop_t)
                    final_set = True

            # --- settle closed windows ----------------------------------------
            _settle(conn, pending_settle, loop_t)
        except Exception as e:
            # never let a transient DB/network error kill the collector
            print(f"[{time.strftime('%H:%M:%S')}] loop error (continuing): {e!r}", flush=True)

        # --- sleep until next tick --------------------------------------------
        interval = TAIL_INTERVAL if time_left <= TAIL_SECONDS else POLL_INTERVAL
        elapsed = time.time() - loop_t
        time.sleep(max(0.0, interval - elapsed))

    pool.shutdown(wait=False)
    conn.close()
    print("stopped.", flush=True)


def _settle(conn, pending, now):
    done = []
    for ws, info in pending.items():
        if now < info["next_try"]:
            continue
        if now > info["deadline"]:
            done.append(ws)
            continue
        try:
            m = feeds.fetch_market(ws)
            outcome = feeds.resolution_from_market(m)
        except Exception:
            outcome = None
        if outcome:
            storage.set_resolution(conn, ws, outcome)
            print(f"[{time.strftime('%H:%M:%S')}] settled window {ws} -> {outcome}", flush=True)
            done.append(ws)
        else:
            info["next_try"] = now + SETTLE_RETRY_EVERY
    for ws in done:
        pending.pop(ws, None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

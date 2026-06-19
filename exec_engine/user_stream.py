"""Order/fill listener — Polymarket CLOB *user channel* (authenticated).

This is the authoritative feed for whether/when YOUR own orders fill. It is for
the LIVE path: it needs API credentials (apiKey/secret/passphrase derived from
your private key) and is subscribed by condition IDs. In PAPER mode you don't use
this — PaperBroker detects fills from the public trade stream instead (see
paper_runner.py).

Endpoint + lifecycle (from the data-reliability research):
  wss://ws-subscriptions-clob.polymarket.com/ws/user
  auth: {"apiKey","secret","passphrase"}; subscribe by condition IDs.
  'trade' events progress MATCHED -> MINED -> CONFIRMED (RETRYING/FAILED branches).
  'order' events report placement/cancel/update.

The exact field names are confirmed against the execution research before the live
path is enabled; until then this parses defensively and passes the raw event to
callbacks. It refuses to run without credentials.
"""

import json
import asyncio

try:
    import websockets
except ImportError:  # keep the package importable without the dep
    websockets = None

USER_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/user"


class UserStream:
    def __init__(self, api_key, secret, passphrase, condition_ids,
                 on_fill=None, on_order=None, inactivity_timeout=120.0):
        if websockets is None:
            raise RuntimeError("UserStream needs the 'websockets' package (pip install websockets).")
        if not (api_key and secret and passphrase):
            raise RuntimeError("UserStream requires apiKey/secret/passphrase credentials.")
        if not condition_ids:
            raise RuntimeError("UserStream requires at least one condition_id to subscribe.")
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.condition_ids = list(condition_ids)
        self.on_fill = on_fill      # callback(asset_id, price, size, side, status, raw)
        self.on_order = on_order    # callback(raw)
        self.inactivity_timeout = inactivity_timeout
        self._running = True

    def _subscribe_msg(self):
        return json.dumps({
            "auth": {"apiKey": self.api_key, "secret": self.secret,
                     "passphrase": self.passphrase},
            "type": "user",
            "markets": self.condition_ids,
        })

    def stop(self):
        self._running = False

    async def run(self):
        import time
        while self._running:
            try:
                async with websockets.connect(USER_WS, ping_interval=15, ping_timeout=10) as ws:
                    await ws.send(self._subscribe_msg())
                    last = time.time()
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            if time.time() - last > self.inactivity_timeout:
                                break
                            continue
                        last = time.time()
                        self._handle(msg)
            except Exception as e:
                print(f"[user_stream] error: {e!r}; reconnecting", flush=True)
                await asyncio.sleep(2.0)

    def _handle(self, msg):
        try:
            data = json.loads(msg)
        except (ValueError, TypeError):
            return
        for ev in (data if isinstance(data, list) else [data]):
            if not isinstance(ev, dict):
                continue
            etype = ev.get("event_type") or ev.get("type")
            if etype == "trade":
                if self.on_fill:
                    def _f(x):
                        try:
                            return float(x)
                        except (TypeError, ValueError):
                            return None
                    self.on_fill(ev.get("asset_id"), _f(ev.get("price")),
                                 _f(ev.get("size")), ev.get("side"),
                                 ev.get("status"), ev)
            elif etype == "order":
                if self.on_order:
                    self.on_order(ev)

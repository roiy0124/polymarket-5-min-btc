"""LiveBook — reconstruct the L2 order book from the market-channel event stream, and derive the depth
features the maker-microstructure ideas need (one-sidedness / inventory skew / circuit-breaker footprint).

This is the missing primitive (flagged repeatedly): ws_collector logs RAW events verbatim but never
maintains a book, so sub-second DEPTH / ONE-SIDEDNESS lives only inside the raw `book_events` JSON. This
module turns that stream into per-asset top-of-book + depth features. It is built to be VALIDATED OFFLINE
against the raw events (each `price_change` carries its own best_bid/best_ask = ground truth) BEFORE the
same code is wired into the collector as a persistent feature layer — so production never runs unproven code.

Event shapes (verified from live data):
  - `book`         : {asset_id, bids:[{price,size}...], asks:[...]}  (full ladder; absolute sizes)
  - `price_change` : {price_changes:[{asset_id, price, size, side, best_bid, best_ask}...]}  (market-wide;
                     size = new ABSOLUTE size at that level, 0 = remove; side BUY=bid, SELL=ask)

    from analysis.book_reconstruct import LiveBook, features
"""
from __future__ import annotations
import json


class LiveBook:
    """Per-asset order book: {price(float): size(float)} for bids and asks. Apply events in time order."""
    def __init__(self):
        self.bids = {}   # asset_id -> {price: size}
        self.asks = {}

    def apply_book(self, asset, bids, asks):
        self.bids[asset] = {float(l["price"]): float(l["size"]) for l in bids if float(l["size"]) > 0}
        self.asks[asset] = {float(l["price"]): float(l["size"]) for l in asks if float(l["size"]) > 0}

    def apply_price_changes(self, changes):
        for ch in changes:
            a = ch.get("asset_id")
            if a is None:
                continue
            p = float(ch["price"]); s = float(ch["size"])
            side = ch.get("side")
            book = self.bids if side == "BUY" else self.asks
            d = book.setdefault(a, {})
            if s <= 0:
                d.pop(p, None)
            else:
                d[p] = s

    def apply_event(self, etype, payload):
        """payload = parsed JSON of one book_events row. Returns the set of asset_ids touched."""
        if etype == "book":
            a = payload.get("asset_id")
            if a is not None:
                self.apply_book(a, payload.get("bids", []), payload.get("asks", []))
                return {a}
        elif etype == "price_change":
            chs = payload.get("price_changes", [])
            self.apply_price_changes(chs)
            return {ch.get("asset_id") for ch in chs if ch.get("asset_id") is not None}
        return set()

    def features(self, asset, reach=0.05, topn=5):
        """Top-of-book + depth features for `asset`. Returns dict or None if the side is empty.
        - best_bid/best_ask/mid/spread; bid_sz1/ask_sz1 (best-level size)
        - bid_depth/ask_depth: cumulative size within `reach` of the best, AND top-`topn` cumulative
        - n_bid/n_ask: number of price levels (one-sidedness: a side near 0 = abandoned)
        - ratio: bid_depth/(bid_depth+ask_depth)  (0.5=balanced; ->1 ask abandoned; ->0 bid abandoned)"""
        b = self.bids.get(asset, {}); a = self.asks.get(asset, {})
        if not b or not a:
            return dict(asset=asset, best_bid=None, best_ask=None, n_bid=len(b), n_ask=len(a),
                        bid_depth=sum(b.values()), ask_depth=sum(a.values()),
                        ratio=(1.0 if a == {} and b else (0.0 if b == {} else None)))
        bb = max(b); ba = min(a)
        bid_depth = sum(sz for p, sz in b.items() if p >= bb - reach)
        ask_depth = sum(sz for p, sz in a.items() if p <= ba + reach)
        tot = bid_depth + ask_depth
        return dict(asset=asset, best_bid=bb, best_ask=ba, mid=(bb + ba) / 2, spread=ba - bb,
                    bid_sz1=b[bb], ask_sz1=a[ba],
                    bid_depth=bid_depth, ask_depth=ask_depth, n_bid=len(b), n_ask=len(a),
                    ratio=(bid_depth / tot if tot > 0 else None))


def replay_window(conn, window_start, assets=None):
    """Replay this window's book_events in time order; yield (recv_ts, asset, features) on each change.
    `assets` optionally restricts to specific token ids. Causal by construction (events in recv order)."""
    lb = LiveBook()
    rows = conn.execute(
        "SELECT recv_ts, event_type, payload FROM book_events WHERE window_start=? "
        "AND event_type IN ('book','price_change') ORDER BY recv_ts, id", (window_start,)).fetchall()
    for recv_ts, etype, payload in rows:
        try:
            p = json.loads(payload)
        except (ValueError, TypeError):
            continue
        touched = lb.apply_event(etype, p)
        for a in touched:
            if assets is not None and a not in assets:
                continue
            f = lb.features(a)
            if f is not None:
                yield recv_ts, a, f


def features_at(conn, window_start, asset, at_ts):
    """Reconstruct `asset`'s features as of recv_ts <= at_ts (the causal state at a decision instant)."""
    lb = LiveBook()
    last = None
    for recv_ts, etype, payload in conn.execute(
            "SELECT recv_ts, event_type, payload FROM book_events WHERE window_start=? AND recv_ts<=? "
            "AND event_type IN ('book','price_change') ORDER BY recv_ts, id", (window_start, at_ts)):
        try:
            p = json.loads(payload)
        except (ValueError, TypeError):
            continue
        lb.apply_event(etype, p)
    return lb.features(asset)

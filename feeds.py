"""Data sources for the BTC up/down 5-minute collector.

All HTTP is stdlib (urllib) so the project has zero dependencies.

Sources
-------
- Gamma  : market metadata (token ids, condition id, official resolution)
- CLOB   : live order book for each outcome token (the "odds")
- Binance: BTCUSDT spot price (proxy for the strike / current price)
- Pyth   : BTC/USD oracle price (second proxy)

NOTE on resolution source: these markets settle on the *Chainlink* BTC/USD
data stream (https://data.chain.link/streams/btc-usd), which is auth-gated.
Binance and Pyth track it within a few dollars but are not identical. We log
both proxies so a later analysis can measure the basis and pick the best
predictor. A Chainlink adapter can drop in here later.
"""

import json
import urllib.request
import urllib.parse

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
CLOB_BOOK = "https://clob.polymarket.com/book"
BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
PYTH_LATEST = "https://hermes.pyth.network/v2/updates/price/latest"
PYTH_BTC_ID = "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"

DEFAULT_TIMEOUT = 8.0
_HEADERS = {"User-Agent": "btc-updown-collector/1.0"}


def _get_json(url, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Market discovery (Gamma)
# ---------------------------------------------------------------------------

def slug_for(window_start):
    """The market slug is exactly the window-start unix timestamp."""
    return f"btc-updown-5m-{int(window_start)}"


def fetch_market(window_start, timeout=DEFAULT_TIMEOUT):
    """Return a normalized dict for the 5-min market starting at window_start,
    or None if it doesn't exist yet / can't be parsed."""
    url = f"{GAMMA_EVENTS}?slug={urllib.parse.quote(slug_for(window_start))}"
    data = _get_json(url, timeout=timeout)
    if not data:
        return None
    event = data[0] if isinstance(data, list) else data
    markets = event.get("markets") or []
    if not markets:
        return None
    m = markets[0]
    token_ids = json.loads(m.get("clobTokenIds") or "[]")
    outcomes = json.loads(m.get("outcomes") or "[]")
    prices = json.loads(m.get("outcomePrices") or "[]")
    if len(token_ids) < 2:
        return None
    return {
        "window_start": int(window_start),
        "slug": m.get("slug"),
        "condition_id": m.get("conditionId"),
        "question": m.get("question"),
        "token_up": token_ids[0],      # outcomes[0] == "Up"
        "token_down": token_ids[1],    # outcomes[1] == "Down"
        "outcomes": outcomes,
        "outcome_prices": prices,
        "closed": bool(m.get("closed")),
        "accepting_orders": bool(m.get("acceptingOrders")),
        "best_bid": m.get("bestBid"),
        "best_ask": m.get("bestAsk"),
        "last_trade": m.get("lastTradePrice"),
    }


def resolution_from_market(market):
    """Given a fetched market dict, return 'Up' / 'Down' / None once settled."""
    if not market or not market.get("closed"):
        return None
    prices = market.get("outcome_prices") or []
    try:
        up = float(prices[0])
        down = float(prices[1])
    except (IndexError, ValueError, TypeError):
        return None
    if up >= 0.99 and down <= 0.01:
        return "Up"
    if down >= 0.99 and up <= 0.01:
        return "Down"
    return None


# ---------------------------------------------------------------------------
# Order book (CLOB)
# ---------------------------------------------------------------------------

def _top_levels(levels, side, n=10):
    """Return up to n price/size levels sorted best-first.
    bids: highest price first. asks: lowest price first."""
    parsed = []
    for lvl in levels or []:
        try:
            parsed.append((float(lvl["price"]), float(lvl["size"])))
        except (KeyError, ValueError, TypeError):
            continue
    parsed.sort(key=lambda x: x[0], reverse=(side == "bid"))
    return parsed[:n]


def fetch_book(token_id, timeout=DEFAULT_TIMEOUT, depth=10):
    """Return best bid/ask/mid/spread plus top-N depth for one outcome token."""
    url = f"{CLOB_BOOK}?token_id={token_id}"
    data = _get_json(url, timeout=timeout)
    bids = _top_levels(data.get("bids"), "bid", depth)
    asks = _top_levels(data.get("asks"), "ask", depth)
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    mid = (best_bid + best_ask) / 2 if (best_bid is not None and best_ask is not None) else None
    spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": spread,
        "bids": bids,
        "asks": asks,
    }


# ---------------------------------------------------------------------------
# Price feeds
# ---------------------------------------------------------------------------

def fetch_binance(timeout=DEFAULT_TIMEOUT):
    data = _get_json(BINANCE_PRICE, timeout=timeout)
    return float(data["price"])


def fetch_pyth(timeout=DEFAULT_TIMEOUT):
    url = f"{PYTH_LATEST}?ids[]={PYTH_BTC_ID}&parsed=true&encoding=hex"
    data = _get_json(url, timeout=timeout)
    item = data["parsed"][0]["price"]
    return int(item["price"]) * (10 ** int(item["expo"]))

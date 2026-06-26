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
import os
import urllib.request
import urllib.parse

import coins

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
CLOB_BOOK = "https://clob.polymarket.com/book"
BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol={}"
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

def slug_for(window_start, coin="btc"):
    """The market slug is the coin's prefix + the window-start unix timestamp,
    e.g. btc-updown-5m-1782097200 / eth-updown-5m-1782097200."""
    return f"{coins.slug_prefix(coin)}-{int(window_start)}"


def fetch_market(window_start, coin="btc", timeout=DEFAULT_TIMEOUT):
    """Return a normalized dict for the coin's 5-min market starting at
    window_start, or None if it doesn't exist yet / can't be parsed."""
    url = f"{GAMMA_EVENTS}?slug={urllib.parse.quote(slug_for(window_start, coin))}"
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


def fetch_fee_schedule(window_start=None, coin="btc", timeout=DEFAULT_TIMEOUT):
    """Verify the LIVE taker-fee schedule from Gamma (it lives on the market, field `feeSchedule`).
    Confirmed 2026-06-25: {rate:0.07, takerOnly:True, rebateRate:0.2, exponent:1}, feesEnabled=True,
    feeType='crypto_fees_v2'. Closes the 'fee hardcoded, never fetched' gap. window_start defaults to
    the current live 5-min window. Returns a dict or None."""
    if window_start is None:
        import time
        window_start = int(time.time() // 300 * 300)
    url = f"{GAMMA_EVENTS}?slug={urllib.parse.quote(slug_for(window_start, coin))}"
    data = _get_json(url, timeout=timeout)
    if not data:
        return None
    event = data[0] if isinstance(data, list) else data
    markets = event.get("markets") or []
    if not markets:
        return None
    m = markets[0]
    sched = m.get("feeSchedule") or {}
    if isinstance(sched, str):
        try:
            sched = json.loads(sched)
        except (ValueError, TypeError):
            sched = {}
    return {
        "slug": m.get("slug"),
        "feesEnabled": bool(m.get("feesEnabled")),
        "feeType": m.get("feeType"),
        "rate": sched.get("rate"),
        "takerOnly": sched.get("takerOnly"),
        "rebateRate": sched.get("rebateRate"),
        "exponent": sched.get("exponent"),
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

def fetch_binance(symbol="BTCUSDT", timeout=DEFAULT_TIMEOUT):
    data = _get_json(BINANCE_PRICE.format(symbol), timeout=timeout)
    return float(data["price"])


_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PRICES_HISTORY = "https://clob.polymarket.com/prices-history"


def fetch_price_history(token_id, start_ts, end_ts, fidelity=1, timeout=DEFAULT_TIMEOUT):
    """Polymarket's official price series for one outcome token over [start,end].
    Public, but Cloudflare 403s non-browser User-Agents, so we send a browser UA.
    Returns [(t_unix, price)]. NOTE: coarse (~1/min) and EMPTY once the market
    resolves -> fetch while the round is still live."""
    url = (f"{PRICES_HISTORY}?market={token_id}&startTs={int(start_ts)}"
           f"&endTs={int(end_ts)}&fidelity={fidelity}")
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for pt in data.get("history", []):
        try:
            out.append((int(pt["t"]), float(pt["p"])))
        except (KeyError, ValueError, TypeError):
            pass
    return out


def fetch_pyth(pyth_id=PYTH_BTC_ID, timeout=DEFAULT_TIMEOUT):
    """Latest Pyth price for the given Crypto.<COIN>/USD feed id (defaults to BTC)."""
    url = f"{PYTH_LATEST}?ids[]={pyth_id}&parsed=true&encoding=hex"
    data = _get_json(url, timeout=timeout)
    item = data["parsed"][0]["price"]
    return int(item["price"]) * (10 ** int(item["expo"]))


# ---------------------------------------------------------------- Chainlink (the SETTLEMENT family)
# The 5-min market settles on the Chainlink <COIN>/USD low-latency DATA STREAM (auth-gated). This reads
# the FREE on-chain Chainlink aggregator (a slower proxy of the same oracle) via stdlib JSON-RPC eth_call
# — the closest free signal to the actual settlement source, and much closer than Binance/Pyth for the
# boundary/basis ideas (see memory `settlement-basis-wall`, ideas_old/settlement-lag.md).
#
# STATUS (2026-06-26): mechanism VERIFIED live (BTC/ETH read cleanly, fresh updatedAt). BUT a key finding
# from building it: the free on-chain aggregator updates only on a HEARTBEAT (~1h for ETH; ~6min for BTC) or
# a ~0.5% deviation — too COARSE to give a fresh price at every 5-min boundary. At a boundary it is often
# stale, so Binance (live, sub-second) is actually the better REAL-TIME proxy; the gap that flips 5-min
# outcomes is specifically to Chainlink's sub-second DATA STREAM. So this free adapter does NOT resolve the
# settlement-lag basis (memory `settlement-basis-wall`); that requires AUTH-GATED Chainlink Data Streams
# access (the user's credentials/subscription). Kept as the closest free Chainlink reference (for measuring
# the slow basis + sanity checks), NOT a settlement-exact source. To go further you need Data Streams auth;
# the alt addresses (SOL/XRP/DOGE/BNB) are also still TODO-verify and may not be on ETH mainnet.
CHAINLINK_RPC = os.environ.get("CHAINLINK_RPC", "https://1rpc.io/eth")
CHAINLINK_FEEDS = {                          # Ethereum-mainnet aggregator PROXY addresses, <coin>/USD
    "btc": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",   # VERIFIED live
    "eth": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",   # VERIFIED live
    "bnb": "0x14e613AC84a31f709eadbdF89C6CC390fDc9540A",   # TODO verify (rate-limited on first read)
    "sol": "0x4ffC43a60e009B551865A93d232E33Fce9f01507",   # TODO verify
    "doge": "0x2465CefD3b488BE410b941b1d4b2767088e2A028",  # TODO verify
    "xrp": None,                                            # TODO find/verify (may not be on ETH mainnet)
}
_RPC_HEADERS = {"Content-Type": "application/json", "User-Agent": _BROWSER_UA}


def _eth_call(to, data, rpc=None, timeout=DEFAULT_TIMEOUT):
    """Minimal stdlib JSON-RPC eth_call -> hex result string (no web3 dependency)."""
    rpc = rpc or CHAINLINK_RPC
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                       "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(rpc, body, _RPC_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if "result" not in out:
        raise RuntimeError(f"eth_call error: {out.get('error')}")
    return out["result"]


def fetch_chainlink(coin="btc", rpc=None, timeout=DEFAULT_TIMEOUT):
    """Latest on-chain Chainlink <coin>/USD price + its updatedAt unix ts. Returns (price, updated_at)
    or raises. `latestRoundData()` selector 0xfeaf968c -> (roundId, int256 answer, startedAt, updatedAt,
    answeredInRound); `decimals()` selector 0x313ce567. Stale-guard on updatedAt is the caller's job."""
    addr = CHAINLINK_FEEDS.get(coin)
    if not addr:
        raise ValueError(f"no Chainlink feed configured for {coin}")
    decimals = int(_eth_call(addr, "0x313ce567", rpc, timeout), 16)
    raw = _eth_call(addr, "0xfeaf968c", rpc, timeout)[2:]
    answer = int(raw[64:128], 16)
    if answer >= 2 ** 255:                   # int256 two's-complement
        answer -= 2 ** 256
    updated_at = int(raw[192:256], 16)
    return answer / (10 ** decimals), updated_at

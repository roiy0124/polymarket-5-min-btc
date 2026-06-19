"""Order data model — shared by paper and live brokers."""

import time
import itertools
from enum import Enum
from dataclasses import dataclass, field

_seq = itertools.count(1)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING_NEW = "PENDING_NEW"        # created, not yet acknowledged
    OPEN = "OPEN"                      # resting on the book
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


TERMINAL = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}


@dataclass
class OrderIntent:
    """What we want to do — passed to a broker to place."""
    side: Side
    token_id: str
    price: float                 # in (0,1), multiple of tick (0.01)
    size: float                  # shares
    tif: str = "GTC"             # GTC (rest) | FOK | FAK | GTD
    tag: str = ""                # 'entry' | 'exit' | free-form
    window_start: int | None = None
    parent_id: str | None = None  # entry client_id, for an auto-sell exit
    client_id: str = field(default_factory=lambda: f"c{next(_seq)}")

    @property
    def notional(self) -> float:
        return self.size * self.price


@dataclass
class Order:
    """Live state of a placed order."""
    intent: OrderIntent
    status: OrderStatus = OrderStatus.PENDING_NEW
    broker_order_id: str | None = None
    filled_size: float = 0.0
    avg_price: float = 0.0
    queue_remaining: float = 0.0     # paper sim: size still ahead of us at our price
    created_ts: float = field(default_factory=time.time)
    updated_ts: float = field(default_factory=time.time)
    note: str = ""

    @property
    def remaining(self) -> float:
        return max(0.0, self.intent.size - self.filled_size)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    def touch(self):
        self.updated_ts = time.time()

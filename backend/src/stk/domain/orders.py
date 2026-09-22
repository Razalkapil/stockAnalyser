"""Paper-trading orders: types, state machine, and the fill rules -- pure.

FILL RULE (the brief): an order fills when a candle's HIGH/LOW *touched* its price -- not when
some last-price happened to equal it. Where the price it fills AT sits inside that candle is
the part that is easy to get subtly, favourably wrong, so it is spelled out:

  MARKET            next candle's OPEN.
  BUY  LIMIT  L     touched when low  <= L. Fills at min(L, open): a gap DOWN through the limit
                    fills at the (better) open, never at a price that wasn't traded.
  SELL LIMIT  L     touched when high >= L. Fills at max(L, open).
  SELL STOP-LOSS S  touched when low  <= S. Fills at min(S, open): a gap down THROUGH the stop
                    fills at the (worse) open -- a stop is not a guarantee.
  SELL TARGET T     touched when high >= T. Fills at max(T, open).

Only SELL-side stop-loss / target exist: this is a long-only delivery playground (no shorting),
so protective exits are sells. A candle counts only if it STARTS at or after the order was
created -- an order cannot fill on price action that happened before it existed. The one
exception is MARKET: if the order was created *during* a candle (``candle.start < created_at <
candle.end`` -- the poller was down and this is the day's EOD bar), it fills at that candle's
CLOSE instead, reason ``market_close``. That is not look-ahead -- the close happened strictly
after the order was placed -- and it is what lets a same-day market order placed mid-session
still execute that evening instead of silently rolling to the next session at a different price.
A MARKET order that reaches its OWN session's close unfilled is cancelled
(``market_order_expired``), the way a real broker treats a day order, rather than carried forward.

A candle frozen at a circuit limit does not trade: no buy at an upper lock, no sell at a lower
lock (the same rule, and the same heuristic, as the backtest).

When a stop-loss and a target sit on the same position and one candle touches both, the STOP
wins (``resolve_oco``): the conservative reading, matching the backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from stk.domain.costs import Side
from stk.domain.fills import Lock, can_buy, can_sell


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "SL"
    TARGET = "TARGET"


class OrderStatus(StrEnum):
    OPEN = "open"
    PENDING_EOD = "pending_eod"  # the delayed feed is down: waits for the end-of-day fill
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


TERMINAL = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})

# from-status -> statuses reachable from it. Terminal states are absorbing.
_ALLOWED: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.OPEN: frozenset({OrderStatus.PENDING_EOD, OrderStatus.FILLED,
                                 OrderStatus.CANCELLED, OrderStatus.REJECTED}),
    OrderStatus.PENDING_EOD: frozenset({OrderStatus.OPEN, OrderStatus.FILLED,
                                        OrderStatus.CANCELLED, OrderStatus.REJECTED}),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


class IllegalTransition(ValueError):
    pass


def transition(current: OrderStatus, new: OrderStatus) -> OrderStatus:
    """Return ``new`` if the move is legal, else raise. Terminal orders never change again."""
    if new not in _ALLOWED[current]:
        raise IllegalTransition(f"an order cannot go from {current.value} to {new.value}")
    return new


class OrderError(ValueError):
    """An order that should never be accepted."""


@dataclass(frozen=True)
class Order:
    order_id: int
    side: Side
    type: OrderType
    qty: int
    created_at: datetime
    limit_price: Decimal | None = None  # LIMIT
    trigger_price: Decimal | None = None  # STOP_LOSS / TARGET
    status: OrderStatus = OrderStatus.OPEN
    oco_group: str | None = None

    def with_status(self, new: OrderStatus) -> Order:
        return replace(self, status=transition(self.status, new))


def validate_order(side: Side, type_: OrderType, qty: int, limit_price: Decimal | None,
                   trigger_price: Decimal | None) -> None:
    """Refuse malformed orders at the door, with a reason a person can act on."""
    if qty < 1:
        raise OrderError("quantity must be at least 1")
    if type_ is OrderType.LIMIT and (limit_price is None or limit_price <= 0):
        raise OrderError("a limit order needs a positive limit price")
    if type_ in (OrderType.STOP_LOSS, OrderType.TARGET):
        if side is not Side.SELL:
            raise OrderError(
                f"{type_.value} orders are sell-side exits (there is no shorting here)"
            )
        if trigger_price is None or trigger_price <= 0:
            raise OrderError(f"a {type_.value} order needs a positive trigger price")
    if type_ is OrderType.MARKET and (limit_price is not None or trigger_price is not None):
        raise OrderError("a market order takes no price")


@dataclass(frozen=True)
class Candle:
    start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    #: When this candle ends. Only used to decide whether a MARKET order was created *during*
    #: this candle (see the module docstring). None means "unknown" -- callers that do not care
    #: about that distinction (most tests, the intraday-poller's older call sites) are unaffected,
    #: and a MARKET order simply keeps the old open-only behaviour.
    end: datetime | None = None


@dataclass(frozen=True)
class Fill:
    price: Decimal  # before slippage
    reason: str  # market_open/market_close/limit_touch/limit_gap/stop_touch/stop_gap/...


def _created_during(order: Order, candle: Candle) -> bool:
    """True when the order was placed strictly inside this candle's window -- only meaningful
    for MARKET, since a LIMIT/STOP's fill depends on the candle's high/low, which the order could
    not have influenced no matter when inside the candle it was placed."""
    return candle.end is not None and candle.start < order.created_at < candle.end


def _blocked(order: Order, candle: Candle, lock: Lock) -> bool:
    if order.status not in (OrderStatus.OPEN, OrderStatus.PENDING_EOD):
        return True
    market_mid_candle = order.type is OrderType.MARKET and _created_during(order, candle)
    if candle.start < order.created_at and not market_mid_candle:
        return True  # price action from before the order existed
    return not (can_buy(lock) if order.side is Side.BUY else can_sell(lock))


def _limit_fill(order: Order, candle: Candle) -> Fill | None:
    assert order.limit_price is not None
    lim, o = order.limit_price, candle.open
    if order.side is Side.BUY and candle.low <= lim:
        return Fill(min(lim, o), "limit_gap" if o <= lim else "limit_touch")
    if order.side is Side.SELL and candle.high >= lim:
        return Fill(max(lim, o), "limit_gap" if o >= lim else "limit_touch")
    return None


def _trigger_fill(order: Order, candle: Candle) -> Fill | None:
    assert order.trigger_price is not None
    trig, o = order.trigger_price, candle.open
    if order.type is OrderType.STOP_LOSS and candle.low <= trig:
        return Fill(min(trig, o), "stop_gap" if o <= trig else "stop_touch")
    if order.type is OrderType.TARGET and candle.high >= trig:
        return Fill(max(trig, o), "target_gap" if o >= trig else "target_touch")
    return None


def try_fill(order: Order, candle: Candle, lock: Lock = Lock.NONE) -> Fill | None:
    """The price ``order`` fills at on ``candle``, or None if it does not fill."""
    if _blocked(order, candle, lock):
        return None
    if order.type is OrderType.MARKET:
        if candle.start < order.created_at:
            # Placed mid-candle (the poller missed it): the close is strictly after the order,
            # so it is a legitimate fill price -- see the module docstring.
            return Fill(candle.close, "market_close")
        return Fill(candle.open, "market_open")
    if order.type is OrderType.LIMIT:
        return _limit_fill(order, candle)
    return _trigger_fill(order, candle)


def market_order_expired(order: Order, session_close: datetime) -> bool:
    """A MARKET order still active once its OWN session has closed is a day order that missed
    its window -- cancel it rather than silently carry it into a later session at a different
    price. Call this AFTER the fill attempt for the day's bar; an order this identifies as
    expired will already have been given its chance to fill at that bar's close.
    """
    return (order.type is OrderType.MARKET
            and order.status in (OrderStatus.OPEN, OrderStatus.PENDING_EOD)
            and order.created_at <= session_close)


def resolve_oco(orders: list[Order], candle: Candle, lock: Lock = Lock.NONE
                ) -> tuple[Order, Fill] | None:
    """Of a group of mutually exclusive orders, the ONE that fills on this candle.

    If several would fill on the same candle the stop-loss wins: with only OHLC we cannot know
    which was touched first, and assuming the flattering one would overstate results.
    """
    hits = [(o, f) for o in orders if (f := try_fill(o, candle, lock)) is not None]
    if not hits:
        return None
    hits.sort(key=lambda h: 0 if h[0].type is OrderType.STOP_LOSS else 1)
    return hits[0]

"""Order fill rules and the state machine. Every price below is worked by hand."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from stk.domain.costs import Side
from stk.domain.fills import Lock
from stk.domain.orders import (
    Candle,
    IllegalTransition,
    Order,
    OrderError,
    OrderStatus,
    OrderType,
    resolve_oco,
    transition,
    try_fill,
    validate_order,
)

T0 = datetime(2026, 9, 18, 10, 0)
D = Decimal


def candle(o, h, low, c=None, start=T0 + timedelta(minutes=5)) -> Candle:
    return Candle(start, D(str(o)), D(str(h)), D(str(low)), D(str(c if c is not None else o)))


def order(side=Side.BUY, type_=OrderType.LIMIT, price=None, qty=10, status=OrderStatus.OPEN, **kw):
    limit = D(str(price)) if type_ is OrderType.LIMIT and price is not None else None
    trig = D(str(price)) if type_ in (OrderType.STOP_LOSS, OrderType.TARGET) else None
    return Order(1, side, type_, qty, T0, limit_price=limit, trigger_price=trig,
                 status=status, **kw)


class TestMarket:
    def test_fills_at_the_next_candles_open(self):
        f = try_fill(order(type_=OrderType.MARKET), candle(101, 105, 99))
        assert f is not None and f.price == D("101") and f.reason == "market_open"


class TestBuyLimit:
    def test_touch_fills_at_the_limit(self):
        f = try_fill(order(price=100), candle(102, 103, 99))
        assert (f.price, f.reason) == (D("100"), "limit_touch")

    def test_gap_down_through_the_limit_fills_at_the_better_open(self):
        f = try_fill(order(price=100), candle(97, 99, 96))
        assert (f.price, f.reason) == (D("97"), "limit_gap")

    def test_not_touched_does_not_fill(self):
        assert try_fill(order(price=100), candle(102, 105, 101)) is None

    def test_exactly_touching_counts(self):
        assert try_fill(order(price=100), candle(102, 103, 100)).price == D("100")


class TestSellLimit:
    def test_touch(self):
        f = try_fill(order(Side.SELL, price=110), candle(105, 111, 104))
        assert (f.price, f.reason) == (D("110"), "limit_touch")

    def test_gap_up_fills_at_the_better_open(self):
        f = try_fill(order(Side.SELL, price=110), candle(113, 115, 112))
        assert (f.price, f.reason) == (D("113"), "limit_gap")

    def test_not_touched(self):
        assert try_fill(order(Side.SELL, price=110), candle(105, 109, 104)) is None


class TestStopLoss:
    def sl(self, price):
        return order(Side.SELL, OrderType.STOP_LOSS, price)

    def test_touch_fills_at_the_stop(self):
        f = try_fill(self.sl(95), candle(100, 101, 94))
        assert (f.price, f.reason) == (D("95"), "stop_touch")

    def test_gap_down_through_the_stop_fills_at_the_WORSE_open(self):
        """A stop is not a guarantee: open 90 is what was actually available."""
        f = try_fill(self.sl(95), candle(90, 91, 88))
        assert (f.price, f.reason) == (D("90"), "stop_gap")

    def test_not_touched(self):
        assert try_fill(self.sl(95), candle(100, 101, 96)) is None


class TestTarget:
    def tg(self, price):
        return order(Side.SELL, OrderType.TARGET, price)

    def test_touch_and_gap(self):
        assert try_fill(self.tg(110), candle(105, 111, 104)).price == D("110")
        assert try_fill(self.tg(110), candle(114, 116, 113)).price == D("114")

    def test_not_touched(self):
        assert try_fill(self.tg(110), candle(105, 109, 104)) is None


class TestTiming:
    def test_a_candle_that_started_before_the_order_existed_is_ignored(self):
        """The order was placed at 10:00; the 09:55 candle's low cannot fill it."""
        early = Candle(T0 - timedelta(minutes=5), D("99"), D("100"), D("90"), D("95"))
        assert try_fill(order(price=95), early) is None

    def test_a_candle_starting_exactly_when_the_order_was_placed_counts(self):
        c = Candle(T0, D("101"), D("102"), D("94"), D("96"))
        assert try_fill(order(price=95), c) is not None

    @pytest.mark.parametrize("status", [OrderStatus.FILLED, OrderStatus.CANCELLED,
                                        OrderStatus.REJECTED])
    def test_finished_orders_never_fill_again(self, status):
        assert try_fill(order(type_=OrderType.MARKET, status=status), candle(100, 101, 99)) is None

    def test_a_pending_eod_order_can_still_fill(self):
        o = order(type_=OrderType.MARKET, status=OrderStatus.PENDING_EOD)
        assert try_fill(o, candle(100, 101, 99)) is not None


class TestCircuitLocks:
    def test_no_buy_at_an_upper_lock(self):
        assert try_fill(order(type_=OrderType.MARKET), candle(110, 110, 110), Lock.UPPER) is None

    def test_no_sell_at_a_lower_lock(self):
        o = order(Side.SELL, OrderType.MARKET)
        assert try_fill(o, candle(90, 90, 90), Lock.LOWER) is None

    def test_the_other_direction_is_unaffected(self):
        assert try_fill(order(Side.SELL, OrderType.MARKET), candle(110, 110, 110),
                        Lock.UPPER) is not None
        assert try_fill(order(type_=OrderType.MARKET), candle(90, 90, 90), Lock.LOWER) is not None


class TestOco:
    def group(self):
        stop = order(Side.SELL, OrderType.STOP_LOSS, 95, oco_group="g")
        target = Order(2, Side.SELL, OrderType.TARGET, 10, T0, trigger_price=D("110"),
                       oco_group="g")
        return [target, stop]

    def test_only_the_touched_one_fills(self):
        o, f = resolve_oco(self.group(), candle(100, 111, 100))
        assert o.type is OrderType.TARGET and f.price == D("110")

    def test_the_stop_wins_when_one_candle_touches_both(self):
        o, _ = resolve_oco(self.group(), candle(100, 115, 90))
        assert o.type is OrderType.STOP_LOSS  # the conservative reading

    def test_nothing_touched(self):
        assert resolve_oco(self.group(), candle(100, 105, 99)) is None


class TestStateMachine:
    @pytest.mark.parametrize(("a", "b"), [
        (OrderStatus.OPEN, OrderStatus.FILLED),
        (OrderStatus.OPEN, OrderStatus.CANCELLED),
        (OrderStatus.OPEN, OrderStatus.PENDING_EOD),
        (OrderStatus.PENDING_EOD, OrderStatus.OPEN),  # the feed came back
        (OrderStatus.PENDING_EOD, OrderStatus.FILLED),
    ])
    def test_legal(self, a, b):
        assert transition(a, b) is b

    @pytest.mark.parametrize("terminal", [OrderStatus.FILLED, OrderStatus.CANCELLED,
                                          OrderStatus.REJECTED])
    @pytest.mark.parametrize("target", list(OrderStatus))
    def test_terminal_states_are_absorbing(self, terminal, target):
        with pytest.raises(IllegalTransition):
            transition(terminal, target)

    def test_open_to_open_is_not_a_move(self):
        with pytest.raises(IllegalTransition):
            transition(OrderStatus.OPEN, OrderStatus.OPEN)

    def test_with_status_returns_a_new_order(self):
        o = order(type_=OrderType.MARKET)
        f = o.with_status(OrderStatus.FILLED)
        assert o.status is OrderStatus.OPEN and f.status is OrderStatus.FILLED


class TestValidation:
    def test_valid_orders_pass(self):
        validate_order(Side.BUY, OrderType.MARKET, 1, None, None)
        validate_order(Side.BUY, OrderType.LIMIT, 5, D("100"), None)
        validate_order(Side.SELL, OrderType.STOP_LOSS, 5, None, D("90"))

    @pytest.mark.parametrize(("args", "match"), [
        ((Side.BUY, OrderType.MARKET, 0, None, None), "at least 1"),
        ((Side.BUY, OrderType.LIMIT, 1, None, None), "limit price"),
        ((Side.BUY, OrderType.LIMIT, 1, D("-5"), None), "limit price"),
        ((Side.BUY, OrderType.STOP_LOSS, 1, None, D("90")), "sell-side"),
        ((Side.BUY, OrderType.TARGET, 1, None, D("90")), "sell-side"),
        ((Side.SELL, OrderType.TARGET, 1, None, None), "trigger price"),
        ((Side.BUY, OrderType.MARKET, 1, D("100"), None), "takes no price"),
    ])
    def test_invalid(self, args, match):
        with pytest.raises(OrderError, match=match):
            validate_order(*args)

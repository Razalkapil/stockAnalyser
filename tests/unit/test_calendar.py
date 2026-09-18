"""Tests for trading-calendar domain logic (weekday-holiday intersection)."""

from __future__ import annotations

from datetime import date

from stk.core.time import is_weekend
from stk.domain.calendar import build_trading_day_set, last_trading_day_on_or_before


class TestWeekendDetection:
    def test_saturday_is_weekend(self):
        assert is_weekend(date(2026, 9, 19)) is True  # a Saturday

    def test_sunday_is_weekend(self):
        assert is_weekend(date(2026, 9, 20)) is True

    def test_weekday_is_not_weekend(self):
        assert is_weekend(date(2026, 9, 17)) is False  # a Thursday


class TestBuildTradingDaySet:
    def test_weekend_falling_holiday_does_not_break_anything(self):
        """NSE's holiday-master API lists holidays that fall on a Sunday
        (e.g. 15-Feb-2026). Such a date should simply already be excluded
        as a weekend -- it must not appear as a trading day, and its
        presence in holiday_dates must not cause any error."""
        sunday_holiday = date(2026, 2, 15)  # a Sunday in this fixture
        assert is_weekend(sunday_holiday)

        days = build_trading_day_set(date(2026, 2, 13), date(2026, 2, 17), {sunday_holiday})
        assert sunday_holiday not in days
        assert date(2026, 2, 16) in days  # the following Monday, not a holiday

    def test_weekday_holiday_is_excluded(self):
        republic_day = date(2026, 1, 26)  # a Monday
        days = build_trading_day_set(date(2026, 1, 24), date(2026, 1, 28), {republic_day})
        assert republic_day not in days
        assert date(2026, 1, 24) not in days  # Saturday
        assert date(2026, 1, 25) not in days  # Sunday
        assert date(2026, 1, 27) in days  # Tuesday, a normal trading day

    def test_no_holidays_returns_all_weekdays(self):
        days = build_trading_day_set(date(2026, 9, 14), date(2026, 9, 18), set())
        assert len(days) == 5  # Mon-Fri


class TestLastTradingDayOnOrBefore:
    def test_target_itself_if_trading_day(self):
        trading_days = {date(2026, 9, 17)}
        assert last_trading_day_on_or_before(date(2026, 9, 17), trading_days) == date(2026, 9, 17)

    def test_walks_back_over_a_holiday_weekend(self):
        trading_days = {date(2026, 9, 17), date(2026, 9, 18)}  # Thu, Fri; Mon 21 is a holiday
        result = last_trading_day_on_or_before(date(2026, 9, 21), trading_days)
        assert result == date(2026, 9, 18)

    def test_returns_none_if_nothing_found_within_bound(self):
        assert last_trading_day_on_or_before(date(2026, 9, 17), set()) is None

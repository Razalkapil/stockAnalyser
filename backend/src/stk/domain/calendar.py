"""Trading-calendar domain logic built from raw holiday data.

Combines a CalendarProvider's raw holiday rows with weekday arithmetic
to answer "is this a trading day" and "what are the trading days in
this range" -- the provider gives raw facts, this module gives the
actual calendar decision. See providers.base.HolidayRecord's docstring
for why the raw list cannot be used directly (it includes holidays that
fall on a weekend).
"""

from __future__ import annotations

from datetime import date, timedelta

from stk.core.time import is_weekend


def build_trading_day_set(start: date, end: date, holiday_dates: set[date]) -> set[date]:
    """All weekday dates in [start, end] that are not in holiday_dates."""
    days = set()
    current = start
    while current <= end:
        if not is_weekend(current) and current not in holiday_dates:
            days.add(current)
        current += timedelta(days=1)
    return days


def last_trading_day_on_or_before(target: date, trading_days: set[date]) -> date | None:
    """Walk backward from target (inclusive) to find the nearest trading day.

    Bounded to 14 days back to avoid an unbounded loop if trading_days
    is empty or stale -- returns None rather than looping forever.
    """
    current = target
    for _ in range(14):
        if current in trading_days:
            return current
        current -= timedelta(days=1)
    return None

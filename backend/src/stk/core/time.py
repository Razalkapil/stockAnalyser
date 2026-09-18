"""IST timezone helpers and trading-day arithmetic primitives.

All business logic in this app operates in Asia/Kolkata (IST, UTC+5:30).
Never use naive datetimes or the server's local timezone for anything
that touches a trading date or a market-hours decision.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    """Current wall-clock time in IST."""
    return datetime.now(IST)


def today_ist() -> date:
    """Current calendar date in IST (not the server's local date)."""
    return now_ist().date()


def is_weekend(d: date) -> bool:
    """True for Saturday/Sunday.

    NSE's holiday-master API includes holidays that fall on a weekend
    (e.g. a Sunday-falling festival), so callers must intersect the raw
    holiday list with weekdays rather than trusting it as a trading-day
    calendar on its own.
    """
    return d.weekday() >= 5


def parse_ddmmmyyyy(s: str) -> date:
    """Parse NSE's 'DD-Mon-YYYY' date format (e.g. '17-Sep-2026').

    Explicit format string only -- never dateutil inference, which
    silently mis-parses ambiguous day/month combinations.
    """
    return datetime.strptime(s.strip(), "%d-%b-%Y").date()


def parse_ddmmyyyy_compact(s: str) -> date:
    """Parse the compact 'DDMMYYYY' form used in bhavcopy filenames."""
    return datetime.strptime(s.strip(), "%d%m%Y").date()


def format_ddmmyyyy_compact(d: date) -> str:
    """Format a date as 'DDMMYYYY' for bhavcopy filename construction."""
    return d.strftime("%d%m%Y")


def format_yyyymmdd(d: date) -> str:
    """Format a date as 'YYYYMMDD' for UDiFF filename construction."""
    return d.strftime("%Y%m%d")


def is_market_hours(dt: datetime | None = None) -> bool:
    """Whether the given (or current) IST instant is within 9:15-15:30.

    Does not check the trading calendar -- combine with a CalendarProvider
    to know if today is actually a trading day.
    """
    moment = dt.astimezone(IST) if dt else now_ist()
    return MARKET_OPEN <= moment.time() <= MARKET_CLOSE


def previous_calendar_day(d: date) -> date:
    """The calendar day immediately before ``d`` (no calendar awareness)."""
    return d - timedelta(days=1)

"""Trading-calendar ingest: populating `trading_calendar` from NSE, and
from what the price lake actually contains.

WHY TWO SOURCES. NSE's holiday-master API is authoritative and, as
confirmed by live probe on 2026-09-19, reaches back to 2011 -- so it
covers essentially the whole backfill range. It does NOT cover 2010,
the earliest year the price archives reach (see ADR 0003). Rather than
leave 2010 with no calendar, or silently pretend every 2010 weekday
traded, a second derivation reads the already-ingested bars: a date
with bars demonstrably traded, and a weekday inside a covered range
with no bars demonstrably did not. That is an honest observation, and
it is labelled as one in `trading_calendar.source`, so nothing
downstream can mistake it for an exchange's own statement.

PRECEDENCE. An observed row never overwrites an authoritative one. The
reverse is allowed: learning NSE's real answer for a date we had only
inferred is strictly an improvement.

WHAT THIS IS NOT. The calendar is an optimisation and a cross-check,
never a new trust boundary. `ingest.daily` still treats "no calendar
row" as unknown and goes to the network; `ingest.backfill` still
relies on DataNotPublished -> skipped_holiday as the backstop. A
calendar that is merely absent must never be able to silently skip a
real trading day.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from stk.core.time import is_weekend
from stk.domain.calendar import build_trading_day_set
from stk.ingest.jobs import job_run
from stk.ingest.raw_store import persist_artifact
from stk.store import duck
from stk.store.db.engine import connect

#: Written to trading_calendar.source for each derivation.
AUTHORITATIVE_SOURCE = "nse_holiday_master"
OBSERVED_SOURCE = "observed_bars"

#: BSE has no separate holiday feed here; NSE's equity calendar is used
#: as a documented approximation (docs/data-sources.md), labelled so
#: that the approximation is visible in the data itself.
NSE_PROXY_SOURCE = "nse_holiday_master(nse_proxy)"

#: Only an authoritative source may overwrite a row; observed rows are
#: written only where nothing better exists.
_SOURCE_RANK = {OBSERVED_SOURCE: 0, NSE_PROXY_SOURCE: 1, AUTHORITATIVE_SOURCE: 2}

SEGMENT = "CM"


class CalendarIngestResult:
    def __init__(self, year: int, exchange: str, trading_days: int, holidays: int) -> None:
        self.year = year
        self.exchange = exchange
        self.trading_days = trading_days
        self.holidays = holidays


def _upsert_day(
    conn: sqlite3.Connection,
    *,
    cal_date: date,
    exchange: str,
    is_trading_day: bool,
    description: str | None,
    source: str,
) -> None:
    """Insert or improve one calendar row, respecting source precedence."""
    existing = conn.execute(
        "SELECT source FROM trading_calendar WHERE cal_date=? AND exchange=? AND segment=?",
        (cal_date.isoformat(), exchange, SEGMENT),
    ).fetchone()
    if existing is not None:
        incumbent_rank = _SOURCE_RANK.get(str(existing["source"]), 0)
        if _SOURCE_RANK.get(source, 0) < incumbent_rank:
            # A weaker source must not degrade a stronger one -- see the
            # module docstring's precedence rule.
            return

    conn.execute(
        """INSERT INTO trading_calendar
               (cal_date, exchange, segment, is_trading_day, holiday_description,
                source, captured_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (cal_date, exchange, segment) DO UPDATE SET
             is_trading_day=excluded.is_trading_day,
             holiday_description=excluded.holiday_description,
             source=excluded.source,
             captured_at=excluded.captured_at""",
        (
            cal_date.isoformat(), exchange, SEGMENT, int(is_trading_day), description,
            source, datetime.now(UTC).isoformat(),
        ),
    )


def ingest_calendar_year(
    year: int,
    *,
    exchange: str,
    sqlite_path: Path,
    raw_root: Path,
    provider_name: str = "nse_holiday_master",
) -> CalendarIngestResult:
    """Populate one calendar year for one exchange from NSE's holiday master.

    Writes a row for every weekday in the year: trading days and
    holidays alike. Weekends are omitted entirely -- they are not facts
    the exchange publishes, they are arithmetic, and storing 104 rows a
    year of arithmetic would invite someone to trust the table over
    `is_weekend`.
    """
    from stk.providers.registry import get_calendar_provider  # noqa: PLC0415

    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_calendar", business_date=date(year, 1, 1)) as handle:
            provider = get_calendar_provider(provider_name)
            artifact = provider.fetch_holidays_artifact(year)
            persist_artifact(raw_root, conn, artifact)

            records = provider.parse_holidays(artifact, SEGMENT)
            holiday_by_date = {r.trading_date: r.description for r in records}

            start, end = date(year, 1, 1), date(year, 12, 31)
            # NSE lists holidays that fall on a Saturday or Sunday;
            # build_trading_day_set is the single place that intersects
            # them away (see HolidayRecord's docstring).
            trading = build_trading_day_set(start, end, set(holiday_by_date))

            source = AUTHORITATIVE_SOURCE if exchange == "NSE" else NSE_PROXY_SOURCE
            holidays_written = 0
            current = start
            while current <= end:
                if not is_weekend(current):
                    is_trading = current in trading
                    if not is_trading:
                        holidays_written += 1
                    _upsert_day(
                        conn,
                        cal_date=current,
                        exchange=exchange,
                        is_trading_day=is_trading,
                        description=holiday_by_date.get(current),
                        source=source,
                    )
                current += timedelta(days=1)

            handle.rows_in = len(records)
            handle.rows_written = len(trading) + holidays_written
            handle.metrics["trading_days"] = len(trading)
            handle.metrics["holidays"] = holidays_written

        return CalendarIngestResult(year, exchange, len(trading), holidays_written)
    finally:
        conn.close()


def ingest_calendar_from_bars(
    *,
    exchange: str,
    sqlite_path: Path,
    parquet_root: Path,
) -> CalendarIngestResult:
    """Derive calendar rows from the dates actually present in bars_daily.

    Covers only the range the lake covers -- from its earliest to its
    latest bar. Extrapolating past either end would be inventing facts:
    outside that range, absence of bars means "not ingested", not "did
    not trade", and those are emphatically different claims.

    Never overwrites an authoritative row (see module docstring).
    """
    with duck.connect(parquet_root) as session:
        rows = session.sql("dates_present", [exchange]).fetchall()
    observed = {r[0] for r in rows}

    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_calendar_from_bars", business_date=None) as handle:
            if not observed:
                handle.metrics["observed_dates"] = 0
                return CalendarIngestResult(0, exchange, 0, 0)

            start, end = min(observed), max(observed)
            holidays_written = 0
            current = start
            while current <= end:
                if not is_weekend(current):
                    is_trading = current in observed
                    if not is_trading:
                        holidays_written += 1
                    _upsert_day(
                        conn,
                        cal_date=current,
                        exchange=exchange,
                        is_trading_day=is_trading,
                        description=None,
                        source=OBSERVED_SOURCE,
                    )
                current += timedelta(days=1)

            handle.rows_in = len(observed)
            handle.rows_written = len(observed) + holidays_written
            handle.metrics["observed_trading_days"] = len(observed)
            handle.metrics["inferred_non_trading_weekdays"] = holidays_written

        return CalendarIngestResult(start.year, exchange, len(observed), holidays_written)
    finally:
        conn.close()


def is_trading_day(conn: sqlite3.Connection, cal_date: date, exchange: str) -> bool | None:
    """Whether the calendar knows this date traded.

    Returns None for "the calendar has no row" -- deliberately
    tri-state. A caller that collapses unknown into False would skip a
    real trading day the moment the calendar fell behind, which is the
    exact silent-no-op failure this project forbids.
    """
    row = conn.execute(
        "SELECT is_trading_day FROM trading_calendar "
        "WHERE cal_date=? AND exchange=? AND segment=?",
        (cal_date.isoformat(), exchange, SEGMENT),
    ).fetchone()
    if row is None:
        return None
    return bool(row["is_trading_day"])


def trading_days_between(
    conn: sqlite3.Connection, start: date, end: date, exchange: str
) -> list[date] | None:
    """Known trading days in [start, end], or None if the calendar does
    not fully cover the range.

    All-or-nothing on purpose: a partially-covered range silently
    returning its covered subset would make a backfill skip every date
    the calendar happens not to know about yet.
    """
    expected_weekdays = {
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if not is_weekend(start + timedelta(days=offset))
    }
    rows = conn.execute(
        "SELECT cal_date, is_trading_day FROM trading_calendar "
        "WHERE exchange=? AND segment=? AND cal_date BETWEEN ? AND ?",
        (exchange, SEGMENT, start.isoformat(), end.isoformat()),
    ).fetchall()
    known = {date.fromisoformat(str(r["cal_date"])): bool(r["is_trading_day"]) for r in rows}

    if not expected_weekdays <= set(known):
        return None
    return sorted(d for d in expected_weekdays if known[d])

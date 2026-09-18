"""Integration tests for trading_calendar population.

Covers the three rules that make this table safe to depend on:
source precedence (an inferred row never degrades an authoritative
one), range honesty (nothing is claimed outside what the lake or the
exchange actually covers), and the tri-state read (an unknown date is
unknown, not a holiday).

The load-bearing test is test_known_holiday_skips_without_any_request:
it asserts the nightly ingest makes ZERO HTTP calls on a date the
calendar says did not trade, which is the only proof the wiring is
real rather than decorative.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pyarrow as pa
import pytest
import respx

from stk.ingest.calendar import (
    AUTHORITATIVE_SOURCE,
    OBSERVED_SOURCE,
    ingest_calendar_from_bars,
    ingest_calendar_year,
    is_trading_day,
    trading_days_between,
)
from stk.ingest.daily import ingest_nse_prices_for_date
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition

HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master"
FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def data_dirs(tmp_path):
    sqlite_path = tmp_path / "app.db"
    migrate(sqlite_path)
    return sqlite_path, tmp_path / "parquet", tmp_path / "raw"


def _holiday_payload(*holidays: tuple[str, str]) -> dict:
    return {
        "CBM": [{"tradingDate": "01-Jan-2026", "description": "Bond-only"}],
        "CM": [{"tradingDate": d, "description": desc} for d, desc in holidays],
    }


def _mock_holidays(payload: dict) -> None:
    respx.get(HOLIDAY_URL).mock(
        return_value=httpx.Response(
            200, text=json.dumps(payload), headers={"content-type": "application/json"}
        )
    )


def _write_bars(parquet_root: Path, exchange: str, days: list[date]) -> None:
    n = len(days)
    table = pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "exchange": pa.array([exchange] * n).dictionary_encode(),
            "symbol": ["AAA"] * n,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array(["EQ"] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": [100.0] * n, "high": [100.0] * n, "low": [100.0] * n, "close": [100.0] * n,
            "prev_close": [100.0] * n, "last": [100.0] * n,
            "vwap": pa.array([None] * n, type=pa.float64()),
            "volume": [1000] * n, "turnover": [100_000.0] * n,
            "trades": pa.array([50] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=BARS_DAILY_SCHEMA,
    )
    for year in {d.year for d in days}:
        year_days = [d for d in days if d.year == year]
        upsert_partition(
            bars_daily_partition(parquet_root, exchange, year),
            table.filter(pa.compute.field("date").isin(year_days)),
            schema=BARS_DAILY_SCHEMA,
            replace_dates=set(year_days),
        )


class TestIngestCalendarYear:
    @respx.mock
    def test_populates_weekdays_only(self, data_dirs):
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))

        result = ingest_calendar_year(
            2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root
        )

        conn = connect(sqlite_path)
        try:
            rows = conn.execute("SELECT cal_date FROM trading_calendar").fetchall()
        finally:
            conn.close()

        stored = {date.fromisoformat(r["cal_date"]) for r in rows}
        assert stored, "expected rows"
        assert not any(d.weekday() >= 5 for d in stored), "weekends are arithmetic, not data"
        assert result.holidays == 1
        assert result.trading_days == len(stored) - 1

    @respx.mock
    def test_holiday_is_marked_with_its_description(self, data_dirs):
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))

        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT is_trading_day, holiday_description, source FROM trading_calendar "
                "WHERE cal_date='2026-01-26' AND exchange='NSE'"
            ).fetchone()
        finally:
            conn.close()

        assert row["is_trading_day"] == 0
        assert row["holiday_description"] == "Republic Day"
        assert row["source"] == AUTHORITATIVE_SOURCE

    @respx.mock
    def test_weekend_falling_holiday_does_not_create_a_row(self, data_dirs):
        """A Sunday holiday is not a trading-calendar gap. NSE lists it;
        the calendar must not store it as though a trading day were lost."""
        sqlite_path, _, raw_root = data_dirs
        sunday = date(2026, 2, 15)
        assert sunday.weekday() == 6
        _mock_holidays(_holiday_payload(("15-Feb-2026", "Mahashivratri")))

        result = ingest_calendar_year(
            2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root
        )

        conn = connect(sqlite_path)
        try:
            assert is_trading_day(conn, sunday, "NSE") is None
        finally:
            conn.close()
        assert result.holidays == 0

    @respx.mock
    def test_rerunning_is_idempotent(self, data_dirs):
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))

        def run_and_count():
            ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)
            conn = connect(sqlite_path)
            try:
                return conn.execute("SELECT count(*) AS n FROM trading_calendar").fetchone()["n"]
            finally:
                conn.close()

        assert run_and_count() == run_and_count()

    @respx.mock
    def test_raw_artifact_is_persisted_before_parsing(self, data_dirs):
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))

        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT validation FROM raw_artifacts WHERE source='nse_holiday_master'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row["validation"] == "ok"

    @respx.mock
    def test_bse_is_labelled_as_using_nse_as_a_proxy(self, data_dirs):
        """BSE has no separate feed wired up. Using NSE's calendar is a
        reasonable approximation, but it must be visible AS one."""
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))

        ingest_calendar_year(2026, exchange="BSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT source FROM trading_calendar WHERE exchange='BSE' LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert "nse_proxy" in row["source"]


class TestIngestCalendarFromBars:
    def test_derives_trading_and_non_trading_days_within_covered_range(self, data_dirs):
        sqlite_path, parquet_root, _ = data_dirs
        # Mon, Tue, Thu -- Wednesday is inside the range with no bars.
        traded = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 17)]
        _write_bars(parquet_root, "NSE", traded)

        ingest_calendar_from_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        conn = connect(sqlite_path)
        try:
            assert is_trading_day(conn, date(2026, 9, 14), "NSE") is True
            assert is_trading_day(conn, date(2026, 9, 16), "NSE") is False
            # Outside the covered range: unknown, NOT inferred.
            assert is_trading_day(conn, date(2026, 9, 18), "NSE") is None
            assert is_trading_day(conn, date(2026, 9, 11), "NSE") is None
        finally:
            conn.close()

    def test_empty_lake_is_a_no_op_not_a_failure(self, data_dirs):
        sqlite_path, parquet_root, _ = data_dirs
        result = ingest_calendar_from_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )
        assert result.trading_days == 0

    @respx.mock
    def test_observed_never_overwrites_authoritative(self, data_dirs):
        """The precedence rule. NSE says 26-Jan-2026 was a holiday; the
        lake has no bars for it either way. The stored row must keep
        NSE's description and NSE's source label."""
        sqlite_path, parquet_root, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))
        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        _write_bars(parquet_root, "NSE", [date(2026, 1, 23), date(2026, 1, 27)])
        ingest_calendar_from_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT source, holiday_description FROM trading_calendar "
                "WHERE cal_date='2026-01-26' AND exchange='NSE'"
            ).fetchone()
        finally:
            conn.close()

        assert row["source"] == AUTHORITATIVE_SOURCE
        assert row["holiday_description"] == "Republic Day"

    def test_authoritative_may_improve_an_observed_row(self, data_dirs):
        """The reverse direction IS allowed -- learning NSE's real
        answer for a date we had only inferred is strictly better."""
        sqlite_path, parquet_root, raw_root = data_dirs
        _write_bars(parquet_root, "NSE", [date(2026, 1, 23), date(2026, 1, 27)])
        ingest_calendar_from_bars(
            exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root
        )

        conn = connect(sqlite_path)
        try:
            before = conn.execute(
                "SELECT source FROM trading_calendar WHERE cal_date='2026-01-26'"
            ).fetchone()
        finally:
            conn.close()
        assert before["source"] == OBSERVED_SOURCE

        with respx.mock:
            _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))
            ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            after = conn.execute(
                "SELECT source, holiday_description FROM trading_calendar "
                "WHERE cal_date='2026-01-26'"
            ).fetchone()
        finally:
            conn.close()
        assert after["source"] == AUTHORITATIVE_SOURCE
        assert after["holiday_description"] == "Republic Day"


class TestTradingDaysBetween:
    @respx.mock
    def test_returns_none_when_the_range_is_not_fully_covered(self, data_dirs):
        """All-or-nothing: a partially-known range must not quietly
        return its known subset, or a backfill would skip every date
        the calendar has not heard of."""
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))
        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            assert trading_days_between(conn, date(2026, 1, 1), date(2026, 1, 31), "NSE")
            assert trading_days_between(conn, date(2025, 12, 1), date(2026, 1, 31), "NSE") is None
        finally:
            conn.close()

    @respx.mock
    def test_excludes_holidays_and_weekends(self, data_dirs):
        sqlite_path, _, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))
        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)

        conn = connect(sqlite_path)
        try:
            days = trading_days_between(conn, date(2026, 1, 23), date(2026, 1, 27), "NSE")
        finally:
            conn.close()

        assert days == [date(2026, 1, 23), date(2026, 1, 27)]


class TestDailyIngestHonoursTheCalendar:
    @respx.mock
    def test_known_holiday_skips_without_any_request(self, data_dirs):
        """The wiring proof: on a date the calendar says did not trade,
        the nightly ingest must not touch the network at all."""
        sqlite_path, parquet_root, raw_root = data_dirs
        _mock_holidays(_holiday_payload(("26-Jan-2026", "Republic Day")))
        ingest_calendar_year(2026, exchange="NSE", sqlite_path=sqlite_path, raw_root=raw_root)
        calls_before = len(respx.calls)

        result = ingest_nse_prices_for_date(
            date(2026, 1, 26),
            sqlite_path=sqlite_path,
            parquet_root=parquet_root,
            raw_root=raw_root,
        )

        assert result.status == "skipped_holiday"
        assert len(respx.calls) == calls_before, "a known holiday must cost zero HTTP requests"

    @respx.mock
    def test_unknown_date_still_goes_to_the_network(self, data_dirs):
        """Tri-state, not boolean: no calendar row means UNKNOWN, and
        unknown must be fetched. Collapsing it to "holiday" would
        silently skip real trading days whenever the calendar lags."""
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        route = respx.get(
            "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_17092026.csv"
        ).mock(return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"}))

        result = ingest_nse_prices_for_date(
            date(2026, 9, 17),
            sqlite_path=sqlite_path,
            parquet_root=parquet_root,
            raw_root=raw_root,
        )

        assert route.called
        assert result.status == "success"

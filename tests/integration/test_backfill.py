"""Integration tests for the backfill orchestrator, mocked via respx.

Reuses the same fixture-based approach as test_daily_ingest.py -- the
backfill orchestrator's whole design point is that it shares
ingest_nse_prices_for_date's code path rather than having its own, so
these tests focus on the range-iteration, throttle, and
continue-on-failure behaviour that IS unique to backfill.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from stk.ingest.backfill import backfill_nse_prices
from stk.store.db.engine import connect, migrate

FIXTURES = Path(__file__).parent.parent / "fixtures"
SEC_BHAVDATA_URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
)


@pytest.fixture
def data_dirs(tmp_path):
    sqlite_path = tmp_path / "app.db"
    parquet_root = tmp_path / "parquet"
    raw_root = tmp_path / "raw"
    migrate(sqlite_path)
    return sqlite_path, parquet_root, raw_root


def _mock_date(d: date, *, text: str | None = None, status: int = 200) -> None:
    url = SEC_BHAVDATA_URL_TEMPLATE.format(d=d.strftime("%d%m%Y"))
    if text is not None:
        respx.get(url).mock(
            return_value=httpx.Response(status, text=text, headers={"content-type": "text/csv"})
        )
    else:
        respx.get(url).mock(return_value=httpx.Response(status))


def _fixture_for_date(d: date) -> str:
    """Real fixture content, with every DATE1 value rewritten to `d`."""
    base = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
    lines = base.splitlines()
    new_date_str = d.strftime("%d-%b-%Y")
    rewritten = [lines[0]] + [line.replace("17-Sep-2026", new_date_str) for line in lines[1:]]
    return "\n".join(rewritten) + "\n"


class TestBackfillNsePrices:
    @respx.mock
    def test_backfills_a_short_weekday_range(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        # Mon 2026-09-14 .. Fri 2026-09-18 -- 5 weekdays, no weekend in range.
        for offset in range(5):
            d = date(2026, 9, 14) + timedelta(days=offset)
            _mock_date(d, text=_fixture_for_date(d))

        summary = backfill_nse_prices(
            date(2026, 9, 14), date(2026, 9, 18),
            sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root,
            throttle_s=0,
        )

        assert summary.total_dates == 5
        assert summary.succeeded == 5
        assert summary.failed_dates == []
        assert summary.ok is True

    @respx.mock
    def test_weekends_are_skipped_without_a_fetch_attempt(self, data_dirs):
        """2026-09-19/20 is a Sat/Sun -- must not even attempt a request."""
        sqlite_path, parquet_root, raw_root = data_dirs
        for offset in range(2):
            d = date(2026, 9, 18) + timedelta(days=offset)  # Fri, Sat
            if d.weekday() < 5:
                _mock_date(d, text=_fixture_for_date(d))

        summary = backfill_nse_prices(
            date(2026, 9, 18), date(2026, 9, 19),  # Fri, Sat
            sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root,
            throttle_s=0,
        )

        assert summary.total_dates == 1  # only the Friday counted
        assert summary.succeeded == 1

    @respx.mock
    def test_a_failed_date_is_recorded_and_iteration_continues(self, data_dirs):
        """The core resilience property: one bad date must not abort the
        whole range -- every other date should still be attempted."""
        sqlite_path, parquet_root, raw_root = data_dirs
        good1 = date(2026, 9, 14)
        bad = date(2026, 9, 15)
        good2 = date(2026, 9, 16)

        _mock_date(good1, text=_fixture_for_date(good1))
        _mock_date(bad, text="<html>server error</html>", status=200)  # content-validation failure
        _mock_date(good2, text=_fixture_for_date(good2))

        summary = backfill_nse_prices(
            good1, good2,
            sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root,
            throttle_s=0,
        )

        assert summary.total_dates == 3
        assert summary.succeeded == 2
        assert summary.failed_dates == [bad]
        assert summary.ok is False

    @respx.mock
    def test_data_not_published_counted_as_skipped_not_failed(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        d = date(2026, 9, 14)
        _mock_date(d, status=404)

        summary = backfill_nse_prices(
            d, d, sqlite_path=sqlite_path, parquet_root=parquet_root,
            raw_root=raw_root, throttle_s=0,
        )

        assert summary.skipped_holidays == 1
        assert summary.failed_dates == []
        assert summary.ok is True

    @respx.mock
    def test_on_progress_callback_invoked_per_date(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        d = date(2026, 9, 14)
        _mock_date(d, text=_fixture_for_date(d))

        calls = []
        backfill_nse_prices(
            d, d, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root,
            throttle_s=0, on_progress=lambda dt, result, error: calls.append((dt, result, error)),
        )

        assert len(calls) == 1
        assert calls[0][0] == d
        assert calls[0][1].status == "success"
        assert calls[0][2] is None

    @respx.mock
    def test_rerunning_a_backfill_range_is_idempotent(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        d = date(2026, 9, 14)
        _mock_date(d, text=_fixture_for_date(d))

        for _ in range(2):
            summary = backfill_nse_prices(
                d, d, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root,
                throttle_s=0,
            )
            assert summary.ok

        conn = connect(sqlite_path)
        try:
            attempts = conn.execute(
                "SELECT attempt FROM job_runs WHERE job_name='ingest_nse_prices' ORDER BY attempt"
            ).fetchall()
        finally:
            conn.close()
        assert [r["attempt"] for r in attempts] == [1, 2]

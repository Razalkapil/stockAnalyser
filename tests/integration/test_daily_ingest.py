"""End-to-end integration test for the daily NSE ingest orchestrator,
against a mocked HTTP response (real fixture bytes, no live network).

This exercises the full path: fetch -> validate -> persist raw ->
parse -> sanity-check -> atomic parquet write -> job_runs bookkeeping
-- the same path proven against the live endpoint during development
(see the build plan's acceptance checklist), but pinned here so it
runs in CI without network access.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
import respx

from stk.ingest.daily import ingest_nse_prices_for_date
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_17092026.csv"
BUSINESS_DATE = date(2026, 9, 17)


@pytest.fixture
def data_dirs(tmp_path):
    sqlite_path = tmp_path / "app.db"
    parquet_root = tmp_path / "parquet"
    raw_root = tmp_path / "raw"
    migrate(sqlite_path)
    return sqlite_path, parquet_root, raw_root


class TestIngestNsePricesForDate:
    @respx.mock
    def test_first_run_writes_partition_and_records_success(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )

        result = ingest_nse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "success"
        assert result.rows_written == 50

        partition = bars_daily_partition(parquet_root, "NSE", 2026)
        assert partition.exists()
        table = pq.read_table(partition)
        assert table.num_rows == 50

    @respx.mock
    def test_raw_bytes_persisted_to_disk(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )

        ingest_nse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        raw_files = list(raw_root.rglob("*.csv"))
        assert len(raw_files) == 1
        assert "20MICRONS" in raw_files[0].read_text()

    @respx.mock
    def test_raw_artifact_recorded_in_ledger(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )

        ingest_nse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT * FROM raw_artifacts WHERE source='nse_sec_bhavdata'"
            ).fetchone()
        finally:
            conn.close()
        assert row["validation"] == "ok"
        assert row["business_date"] == "2026-09-17"

    @respx.mock
    def test_job_run_recorded_as_success_with_row_counts(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )

        ingest_nse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE job_name='ingest_nse_prices'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "success"
        assert row["rows_in"] == 50
        assert row["rows_written"] == 50

    @respx.mock
    def test_rerunning_the_same_date_is_idempotent_end_to_end(self, data_dirs):
        """The full-stack version of the parquet writer's idempotency
        property: running the whole orchestrator twice for the same
        date must not duplicate rows or fail, and must record two
        distinct job_runs attempts."""
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )

        for _ in range(2):
            result = ingest_nse_prices_for_date(
                BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
            )
            assert result.status == "success"

        partition = bars_daily_partition(parquet_root, "NSE", 2026)
        table = pq.read_table(partition)
        assert table.num_rows == 50  # not 100

        conn = connect(sqlite_path)
        try:
            attempts = conn.execute(
                "SELECT attempt FROM job_runs WHERE job_name='ingest_nse_prices' ORDER BY attempt"
            ).fetchall()
        finally:
            conn.close()
        assert [r["attempt"] for r in attempts] == [1, 2]

    @respx.mock
    def test_rows_written_reflects_this_dates_count_not_cumulative_partition_total(self, data_dirs):
        """Regression test: a real live backfill run caught upsert_partition's
        cumulative row count (correct for its own purpose) being surfaced
        as if it were this date's own row count, making progress output
        climb across consecutive days in the same year instead of
        reflecting each day's actual size."""
        sqlite_path, parquet_root, raw_root = data_dirs
        day1_url = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_17092026.csv"
        day2_url = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18092026.csv"

        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        # A second, smaller fixture (first 10 rows) so the two days have
        # DIFFERENT sizes -- if the rows_written bug were present, day 2's
        # reported count would be 60 (50+10 cumulative), not 10. Dates are
        # rewritten to 18-Sep-2026 so this also passes the (separate,
        # equally real) date-content-match assertion added after this
        # test was first written -- see assert_bars_match_requested_date.
        lines = text.splitlines()
        smaller_text = "\n".join(
            [lines[0]] + [line.replace("17-Sep-2026", "18-Sep-2026") for line in lines[1:11]]
        ) + "\n"

        respx.get(day1_url).mock(
            return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
        )
        respx.get(day2_url).mock(
            return_value=httpx.Response(
                200, text=smaller_text, headers={"content-type": "text/csv"}
            )
        )

        result1 = ingest_nse_prices_for_date(
            date(2026, 9, 17), sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )
        result2 = ingest_nse_prices_for_date(
            date(2026, 9, 18), sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result1.rows_written == 50
        assert result2.rows_written == 10  # NOT 60

    @respx.mock
    def test_data_not_published_marks_skipped_holiday(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        respx.get(URL).mock(return_value=httpx.Response(404))

        result = ingest_nse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "skipped_holiday"
        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='ingest_nse_prices'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "skipped_holiday"

    @respx.mock
    def test_content_validation_failure_recorded_as_failed_job(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text="<html>oops</html>", headers={"content-type": "text/html"}
            )
        )

        with pytest.raises(Exception):  # noqa: B017 -- ContentValidationError
            ingest_nse_prices_for_date(
                BUSINESS_DATE, sqlite_path=sqlite_path,
                parquet_root=parquet_root, raw_root=raw_root,
            )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT status, error_type FROM job_runs WHERE job_name='ingest_nse_prices'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "failed"
        assert row["error_type"] == "ContentValidationError"

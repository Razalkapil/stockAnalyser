"""End-to-end integration test for the daily BSE ingest orchestrator.

Both ingest_nse_prices_for_date and ingest_bse_prices_for_date share
the same _ingest_prices_for_date body (see ingest.daily) -- the shared
mechanics (job_run scoping, raw persistence, idempotency, sanity/date
assertions) are already exercised thoroughly against NSE fixtures in
test_daily_ingest.py. This file only covers what's BSE-specific: the
UDiFF parse path, the legacy pre-2024-07-08 parse path (now that both
BSE sources are wired into get_bse_price_provider_for_date), and the
SPA-shell -> skipped_holiday behaviour (which applies to both source's
URL families).
"""

from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
import respx

from stk.ingest.daily import ingest_bse_prices_for_date
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20260917_F_0000.CSV"
BUSINESS_DATE = date(2026, 9, 17)
LEGACY_URL = "https://www.bseindia.com/download/BhavCopy/Equity/EQ040110_CSV.ZIP"
LEGACY_BUSINESS_DATE = date(2010, 1, 4)


@pytest.fixture
def data_dirs(tmp_path):
    sqlite_path = tmp_path / "app.db"
    parquet_root = tmp_path / "parquet"
    raw_root = tmp_path / "raw"
    migrate(sqlite_path)
    return sqlite_path, parquet_root, raw_root


class TestIngestBsePricesForDate:
    @respx.mock
    def test_first_run_writes_partition_and_records_success(self, data_dirs):
        sqlite_path, parquet_root, raw_root = data_dirs
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text=text, headers={"content-type": "application/octet-stream"}
            )
        )

        result = ingest_bse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "success"
        assert result.rows_written == 50

        partition = bars_daily_partition(parquet_root, "BSE", 2026)
        assert partition.exists()
        table = pq.read_table(partition)
        assert table.num_rows == 50

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='ingest_bse_prices'"
            ).fetchone()
            artifact_row = conn.execute(
                "SELECT validation FROM raw_artifacts WHERE source='bse_udiff'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "success"
        assert artifact_row["validation"] == "ok"

    @respx.mock
    def test_spa_shell_marks_skipped_holiday_not_failed(self, data_dirs):
        """The BSE-specific failure mode: a non-trading day returns HTTP
        200 with an HTML SPA shell, not a 404. This must still resolve
        to skipped_holiday, the same as NSE's 404 case -- not a failed job."""
        sqlite_path, parquet_root, raw_root = data_dirs
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text="<html><title>BSE</title></html>", headers={"content-type": "text/html"}
            )
        )

        result = ingest_bse_prices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "skipped_holiday"
        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='ingest_bse_prices'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "skipped_holiday"

    @respx.mock
    def test_date_before_udiff_start_uses_legacy_source(self, data_dirs):
        """2010-01-04 is before the UDiFF cutover, so
        get_bse_price_provider_for_date must route to
        BseLegacyBhavcopyProvider instead of raising -- this is the
        behaviour change from the deferred spike step 4 being resolved
        (see docs/adr/0003-historical-price-source.md)."""
        sqlite_path, parquet_root, raw_root = data_dirs
        csv_text = (FIXTURES / "bse" / "legacy_EQ040110.CSV").read_text()
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("EQ040110.CSV", csv_text)
        respx.get(LEGACY_URL).mock(
            return_value=httpx.Response(
                200,
                content=buf.getvalue(),
                headers={"content-type": "application/x-zip-compressed"},
            )
        )

        result = ingest_bse_prices_for_date(
            LEGACY_BUSINESS_DATE, sqlite_path=sqlite_path,
            parquet_root=parquet_root, raw_root=raw_root,
        )

        assert result.status == "success"
        assert result.rows_written == 50

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='ingest_bse_prices'"
            ).fetchone()
        finally:
            conn.close()
        assert row["status"] == "success"

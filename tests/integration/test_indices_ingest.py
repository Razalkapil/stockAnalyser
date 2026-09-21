"""Integration test for the index ingest orchestrator.

Mirrors test_daily_ingest's shape: real fixture bytes through respx,
no live network. Checks the pieces unique to this path -- the
year-only partition layout, the non-default sort key (indices_daily
has no `symbol` column), and the manifest with no exchange dimension.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
import respx

from stk.core.errors import IngestAssertionError
from stk.ingest.indices import ingest_indices_for_date, reparse_indices_from_raw
from stk.ingest.jobs import job_run
from stk.ingest.raw_store import persist_artifact
from stk.providers.base import RawArtifact
from stk.store import duck
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import indices_daily_partition
from stk.store.parquet.writer import read_manifest

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_17092026.csv"
BUSINESS_DATE = date(2026, 9, 17)


@pytest.fixture
def env(tmp_path):
    sqlite_path = tmp_path / "app.db"
    migrate(sqlite_path)
    return sqlite_path, tmp_path / "parquet", tmp_path / "raw"


def _mock(text: str | None = None) -> None:
    default = (FIXTURES / "nse" / "ind_close_all_17092026.csv").read_text()
    body = text if text is not None else default
    respx.get(URL).mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/csv"})
    )


class TestIngestIndicesForDate:
    @respx.mock
    def test_writes_a_year_partition(self, env):
        sqlite_path, parquet_root, raw_root = env
        _mock()

        result = ingest_indices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "success"
        partition = indices_daily_partition(parquet_root, 2026)
        assert partition.exists()
        rows = pq.read_table(partition).to_pylist()
        assert {r["index_name"] for r in rows} >= {"Nifty 50", "Nifty Bank"}

    @respx.mock
    def test_writes_a_manifest_with_no_exchange_dimension(self, env):
        sqlite_path, parquet_root, raw_root = env
        _mock()

        ingest_indices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        manifest = read_manifest(parquet_root, dataset="indices_daily", exchange=None, year=2026)
        assert manifest is not None
        assert manifest["exchange"] is None
        assert manifest["row_count"] == pq.read_table(
            indices_daily_partition(parquet_root, 2026)
        ).num_rows

    @respx.mock
    def test_rerunning_is_idempotent(self, env):
        sqlite_path, parquet_root, raw_root = env
        _mock()

        def run():
            ingest_indices_for_date(
                BUSINESS_DATE,
                sqlite_path=sqlite_path,
                parquet_root=parquet_root,
                raw_root=raw_root,
            )
            return pq.read_table(indices_daily_partition(parquet_root, 2026)).to_pylist()

        assert len(run()) == len(run())

    @respx.mock
    def test_raw_bytes_are_persisted(self, env):
        sqlite_path, parquet_root, raw_root = env
        _mock()

        ingest_indices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT validation FROM raw_artifacts WHERE source='nse_indices'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row["validation"] == "ok"

    @respx.mock
    def test_a_404_is_recorded_as_skipped_not_failed(self, env):
        sqlite_path, parquet_root, raw_root = env
        respx.get(URL).mock(return_value=httpx.Response(404, text="not found"))

        result = ingest_indices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        assert result.status == "skipped_holiday"

    @respx.mock
    def test_content_dated_differently_from_the_request_is_refused(self, env):
        """ADR 0003's mislabeled-content trap, applied to the index
        archive: writing this under the requested date's key would
        corrupt that date's history."""
        sqlite_path, parquet_root, raw_root = env
        text = (FIXTURES / "nse" / "ind_close_all_17092026.csv").read_text()
        _mock(text.replace("17-09-2026", "27-06-2019"))

        with pytest.raises(IngestAssertionError, match="content is dated"):
            ingest_indices_for_date(
                BUSINESS_DATE,
                sqlite_path=sqlite_path,
                parquet_root=parquet_root,
                raw_root=raw_root,
            )

        assert not indices_daily_partition(parquet_root, 2026).exists()

    @respx.mock
    def test_benchmark_series_query_uses_the_canonical_code(self, env):
        sqlite_path, parquet_root, raw_root = env
        _mock()
        ingest_indices_for_date(
            BUSINESS_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        )

        with duck.connect(parquet_root) as session:
            rows = session.sql(
                "benchmark_series", ["NIFTY_50", "2026-01-01", "2026-12-31"]
            ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == BUSINESS_DATE


FY_DATE = date(2025, 4, 1)
FY_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_01042025.csv"
FY_FILE = FIXTURES / "nse" / "ind_close_all_01042025_fy_boundary.csv"


class TestFinancialYearBoundary:
    """NSE's "Nifty50 Dividend Points" is a cumulative counter that RESETS TO ZERO on the first
    sessions of each financial year (real file, 2025-04-01: close 0.0, no open/high/low). It used
    to abort the whole day and cost the benchmark 65 trading days between 2021 and 2026."""

    @respx.mock
    def test_a_real_fy_boundary_file_is_ingested_with_its_zero_counter(self, env):
        sqlite_path, parquet_root, raw_root = env
        respx.get(FY_URL).mock(return_value=httpx.Response(
            200, text=FY_FILE.read_text(), headers={"content-type": "text/csv"}))

        result = ingest_indices_for_date(
            FY_DATE, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root)

        assert result.status == "success"
        rows = {r["index_name"]: r for r in
                pq.read_table(indices_daily_partition(parquet_root, 2025)).to_pylist()}
        assert rows["Nifty50 Dividend Points"]["close"] == 0.0
        assert rows["Nifty 500"]["close"] > 0  # the benchmark the day was being lost for

    def test_a_zero_close_is_still_fatal_for_a_price_level_index(self):
        from stk.ingest.assertions import assert_index_bars_sane  # noqa: PLC0415
        from stk.ingest.normalise import parse_ind_close_all  # noqa: PLC0415

        text = FY_FILE.read_text().replace(
            "Nifty 500,01-04-2025,21227.1,21398.35,21042.45,21070.75",
            "Nifty 500,01-04-2025,21227.1,21398.35,21042.45,0.0")
        bars = parse_ind_close_all(text)
        with pytest.raises(IngestAssertionError, match="non-positive close"):
            assert_index_bars_sane(bars, context="t")

    def test_a_negative_close_is_fatal_even_for_a_derived_counter(self):
        from stk.ingest.assertions import assert_index_bars_sane  # noqa: PLC0415
        from stk.ingest.normalise import parse_ind_close_all  # noqa: PLC0415

        bars = parse_ind_close_all(FY_FILE.read_text().replace(
            "Dividend Points,01-04-2025,-,-,-,0.0", "Dividend Points,01-04-2025,-,-,-,-3.0"))
        with pytest.raises(IngestAssertionError, match="non-positive close"):
            assert_index_bars_sane(bars, context="t")

    def test_reparse_recovers_a_failed_day_offline_and_supersedes_the_failure(self, env):
        """The day failed under the old rule and its bytes were stored. The re-parse needs no
        network (respx is not active: any HTTP call would raise) and must leave the day's NEWEST
        attempt a success, or `stk doctor` would keep alerting on a day that is now fixed."""
        sqlite_path, parquet_root, raw_root = env
        conn = connect(sqlite_path)
        try:
            persist_artifact(raw_root, conn, RawArtifact(
                source="nse_indices", business_date=FY_DATE, url=FY_URL,
                content=FY_FILE.read_bytes(), content_type="text/csv", http_status=200,
                fetched_at=datetime.now(UTC)))
            with pytest.raises(RuntimeError), job_run(
                    conn, "ingest_indices", business_date=FY_DATE):
                raise RuntimeError("index Nifty50 Dividend Points has non-positive close 0.0")
        finally:
            conn.close()

        result = reparse_indices_from_raw(
            sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root)

        assert result.reparsed == [FY_DATE] and not result.still_failing
        assert pq.read_table(indices_daily_partition(parquet_root, 2025)).num_rows == 4
        conn = connect(sqlite_path)
        try:
            newest = conn.execute(
                "SELECT status FROM job_runs WHERE job_name='ingest_indices' "
                "ORDER BY attempt DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        assert newest["status"] == "success"

        # Nothing left to recover: a second run is a no-op, not a rewrite.
        again = reparse_indices_from_raw(
            sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root)
        assert again.reparsed == []

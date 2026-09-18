"""Integration test for the index ingest orchestrator.

Mirrors test_daily_ingest's shape: real fixture bytes through respx,
no live network. Checks the pieces unique to this path -- the
year-only partition layout, the non-default sort key (indices_daily
has no `symbol` column), and the manifest with no exchange dimension.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
import respx

from stk.core.errors import IngestAssertionError
from stk.ingest.indices import ingest_indices_for_date
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

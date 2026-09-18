"""Integration tests for the DuckDB query layer.

store/duck.py is the only sanctioned way anything outside store/ reads
the parquet lake, so the behaviours that matter here are the ones a
consumer relies on without thinking about: a dataset that does not
exist yet still queries cleanly, hive partition columns really are
columns, the dimension join resolves a renamed symbol correctly, and a
typo in a query name fails loudly rather than returning nothing.

Every test forces the Arrow dimension mode (allow_extension=False):
the suite must never reach extensions.duckdb.org.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from stk.core.errors import ConfigError
from stk.store import duck
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition

DAY = date(2026, 9, 17)


def _bars(exchange: str, symbol: str, days: list[date], close: float = 100.0) -> pa.Table:
    n = len(days)
    return pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "exchange": pa.array([exchange] * n).dictionary_encode(),
            "symbol": [symbol] * n,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array(["EQ"] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": [close] * n,
            "high": [close] * n,
            "low": [close] * n,
            "close": [close] * n,
            "prev_close": [close] * n,
            "last": [close] * n,
            "vwap": pa.array([None] * n, type=pa.float64()),
            "volume": [1000] * n,
            "turnover": [close * 1000] * n,
            "trades": pa.array([50] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=BARS_DAILY_SCHEMA,
    )


def _write(parquet_root: Path, exchange: str, symbol: str, days: list[date], **kw) -> None:
    upsert_partition(
        bars_daily_partition(parquet_root, exchange, days[0].year),
        _bars(exchange, symbol, days, **kw),
        schema=BARS_DAILY_SCHEMA,
        replace_dates=set(days),
    )


class TestViewRegistration:
    def test_bars_view_reads_written_partitions(self, tmp_parquet_root):
        _write(tmp_parquet_root, "NSE", "AAA", [DAY])

        with duck.connect(tmp_parquet_root) as session:
            rows = session.con.execute("SELECT symbol, close FROM bars_daily").fetchall()

        assert rows == [("AAA", 100.0)]

    def test_hive_partition_columns_are_queryable(self, tmp_parquet_root):
        """exchange/year come from the directory names, not the file --
        the liquidity and coverage queries filter on them."""
        _write(tmp_parquet_root, "NSE", "AAA", [DAY])
        _write(tmp_parquet_root, "BSE", "500325", [DAY])

        with duck.connect(tmp_parquet_root) as session:
            rows = session.con.execute(
                "SELECT exchange, year, count(*) FROM bars_daily GROUP BY 1, 2 ORDER BY 1"
            ).fetchall()

        assert rows == [("BSE", 2026, 1), ("NSE", 2026, 1)]

    def test_missing_dataset_registers_an_empty_typed_view(self, tmp_parquet_root):
        """A fresh checkout has no bars_daily_adjusted. Querying it must
        return zero rows with the right columns -- not raise -- because
        "not ingested yet" is a normal state, not a failure."""
        with duck.connect(tmp_parquet_root) as session:
            rows = session.con.execute("SELECT * FROM bars_daily_adjusted").fetchall()
            columns = [d[0] for d in session.con.description]

        assert rows == []
        assert "cumulative_price_factor" in columns
        assert "close" in columns

    def test_every_dataset_has_a_view_even_on_an_empty_root(self, tmp_parquet_root):
        with duck.connect(tmp_parquet_root) as session:
            for dataset in ("bars_daily", "bars_daily_adjusted", "liquidity_daily"):
                assert session.con.execute(f"SELECT count(*) FROM {dataset}").fetchone() == (0,)


class TestNamedQueries:
    def test_unknown_query_name_raises_with_the_known_names(self):
        with pytest.raises(KeyError, match="no named query"):
            duck.named_query("definitely_not_a_query")

    def test_known_queries_are_loaded_from_every_sql_file(self):
        for name in ("adjusted_bars_for_symbol", "liquidity_metrics", "dates_present"):
            assert duck.named_query(name).strip()

    def test_dates_present_returns_only_that_exchange(self, tmp_parquet_root):
        _write(tmp_parquet_root, "NSE", "AAA", [date(2026, 9, 16), DAY])
        _write(tmp_parquet_root, "BSE", "500325", [date(2026, 9, 15)])

        with duck.connect(tmp_parquet_root) as session:
            rows = session.sql("dates_present", ["NSE"]).fetchall()

        assert [r[0] for r in rows] == [date(2026, 9, 16), DAY]

    def test_stale_symbols_reports_last_bar_date(self, tmp_parquet_root):
        _write(tmp_parquet_root, "NSE", "FRESH", [DAY])
        _write(tmp_parquet_root, "NSE", "STALE", [date(2026, 1, 5)])

        with duck.connect(tmp_parquet_root) as session:
            rows = session.sql("stale_symbols", ["NSE", date(2026, 6, 1).isoformat()]).fetchall()

        assert rows == [("STALE", date(2026, 1, 5))]


class TestDimensions:
    @pytest.fixture
    def migrated_db(self, tmp_db_path):
        migrate(tmp_db_path)
        return tmp_db_path

    def test_arrow_mode_exposes_dimension_views(self, tmp_parquet_root, migrated_db):
        with duck.connect(tmp_parquet_root, migrated_db, allow_extension=False) as session:
            assert session.dimension_mode is duck.DimensionMode.ARROW_COPY
            assert session.con.execute("SELECT count(*) FROM dim_securities").fetchone() == (0,)

    def test_missing_database_fails_loudly(self, tmp_parquet_root, tmp_path):
        with pytest.raises(ConfigError, match="stk db migrate"):
            duck.connect(tmp_parquet_root, tmp_path / "nope.db", allow_extension=False)

    def test_renamed_symbol_resolves_to_its_security_via_symbol_history(
        self, tmp_parquet_root, migrated_db
    ):
        """The load-bearing case for query-time identity resolution: a
        bar written under a symbol the company no longer uses must still
        resolve to the right security. A security_id frozen into the
        parquet at ingest time could not do this retroactively."""
        conn = connect(migrated_db)
        try:
            conn.execute(
                "INSERT INTO securities (isin, canonical_symbol, company_name, "
                "primary_exchange, status, first_seen_on, last_seen_on, updated_at) "
                "VALUES ('INE000A01001', 'NEWNAME', 'Example Ltd', 'NSE', 'ACTIVE', "
                "'2020-01-01', '2026-09-17', '2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO listings (security_id, exchange, symbol, series, status, "
                "source, updated_at) "
                "VALUES (1, 'NSE', 'NEWNAME', 'EQ', 'ACTIVE', 'test', "
                "'2026-09-17T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO symbol_history (security_id, exchange, symbol, valid_from, valid_to) "
                "VALUES (1, 'NSE', 'OLDNAME', '2020-01-01', '2026-01-01')"
            )
            conn.execute(
                "INSERT INTO symbol_history (security_id, exchange, symbol, valid_from, valid_to) "
                "VALUES (1, 'NSE', 'NEWNAME', '2026-01-01', NULL)"
            )
        finally:
            conn.close()

        _write(tmp_parquet_root, "NSE", "OLDNAME", [date(2025, 6, 2)])

        with duck.connect(tmp_parquet_root, migrated_db, allow_extension=False) as session:
            rows = session.sql(
                "bars_with_resolved_identity",
                ["NSE", date(2025, 1, 1).isoformat(), date(2025, 12, 31).isoformat()],
            ).fetchall()
            columns = [d[0] for d in session.con.description]

        assert len(rows) == 1
        row = dict(zip(columns, rows[0], strict=True))
        assert row["symbol"] == "OLDNAME"
        assert row["resolved_security_id"] == 1
        assert row["resolved_isin"] == "INE000A01001"

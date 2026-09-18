"""Integration tests for the liquidity feature/universe computation.

Builds synthetic bars_daily partitions directly (bypassing the ingest
fetch/parse path entirely -- this is a pure derived-feature step over
already-ingested data, so its tests should not need respx mocking at
all) and exercises compute_liquidity_for_date end-to-end: DuckDB
aggregation, domain.universe.is_liquid application, the parquet
feature write, and the universe_current SQLite upsert.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stk.config.universe import LiquidityConfig, UniverseConfig
from stk.ingest.liquidity import compute_liquidity_for_date
from stk.store.db.engine import connect, migrate
from stk.store.parquet.layout import bars_daily_partition, liquidity_daily_partition
from stk.store.parquet.schema import BARS_DAILY_SCHEMA


def _make_universe_config(**overrides) -> UniverseConfig:
    liquidity_kwargs = dict(
        lookback_days=20,
        min_median_turnover_inr=1_000_000.0,
        min_median_trades=100.0,
        min_price_inr=10.0,
        min_listed_days=5,
    )
    liquidity_kwargs.update(overrides)
    return UniverseConfig(liquidity=LiquidityConfig(**liquidity_kwargs))


def _write_bars(
    parquet_root: Path,
    *,
    exchange: str,
    symbol: str,
    dates: list[date],
    close: float = 100.0,
    volume: int = 100_000,
    turnover: float = 10_000_000.0,
    trades: int = 500,
) -> None:
    n = len(dates)
    table = pa.table(
        {
            "date": pa.array(dates, type=pa.date32()),
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
            "volume": [volume] * n,
            "turnover": [turnover] * n,
            "trades": pa.array([trades] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array(
                [datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")
            ),
        },
        schema=BARS_DAILY_SCHEMA,
    )
    years = {d.year for d in dates}
    for year in years:
        year_dates = [d for d in dates if d.year == year]
        year_table = table.filter(pa.compute.field("date").isin(year_dates))
        path = bars_daily_partition(parquet_root, exchange, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(year_table, path)


def _trading_days(end: date, n: int) -> list[date]:
    """n consecutive weekdays ending at (and including) end."""
    days: list[date] = []
    current = end
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return sorted(days)


class TestComputeLiquidityForDate:
    def test_liquid_symbol_marked_liquid_in_parquet(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 30)
        _write_bars(parquet_root, exchange="NSE", symbol="LIQUIDCO", dates=dates)

        result = compute_liquidity_for_date(
            as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
            universe_config=_make_universe_config(),
        )

        assert result.symbols_evaluated == 1
        assert result.symbols_liquid == 1

        partition = liquidity_daily_partition(parquet_root, "NSE", as_of.year)
        table = pq.read_table(partition)
        assert table.num_rows == 1
        row = table.to_pylist()[0]
        assert row["symbol"] == "LIQUIDCO"
        assert row["is_liquid"] is True
        assert row["listed_days"] == 30
        assert row["median_turnover_20d"] == 10_000_000.0

    def test_illiquid_symbol_fails_thresholds(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 30)
        _write_bars(
            parquet_root, exchange="NSE", symbol="THINCO", dates=dates,
            turnover=1_000.0, trades=1,
        )

        result = compute_liquidity_for_date(
            as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
            universe_config=_make_universe_config(),
        )

        assert result.symbols_liquid == 0

    def test_recently_listed_symbol_fails_on_listed_days(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 3)  # fewer than min_listed_days=5
        _write_bars(parquet_root, exchange="NSE", symbol="NEWCO", dates=dates)

        result = compute_liquidity_for_date(
            as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
            universe_config=_make_universe_config(),
        )

        assert result.symbols_liquid == 0

    def test_no_bars_ingested_yet_is_empty_not_an_error(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        result = compute_liquidity_for_date(
            date(2026, 9, 17), exchange="NSE", sqlite_path=sqlite_path,
            parquet_root=parquet_root, universe_config=_make_universe_config(),
        )

        assert result.symbols_evaluated == 0
        assert result.symbols_liquid == 0

    def test_universe_current_populated_when_security_resolves(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        conn = connect(sqlite_path)
        try:
            conn.execute(
                """INSERT INTO securities
                   (security_id, isin, canonical_symbol, company_name, primary_exchange,
                    status, first_seen_on, last_seen_on, updated_at)
                   VALUES (1, 'INE000A00000', 'LIQUIDCO', 'Liquid Co', 'NSE',
                           'ACTIVE', '2020-01-01', '2026-09-17', '2026-09-17')"""
            )
            conn.execute(
                """INSERT INTO listings
                   (security_id, exchange, symbol, series, status, source, updated_at)
                   VALUES (1, 'NSE', 'LIQUIDCO', 'EQ', 'ACTIVE', 'test', '2026-09-17')"""
            )
        finally:
            conn.close()

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 30)
        _write_bars(parquet_root, exchange="NSE", symbol="LIQUIDCO", dates=dates)

        compute_liquidity_for_date(
            as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
            universe_config=_make_universe_config(),
        )

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT security_id, is_liquid, as_of_date FROM universe_current"
            ).fetchone()
        finally:
            conn.close()
        assert row["security_id"] == 1
        assert row["is_liquid"] == 1
        assert row["as_of_date"] == as_of.isoformat()

    def test_unresolved_symbol_skipped_in_universe_current_not_a_failure(self, tmp_path):
        """No security master data exists yet -- documented known
        limitation in ingest.liquidity's module docstring: the parquet
        feature build must still succeed even though nothing can be
        upserted into universe_current."""
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 30)
        _write_bars(parquet_root, exchange="NSE", symbol="UNMAPPEDCO", dates=dates)

        result = compute_liquidity_for_date(
            as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
            universe_config=_make_universe_config(),
        )
        assert result.symbols_evaluated == 1

        conn = connect(sqlite_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM universe_current").fetchone()["c"]
        finally:
            conn.close()
        assert count == 0

    def test_rerunning_is_idempotent(self, tmp_path):
        parquet_root = tmp_path / "parquet"
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        as_of = date(2026, 9, 17)
        dates = _trading_days(as_of, 30)
        _write_bars(parquet_root, exchange="NSE", symbol="LIQUIDCO", dates=dates)

        for _ in range(2):
            compute_liquidity_for_date(
                as_of, exchange="NSE", sqlite_path=sqlite_path, parquet_root=parquet_root,
                universe_config=_make_universe_config(),
            )

        partition = liquidity_daily_partition(parquet_root, "NSE", as_of.year)
        table = pq.read_table(partition)
        assert table.num_rows == 1  # not doubled

"""Build tiny synthetic parquet lakes for integration tests (adjusted bars + index closes)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pyarrow as pa

from stk.store.parquet.layout import (
    bars_daily_adjusted_partition,
    bars_daily_partition,
    indices_daily_partition,
)
from stk.store.parquet.schema import (
    BARS_DAILY_ADJUSTED_SCHEMA,
    BARS_DAILY_SCHEMA,
    INDICES_DAILY_SCHEMA,
)
from stk.store.parquet.writer import upsert_partition

NOW = datetime.now(UTC)
# indices_daily has no symbol column, so the writer's default sort key cannot apply.
INDEX_SORT = [("index_name", "ascending"), ("date", "ascending")]


def days_from(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def adjusted_table(
    symbol: str,
    days: list[date],
    closes: list[float],
    *,
    series: str = "EQ",
    volume: int = 1000,
    factor: float = 1.0,
) -> pa.Table:
    n = len(days)
    return pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "exchange": pa.array(["NSE"] * n).dictionary_encode(),
            "symbol": [symbol] * n,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array([series] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "prev_close": pa.array([None] * n, type=pa.float64()),
            "last": closes,
            "vwap": pa.array([None] * n, type=pa.float64()),
            "volume": pa.array([volume] * n, type=pa.int64()),
            "turnover": [c * volume for c in closes],
            "trades": pa.array([None] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([NOW] * n, type=pa.timestamp("us", tz="UTC")),
            "cumulative_price_factor": [factor] * n,
            "cumulative_volume_factor": [1.0] * n,
        },
        schema=BARS_DAILY_ADJUSTED_SCHEMA,
    )


def index_table(code: str, name: str, days: list[date], closes: list[float]) -> pa.Table:
    n = len(days)
    nulls = pa.array([None] * n, type=pa.float64())
    return pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "index_name": [name] * n,
            "index_code": pa.array([code] * n).dictionary_encode(),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "points_change": nulls, "pct_change": nulls,
            "volume": pa.array([None] * n, type=pa.int64()),
            "turnover": nulls, "pe": nulls, "pb": nulls, "div_yield": nulls,
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([NOW] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=INDICES_DAILY_SCHEMA,
    )


def write_bars(root, symbol, days, closes):
    upsert_partition(
        bars_daily_adjusted_partition(root, "NSE", days[0].year),
        adjusted_table(symbol, days, closes),
        schema=BARS_DAILY_ADJUSTED_SCHEMA,
        replace_dates=set(days),
    )




def write_bars_by_year(root, symbol: str, days: list[date], closes: list[float]) -> None:
    """Like write_bars, but split across the year partitions the real lake uses."""
    for year in sorted({d.year for d in days}):
        idx = [i for i, d in enumerate(days) if d.year == year]
        yd = [days[i] for i in idx]
        upsert_partition(
            bars_daily_adjusted_partition(root, "NSE", year),
            adjusted_table(symbol, yd, [closes[i] for i in idx]),
            schema=BARS_DAILY_ADJUSTED_SCHEMA,
            replace_dates=set(yd),
        )


def write_index_by_year(root, code: str, name: str, days: list[date], closes: list[float]) -> None:
    for year in sorted({d.year for d in days}):
        idx = [i for i, d in enumerate(days) if d.year == year]
        yd = [days[i] for i in idx]
        upsert_partition(
            indices_daily_partition(root, year),
            index_table(code, name, yd, [closes[i] for i in idx]),
            schema=INDICES_DAILY_SCHEMA,
            replace_dates=set(yd),
            sort_keys=INDEX_SORT,
        )


def write_panel_by_year(root, days: list[date], closes_by_symbol: dict[str, list[float]]) -> None:
    """Write MANY symbols across the year partitions in one go (both bars datasets).

    A real lake has ``bars_daily`` (what ingest wrote, the freshness truth) AND
    ``bars_daily_adjusted`` (derived from it); the API reads the former for "latest data" and
    the backtest reads the latter, so a fixture needs both.

    upsert_partition REPLACES the given dates for the whole partition, so writing symbols one
    call at a time silently leaves only the last one. (write_bars_by_year is fine for a
    single symbol; use this for a market.)
    """
    for year in sorted({d.year for d in days}):
        idx = [i for i, d in enumerate(days) if d.year == year]
        yd = [days[i] for i in idx]
        tables = [adjusted_table(sym, yd, [closes[i] for i in idx])
                  for sym, closes in closes_by_symbol.items()]
        adjusted = pa.concat_tables(tables)
        upsert_partition(
            bars_daily_adjusted_partition(root, "NSE", year), adjusted,
            schema=BARS_DAILY_ADJUSTED_SCHEMA, replace_dates=set(yd),
        )
        upsert_partition(
            bars_daily_partition(root, "NSE", year),
            adjusted.select(BARS_DAILY_SCHEMA.names).cast(BARS_DAILY_SCHEMA),
            schema=BARS_DAILY_SCHEMA, replace_dates=set(yd),
        )

"""backtest.data reads adjusted bars and the benchmark through store.duck."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pyarrow as pa
import pytest

from stk.backtest.data import load_benchmark, load_market_data
from stk.store.parquet.layout import bars_daily_adjusted_partition, indices_daily_partition
from stk.store.parquet.schema import BARS_DAILY_ADJUSTED_SCHEMA, INDICES_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition

NOW = datetime.now(UTC)
# indices_daily has no symbol column, so the writer's default sort key cannot apply.
INDEX_SORT = [("index_name", "ascending"), ("date", "ascending")]


def _days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _adjusted(symbol: str, days: list[date], closes: list[float]) -> pa.Table:
    n = len(days)
    return pa.table(
        {
            "date": pa.array(days, type=pa.date32()),
            "exchange": pa.array(["NSE"] * n).dictionary_encode(),
            "symbol": [symbol] * n,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array(["EQ"] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "prev_close": pa.array([None] * n, type=pa.float64()),
            "last": closes,
            "vwap": pa.array([None] * n, type=pa.float64()),
            "volume": pa.array([1000] * n, type=pa.int64()),
            "turnover": [c * 1000 for c in closes],
            "trades": pa.array([None] * n, type=pa.int64()),
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["test"] * n).dictionary_encode(),
            "ingested_at": pa.array([NOW] * n, type=pa.timestamp("us", tz="UTC")),
            "cumulative_price_factor": [1.0] * n,
            "cumulative_volume_factor": [1.0] * n,
        },
        schema=BARS_DAILY_ADJUSTED_SCHEMA,
    )


def _index(code: str, name: str, days: list[date], closes: list[float]) -> pa.Table:
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


def _write_bars(root, symbol, days, closes):
    upsert_partition(
        bars_daily_adjusted_partition(root, "NSE", days[0].year),
        _adjusted(symbol, days, closes),
        schema=BARS_DAILY_ADJUSTED_SCHEMA,
        replace_dates=set(days),
    )


class TestLoadMarketData:
    def test_loads_prepared_bars_with_past_only_derived_columns(self, tmp_parquet_root):
        days = _days(date(2024, 3, 1), 5)
        _write_bars(tmp_parquet_root, "AAA", days, [100.0, 101.0, 102.0, 103.0, 104.0])
        data = load_market_data(tmp_parquet_root, exchange="NSE", start=days[0], end=days[-1],
                                adv_lookback_days=20)
        bars = data.bars[data.bars["symbol"] == "AAA"].reset_index(drop=True)
        assert len(bars) == 5
        assert bars["prev_close"].isna().iloc[0]  # nothing precedes the first bar
        assert bars["prev_close"].iloc[1] == pytest.approx(100.0)
        assert bars["adv_turnover"].isna().iloc[0]
        assert bars["adv_turnover"].iloc[1] == pytest.approx(100.0 * 1000)  # day 0 only

    def test_symbols_do_not_contaminate_each_others_derived_columns(self, tmp_parquet_root):
        days = _days(date(2024, 3, 1), 3)
        both = pa.concat_tables(
            [_adjusted("AAA", days, [100.0] * 3), _adjusted("BBB", days, [500.0] * 3)]
        )
        upsert_partition(
            bars_daily_adjusted_partition(tmp_parquet_root, "NSE", 2024),
            both,
            schema=BARS_DAILY_ADJUSTED_SCHEMA,
            replace_dates=set(days),
        )
        data = load_market_data(tmp_parquet_root, exchange="NSE", start=days[0], end=days[-1],
                                adv_lookback_days=20)
        aaa = data.bars[data.bars["symbol"] == "AAA"]
        bbb = data.bars[data.bars["symbol"] == "BBB"]
        assert aaa["prev_close"].dropna().tolist() == [100.0, 100.0]  # never BBB's 500
        assert bbb["prev_close"].dropna().tolist() == [500.0, 500.0]

    def test_empty_lake_fails_loudly_with_the_fix_in_the_message(self, tmp_parquet_root):
        with pytest.raises(ValueError, match="stk backfill prices"):
            load_market_data(tmp_parquet_root, exchange="NSE", start=date(2024, 1, 1),
                             end=date(2024, 1, 31), adv_lookback_days=20)


class TestLoadBenchmark:
    def test_keys_on_canonical_code_across_a_rename(self, tmp_parquet_root):
        """NSE renamed the index between 2015 and 2016; a name filter would return a fragment."""
        a, b = _days(date(2015, 1, 1), 3), _days(date(2016, 1, 1), 3)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2015),
                         _index("NIFTY_500", "CNX 500", a, [1.0, 2.0, 3.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(a), sort_keys=INDEX_SORT)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2016),
                         _index("NIFTY_500", "Nifty 500", b, [4.0, 5.0, 6.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(b), sort_keys=INDEX_SORT)
        df = load_benchmark(tmp_parquet_root, index_code="NIFTY_500", start=a[0], end=b[-1])
        assert df["close"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    def test_other_indices_are_excluded(self, tmp_parquet_root):
        days = _days(date(2024, 1, 1), 2)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2024),
                         _index("NIFTY_50", "Nifty 50", days, [9.0, 9.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(days), sort_keys=INDEX_SORT)
        df = load_benchmark(tmp_parquet_root, index_code="NIFTY_500", start=days[0], end=days[-1])
        assert df.empty

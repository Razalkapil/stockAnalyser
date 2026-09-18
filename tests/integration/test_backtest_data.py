"""backtest.data reads adjusted bars and the benchmark through store.duck."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pyarrow as pa
import pytest

from integration.lake import (
    INDEX_SORT,
    adjusted_table,
    days_from,
    index_table,
    write_bars,
)
from stk.backtest.data import load_benchmark, load_market_data, prepare_bars
from stk.domain.indicators import compute_indicators
from stk.store.parquet.layout import bars_daily_adjusted_partition, indices_daily_partition
from stk.store.parquet.schema import BARS_DAILY_ADJUSTED_SCHEMA, INDICES_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition


class TestLoadMarketData:
    def test_loads_prepared_bars_with_past_only_derived_columns(self, tmp_parquet_root):
        days = days_from(date(2024, 3, 1), 5)
        write_bars(tmp_parquet_root, "AAA", days, [100.0, 101.0, 102.0, 103.0, 104.0])
        data = load_market_data(tmp_parquet_root, exchange="NSE", start=days[0], end=days[-1],
                                adv_lookback_days=20)
        bars = data.bars[data.bars["symbol"] == "AAA"].reset_index(drop=True)
        assert len(bars) == 5
        assert bars["prev_close"].isna().iloc[0]  # nothing precedes the first bar
        assert bars["prev_close"].iloc[1] == pytest.approx(100.0)
        assert bars["adv_turnover"].isna().iloc[0]
        assert bars["adv_turnover"].iloc[1] == pytest.approx(100.0 * 1000)  # day 0 only

    def test_symbols_do_not_contaminate_each_others_derived_columns(self, tmp_parquet_root):
        days = days_from(date(2024, 3, 1), 3)
        both = pa.concat_tables(
            [adjusted_table("AAA", days, [100.0] * 3), adjusted_table("BBB", days, [500.0] * 3)]
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


class TestOneBarPerSymbolPerDay:
    """Regression for a bug found by a real backfill: NSE publishes several series for one
    symbol on one day (WIPRO: EQ plus a 3-share T0 stub). Reading bars_daily_adjusted raw
    handed the engine two bars for one stock."""

    def two_series_lake(self, root, days, series_pairs):
        tables = [adjusted_table("WIPRO", days, closes, series=series, volume=vol)
                  for series, closes, vol in series_pairs]
        upsert_partition(
            bars_daily_adjusted_partition(root, "NSE", days[0].year),
            pa.concat_tables(tables),
            schema=BARS_DAILY_ADJUSTED_SCHEMA,
            replace_dates=set(days),
        )

    def load(self, root, days, **kw):
        return load_market_data(root, exchange="NSE", start=days[0], end=days[-1],
                                adv_lookback_days=20, **kw)

    def test_the_eq_row_wins_and_the_t0_stub_is_dropped(self, tmp_parquet_root):
        days = days_from(date(2025, 7, 7), 3)
        self.two_series_lake(tmp_parquet_root, days, [
            ("EQ", [269.65] * 3, 5_519_016), ("T0", [269.00] * 3, 3)])
        bars = self.load(tmp_parquet_root, days).bars
        assert len(bars) == 3 and set(bars["series"]) == {"EQ"}
        assert (bars["volume"] == 5_519_016).all()  # never the 3-share stub

    def test_precedence_eq_over_be_over_bz(self, tmp_parquet_root):
        days = days_from(date(2025, 7, 7), 2)
        self.two_series_lake(tmp_parquet_root, days, [
            ("BZ", [30.0] * 2, 100), ("BE", [20.0] * 2, 200), ("EQ", [10.0] * 2, 300)])
        assert set(self.load(tmp_parquet_root, days).bars["series"]) == {"EQ"}

    def test_a_trade_for_trade_name_with_no_eq_row_is_kept(self, tmp_parquet_root):
        days = days_from(date(2025, 7, 7), 2)
        self.two_series_lake(tmp_parquet_root, days, [("BE", [20.0] * 2, 200)])
        assert set(self.load(tmp_parquet_root, days).bars["series"]) == {"BE"}

    @pytest.mark.parametrize("series", ["SM", "ST", "T0", "P1", "N3", "GS", "MF"])
    def test_non_instrument_series_alone_never_enter_the_panel(self, tmp_parquet_root, series):
        days = days_from(date(2025, 7, 7), 2)
        self.two_series_lake(tmp_parquet_root, days, [(series, [50.0] * 2, 1000)])
        with pytest.raises(ValueError, match="no adjusted bars"):
            self.load(tmp_parquet_root, days)

    def test_the_series_filter_is_configurable(self, tmp_parquet_root):
        days = days_from(date(2025, 7, 7), 2)
        self.two_series_lake(tmp_parquet_root, days, [("SM", [50.0] * 2, 1000)])
        bars = self.load(tmp_parquet_root, days, tradeable_series=("SM",)).bars
        assert set(bars["series"]) == {"SM"}

    def test_duplicates_that_slip_through_fail_loudly_instead_of_corrupting_windows(self):
        dup = pd.DataFrame({
            "date": pd.to_datetime(["2025-07-07", "2025-07-07"]), "symbol": ["A", "A"],
            "close": [1.0, 2.0], "turnover": [1.0, 2.0],
        })
        with pytest.raises(ValueError, match="one bar per symbol per day"):
            prepare_bars(dup, 20)


class TestRawCloseIsRecoverable:
    """Regression: the panel query once omitted cumulative_price_factor, so close_raw silently
    equalled the ADJUSTED close and every minimum-rupee-price filter used the wrong number."""

    def test_close_raw_undoes_the_adjustment(self, tmp_parquet_root):
        days = days_from(date(2025, 7, 7), 3)
        upsert_partition(
            bars_daily_adjusted_partition(tmp_parquet_root, "NSE", 2025),
            adjusted_table("SPLIT", days, [50.0] * 3, factor=0.5),  # a later 1:1 bonus halved it
            schema=BARS_DAILY_ADJUSTED_SCHEMA,
            replace_dates=set(days),
        )
        data = load_market_data(tmp_parquet_root, exchange="NSE", start=days[0], end=days[-1],
                                adv_lookback_days=20)
        assert "cumulative_price_factor" in data.bars.columns
        assert compute_indicators(data.bars)["close_raw"].tolist() == [100.0] * 3


class TestLoadBenchmark:
    def test_keys_on_canonical_code_across_a_rename(self, tmp_parquet_root):
        """NSE renamed the index between 2015 and 2016; a name filter would return a fragment."""
        a, b = days_from(date(2015, 1, 1), 3), days_from(date(2016, 1, 1), 3)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2015),
                         index_table("NIFTY_500", "CNX 500", a, [1.0, 2.0, 3.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(a), sort_keys=INDEX_SORT)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2016),
                         index_table("NIFTY_500", "Nifty 500", b, [4.0, 5.0, 6.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(b), sort_keys=INDEX_SORT)
        df = load_benchmark(tmp_parquet_root, index_code="NIFTY_500", start=a[0], end=b[-1])
        assert df["close"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    def test_other_indices_are_excluded(self, tmp_parquet_root):
        days = days_from(date(2024, 1, 1), 2)
        upsert_partition(indices_daily_partition(tmp_parquet_root, 2024),
                         index_table("NIFTY_50", "Nifty 50", days, [9.0, 9.0]),
                         schema=INDICES_DAILY_SCHEMA, replace_dates=set(days), sort_keys=INDEX_SORT)
        df = load_benchmark(tmp_parquet_root, index_code="NIFTY_500", start=days[0], end=days[-1])
        assert df.empty

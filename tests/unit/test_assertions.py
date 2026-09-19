"""Tests for post-ingest sanity assertions.

Includes a regression test for a real bug caught by a live ingest run:
thin government-securities rows (gilts/SGBs) in sec_bhavdata_full have
turnover/volume/vwap so small that a pure-ratio plausibility check
fails on rounding noise, not a real units bug.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stk.core.errors import IngestAssertionError
from stk.ingest.assertions import assert_bars_match_requested_date, assert_bars_sane
from stk.providers.base import CanonicalBar


def _bar(**overrides) -> CanonicalBar:
    defaults = dict(
        date=date(2026, 9, 17),
        exchange="NSE",
        symbol="TCS",
        series="EQ",
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("102"),
        vwap=Decimal("101"),
        volume=1000,
        turnover=Decimal("101000"),
        source="nse_sec_bhavdata",
    )
    defaults.update(overrides)
    return CanonicalBar(**defaults)


class TestAssertBarsSane:
    def test_passes_on_sane_bars(self):
        assert_bars_sane([_bar()], context="test")  # should not raise

    def test_empty_batch_rejected(self):
        with pytest.raises(IngestAssertionError, match="zero bars"):
            assert_bars_sane([], context="test")

    def test_duplicate_key_rejected(self):
        bar = _bar()
        with pytest.raises(IngestAssertionError, match="duplicate"):
            assert_bars_sane([bar, bar], context="test")

    def test_high_below_close_rejected(self):
        bad = _bar(high=Decimal("50"), close=Decimal("102"))
        with pytest.raises(IngestAssertionError, match="high"):
            assert_bars_sane([bad], context="test")

    def test_zero_close_rejected(self):
        bad = _bar(close=Decimal("0"))
        with pytest.raises(IngestAssertionError, match="close"):
            assert_bars_sane([bad], context="test")

    def test_negative_volume_rejected(self):
        bad = _bar(volume=-1)
        with pytest.raises(IngestAssertionError, match="volume"):
            assert_bars_sane([bad], context="test")

    def test_delivery_exceeding_volume_rejected(self):
        bad = _bar(volume=1000, delivery_qty=2000)
        with pytest.raises(IngestAssertionError, match="delivery_qty"):
            assert_bars_sane([bad], context="test")

    def test_turnover_wildly_off_from_volume_times_vwap_rejected(self):
        # volume*vwap = 1000*101 = 101,000; turnover claims 10,100,000 (100x) --
        # a real units bug (e.g. a missed lakhs conversion) should still be caught.
        bad = _bar(volume=1000, vwap=Decimal("101"), turnover=Decimal("10100000"))
        with pytest.raises(IngestAssertionError, match="turnover"):
            assert_bars_sane([bad], context="test")

    def test_tiny_gilt_style_row_with_zero_turnover_is_not_rejected(self):
        """Regression test: a real live-ingest failure. Thin government
        securities (gilts/SGBs) can have turnover=0 with a tiny nonzero
        volume*vwap -- this must NOT trip the units-mistake check, which
        exists to catch orders-of-magnitude errors, not rounding noise
        at near-zero absolute values."""
        gilt_bar = _bar(
            symbol="610GS2031",
            series="GS",
            volume=1,
            vwap=Decimal("99.99"),
            turnover=Decimal("0"),
        )
        assert_bars_sane([gilt_bar], context="test")  # should not raise

    def test_turnover_check_still_fires_above_the_floor(self):
        """The floor must not swallow real bugs once absolute values are
        large enough to be meaningful."""
        bad = _bar(volume=1000, vwap=Decimal("101"), turnover=Decimal("1010000000"))
        with pytest.raises(IngestAssertionError, match="turnover"):
            assert_bars_sane([bad], context="test")


class TestAssertBarsMatchRequestedDate:
    """Regression tests for a real bug found via live backfill testing:
    NSE's own sec_bhavdata_full archive was observed serving a file
    whose CONTENT is dated differently from what its URL promises
    (e.g. the file requested for 2019-09-30 actually contained rows
    dated 27-Jun-2019). Silently trusting the requested date would
    write that content under the wrong partition key.
    """

    def test_matching_dates_pass(self):
        bars = [_bar(date=date(2026, 9, 17))]
        assert_bars_match_requested_date(bars, date(2026, 9, 17), context="test")  # no raise

    def test_mismatched_date_raises(self):
        bars = [_bar(date=date(2019, 6, 27))]
        with pytest.raises(IngestAssertionError, match="2019-09-30"):
            assert_bars_match_requested_date(bars, date(2019, 9, 30), context="test")

    def test_mixed_matching_and_mismatched_bars_raises(self):
        """Even if only some rows are wrong, the whole file must be rejected."""
        bars = [_bar(date=date(2026, 9, 17)), _bar(symbol="INFY", date=date(2019, 6, 27))]
        with pytest.raises(IngestAssertionError):
            assert_bars_match_requested_date(bars, date(2026, 9, 17), context="test")


class TestAuxiliarySeriesOhlc:
    """Regression for a real failure found by a live backfill (2025-07 .. 2025-11).

    NSE's sec_bhavdata_full carries auxiliary series rows alongside the EQ row, e.g.
    WIPRO on 2025-07-08:
        EQ  267.80 270.30 267.35 ... close 269.65     <- the real bar
        T0  269.00 269.00 269.00 ... close 269.65     <- 3 shares; open=high=low=269.00
                                                         but CLOSE carries the EQ close
    The T0 row is internally inconsistent (high < close). Aborting the whole day over it
    blocked ~1/3 of real trading days -- and a check that cries wolf that often hides the
    real alarms. The check stays FATAL for equity series and becomes a counted anomaly
    for the rest.
    """

    def t0_row(self, **kw):
        fields = dict(series="T0", open=Decimal("269.00"), high=Decimal("269.00"),
                      low=Decimal("269.00"), close=Decimal("269.65"), vwap=None, volume=3,
                      turnover=Decimal("807"))
        fields.update(kw)
        return _bar(**fields)

    def test_an_inconsistent_auxiliary_series_row_does_not_abort_the_day(self):
        anomalies = assert_bars_sane([_bar(symbol="WIPRO"), self.t0_row(symbol="WIPRO")],
                                     context="NSE 2025-07-08")
        assert len(anomalies) == 1
        assert "WIPRO" in anomalies[0] and "T0" in anomalies[0]

    def test_the_same_inconsistency_on_an_EQ_row_is_still_fatal(self):
        bad = _bar(series="EQ", high=Decimal("50"), close=Decimal("102"))
        with pytest.raises(IngestAssertionError, match="high"):
            assert_bars_sane([bad], context="test")

    @pytest.mark.parametrize("series", ["EQ", "BE", "BZ", "SM", "ST"])
    def test_every_equity_series_stays_strict(self, series):
        bad = _bar(series=series, high=Decimal("50"), close=Decimal("102"))
        with pytest.raises(IngestAssertionError):
            assert_bars_sane([bad], context="test")

    def test_clean_batches_report_no_anomalies(self):
        assert assert_bars_sane([_bar()], context="test") == []

    def test_other_invariants_still_apply_to_auxiliary_series(self):
        """Only the OHLC-ordering check is relaxed -- a non-positive close is wrong anywhere."""
        with pytest.raises(IngestAssertionError, match="close<=0"):
            assert_bars_sane([self.t0_row(close=Decimal("0"))], context="test")


class TestIsolatedDeliveryInconsistency:
    """Regression from a real backfill: NSE's 2024-02-19 file has WTICAB with delivery_qty
    2,566,000 > volume 2,561,000 (0.2% over). One quirky row aborted the whole trading day for
    all ~2,700 symbols. A UNITS bug would break MANY rows at once; a handful is a source quirk."""

    def bars(self, n_total: int, n_bad: int):
        bars = [_bar(symbol=f"S{i}", volume=1000, delivery_qty=500) for i in range(n_total)]
        for i in range(n_bad):
            bars[i] = _bar(symbol=f"BAD{i}", volume=1000, delivery_qty=1005)
        return bars

    def test_a_single_bad_row_in_a_full_day_is_an_anomaly_not_an_abort(self):
        anomalies = assert_bars_sane(self.bars(2700, 1), context="NSE 2024-02-19")
        assert len(anomalies) == 1 and "BAD0" in anomalies[0] and "delivery_qty" in anomalies[0]

    def test_a_handful_is_still_tolerated(self):
        assert len(assert_bars_sane(self.bars(2700, 3), context="t")) == 3

    def test_many_bad_rows_look_systemic_and_abort(self):
        """e.g. a units/column-shift bug: 5% of rows violate it."""
        with pytest.raises(IngestAssertionError, match="delivery_qty"):
            assert_bars_sane(self.bars(2000, 100), context="t")

    def test_the_threshold_is_relative_so_a_tiny_batch_cannot_hide_a_systemic_bug(self):
        with pytest.raises(IngestAssertionError, match="delivery_qty"):
            assert_bars_sane(self.bars(10, 5), context="t")

    def test_the_error_names_examples_and_the_rate(self):
        with pytest.raises(IngestAssertionError) as e:
            assert_bars_sane(self.bars(200, 20), context="NSE 2024-01-01")
        assert "20 of 200" in str(e.value) and "BAD0" in str(e.value)

    def test_consistent_delivery_is_untouched(self):
        assert assert_bars_sane(self.bars(50, 0), context="t") == []

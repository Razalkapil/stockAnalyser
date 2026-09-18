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
from stk.ingest.assertions import assert_bars_sane
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

"""Unit tests for the NSE index-file parser.

Two conversions happen only here and must be pinned: "Rs. Cr." ->
rupees, and the printed index name -> a stable canonical code. The
second exists because NSE renamed its own benchmark twice inside the
range we backfill, which would otherwise split the benchmark series
into three disconnected fragments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stk.core.errors import DataNotPublished, ParseError
from stk.ingest.normalise import canonical_index_code, parse_ind_close_all
from stk.providers.nse.indices import NseIndicesProvider

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nse" / "ind_close_all_17092026.csv"
HEADER = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield"
)


class TestParseRealFixture:
    def test_parses_the_benchmark_row(self):
        bars = parse_ind_close_all(FIXTURE.read_text())
        nifty = next(b for b in bars if b.index_name == "Nifty 50")

        assert nifty.date == date(2026, 9, 17)
        assert nifty.index_code == "NIFTY_50"
        assert nifty.close == Decimal("23270.6")
        assert nifty.open == Decimal("23195.25")

    def test_turnover_is_converted_from_crore_to_rupees(self):
        """18775.3 crore = 1,87,753,000,000 rupees. The word "crore"
        must never survive into the canonical layer."""
        bars = parse_ind_close_all(FIXTURE.read_text())
        nifty = next(b for b in bars if b.index_name == "Nifty 50")
        assert nifty.turnover == Decimal("18775.3") * Decimal(10_000_000)

    def test_derived_series_with_null_ohlc_is_kept(self):
        """NSE's file carries rows like "Nifty50 Dividend Points" that
        have a real close and '-' for OHLC. Those are valid rows."""
        bars = parse_ind_close_all(FIXTURE.read_text())
        dividend_points = [b for b in bars if "Dividend Points" in b.index_name]
        assert dividend_points
        bar = dividend_points[0]
        assert bar.open is None
        assert bar.close > 0
        assert bar.index_code is None, "no canonical code claimed for a series we do not track"


class TestNullHandling:
    def test_dash_becomes_none_never_zero(self):
        row = f"{HEADER}\nTest Index,17-09-2026,-,-,-,100.5,-,-,-,-,-,-,-"
        bar = parse_ind_close_all(row)[0]

        assert bar.open is None
        assert bar.volume is None
        assert bar.turnover is None
        assert bar.pe is None
        assert bar.close == Decimal("100.5")

    def test_a_row_with_no_close_is_skipped_not_stored_with_a_null(self):
        """A row with no closing value is not a price bar at all."""
        row = f"{HEADER}\nTest Index,17-09-2026,1,2,0.5,-,-,-,-,-,-,-,-"
        assert parse_ind_close_all(row) == []


class TestCanonicalIndexCode:
    @pytest.mark.parametrize(
        "printed",
        ["S&P CNX Nifty", "CNX Nifty", "Nifty 50", "nifty 50", "  Nifty 50  "],
    )
    def test_every_historical_name_of_the_benchmark_maps_to_one_code(self, printed):
        """The finding this mapping exists for: NSE's benchmark is
        printed as three different names across 2012-2026, and keying a
        series on the printed name breaks it into fragments."""
        assert canonical_index_code(printed) == "NIFTY_50"

    def test_an_untracked_index_gets_no_code_rather_than_a_guess(self):
        assert canonical_index_code("Nifty Alpha Quality Value Low-Volatility 30") is None


class TestMalformedInput:
    def test_missing_header_column_raises(self):
        with pytest.raises(ParseError, match="missing 'Index Name'"):
            parse_ind_close_all("Some,Other,Header\na,b,c")

    def test_unparseable_date_raises(self):
        row = f"{HEADER}\nTest Index,2026-09-17,1,2,0.5,1.5,-,-,-,-,-,-,-"
        with pytest.raises(ParseError, match="could not parse index date"):
            parse_ind_close_all(row)


@pytest.mark.live
class TestLiveEndpoint:
    """Run deliberately: `pytest -m live`."""

    def test_recent_trading_day_is_reachable_in_the_documented_shape(self):
        artifact = NseIndicesProvider().fetch_indices(date(2026, 9, 17))
        bars = parse_ind_close_all(artifact.content.decode("utf-8-sig"))
        assert any(b.index_code == "NIFTY_50" for b in bars)

    def test_a_non_trading_day_404s_honestly(self):
        """Unlike BSE, NSE's index archive gives a real 404 rather than
        a 200 with an SPA shell."""
        with pytest.raises(DataNotPublished):
            NseIndicesProvider().fetch_indices(date(2026, 1, 26))  # Republic Day

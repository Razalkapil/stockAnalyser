"""Tests for parsing real NSE/BSE fixture files into canonical bars.

Fixtures in tests/fixtures/ are trimmed real responses (not synthetic),
so these tests double as a regression check against actual NSE/BSE
output formats.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from stk.ingest.normalise import parse_legacy_bhavcopy, parse_sec_bhavdata_full, parse_udiff

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestParseSecBhavdataFull:
    def test_parses_real_fixture_without_error(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        assert len(bars) == 50

    def test_leading_spaces_in_header_and_values_handled(self):
        """The real NSE file has a leading space on every header/value
        after the first column -- skipinitialspace must cope with this."""
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        first = bars[0]
        assert first.series == "EQ"  # not " EQ" with a leading space

    def test_turnover_converted_from_lacs_to_rupees(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        first = bars[0]
        assert first.symbol == "20MICRONS"
        # TURNOVER_LACS=117.52 -> Rs 11,752,000
        assert first.turnover == Decimal("117.52") * Decimal(100_000)

    def test_dates_parsed_correctly(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        assert bars[0].date == date(2026, 9, 17)

    def test_dash_delivery_fields_become_none_not_zero(self):
        """This is the critical rule: '-' means unreported, not zero."""
        text = (FIXTURES / "nse" / "sec_bhavdata_full_with_dashes.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))

        be_series_bars = [b for b in bars if b.series == "BE"]
        assert len(be_series_bars) == 3
        for bar in be_series_bars:
            assert bar.delivery_qty is None
            assert bar.delivery_pct is None

    def test_reported_delivery_is_a_real_number_not_none(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_with_dashes.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        eq_bar = next(b for b in bars if b.series == "EQ")
        assert eq_bar.delivery_qty == 25090
        assert eq_bar.delivery_pct == Decimal("44.10")

    def test_exchange_is_always_nse(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        assert all(b.exchange == "NSE" for b in bars)

    def test_source_tag_set(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        bars = list(parse_sec_bhavdata_full(text))
        assert all(b.source == "nse_sec_bhavdata" for b in bars)


class TestParseUdiff:
    def test_parses_real_bse_fixture_without_error(self):
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        bars = list(parse_udiff(text, exchange="BSE", source="bse_udiff"))
        assert len(bars) == 50

    def test_isin_present(self):
        """UDiFF carries ISIN, unlike sec_bhavdata_full -- this is why
        it is the ISIN-bearing companion source in the merge step."""
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        bars = list(parse_udiff(text, exchange="BSE", source="bse_udiff"))
        assert any(b.isin and b.isin.startswith("INE") for b in bars)

    def test_iso_dates_parsed(self):
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        bars = list(parse_udiff(text, exchange="BSE", source="bse_udiff"))
        assert bars[0].date == date(2026, 9, 17)

    def test_exchange_tag_set_correctly(self):
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        bars = list(parse_udiff(text, exchange="BSE", source="bse_udiff"))
        assert all(b.exchange == "BSE" for b in bars)


class TestParseLegacyBhavcopy:
    def test_parses_real_2010_fixture_without_error(self):
        text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        bars = list(parse_legacy_bhavcopy(text))
        assert len(bars) == 50

    def test_non_zero_padded_day_in_timestamp_parsed_correctly(self):
        """The real 2010 file uses '4-JAN-2010', not '04-JAN-2010'."""
        text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        bars = list(parse_legacy_bhavcopy(text))
        assert bars[0].date == date(2010, 1, 4)

    def test_no_delivery_data_in_legacy_format(self):
        """This format predates delivery reporting -- delivery fields
        must be None, not silently 0."""
        text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        bars = list(parse_legacy_bhavcopy(text))
        assert all(b.delivery_qty is None for b in bars)
        assert all(b.delivery_pct is None for b in bars)

    def test_no_isin_in_legacy_format(self):
        text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        bars = list(parse_legacy_bhavcopy(text))
        assert all(b.isin is None for b in bars)

    def test_known_symbol_and_values(self):
        text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        bars = list(parse_legacy_bhavcopy(text))
        first = bars[0]
        assert first.symbol == "20MICRONS"
        assert first.open == Decimal("46")
        assert first.close == Decimal("47.55")
        assert first.volume == 36282

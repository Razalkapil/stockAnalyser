"""Tests for NseSecurityMasterProvider, mocked via respx."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import respx

from stk.providers.base import MasterRecord, PriceBand
from stk.providers.nse.master import NseSecurityMasterProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SEC_LIST_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"


class TestFetchMaster:
    @respx.mock
    def test_parses_records(self):
        csv_text = (FIXTURES / "nse" / "equity_l.csv").read_text()
        respx.get(EQUITY_L_URL).mock(
            return_value=httpx.Response(200, text=csv_text, headers={"content-type": "text/csv"})
        )

        records = NseSecurityMasterProvider().fetch_master()

        assert len(records) == 50
        first = records[0]
        assert isinstance(first, MasterRecord)
        assert first.symbol == "20MICRONS"
        assert first.isin == "INE144J01027"
        assert first.exchange == "NSE"
        assert first.series == "EQ"
        assert first.face_value == Decimal("5")
        assert first.lot_size == 1
        assert first.listing_date == date(2008, 10, 6)
        assert first.company_name == "20 Microns Limited"


class TestFetchPriceBands:
    @respx.mock
    def test_parses_bands(self):
        csv_text = (FIXTURES / "nse" / "sec_list_trimmed.csv").read_text()
        respx.get(SEC_LIST_URL).mock(
            return_value=httpx.Response(200, text=csv_text, headers={"content-type": "text/csv"})
        )

        bands = NseSecurityMasterProvider().fetch_price_bands()

        assert len(bands) > 0
        first = bands[0]
        assert isinstance(first, PriceBand)
        assert first.symbol == "21STCENMGM"
        assert first.series == "EQ"
        assert first.band_pct == 2

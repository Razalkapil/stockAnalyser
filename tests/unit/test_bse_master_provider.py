"""Tests for BseSecurityMasterProvider, mocked via respx."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import respx

from stk.providers.base import MasterRecord
from stk.providers.bse.master import BseSecurityMasterProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)


class TestFetchMaster:
    @respx.mock
    def test_parses_records(self):
        payload = json.loads((FIXTURES / "bse" / "scrip_data_trimmed.json").read_text())
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        records = BseSecurityMasterProvider().fetch_master()

        assert len(records) == len(payload)
        first = records[0]
        assert isinstance(first, MasterRecord)
        assert first.symbol == "ABB"
        assert first.isin == "INE117A01022"
        assert first.exchange == "BSE"
        assert first.series == "A"
        assert first.exchange_token == "500002"
        assert first.face_value == Decimal("2.00")
        assert first.company_name == "ABB India Limited"

    @respx.mock
    def test_blank_isin_or_symbol_skipped(self):
        payload = [
            {
                "SCRIP_CD": "999999",
                "Scrip_Name": "No ISIN Co",
                "GROUP": "X",
                "FACE_VALUE": "10.00",
                "ISIN_NUMBER": "",
                "scrip_id": "NOISIN",
                "Issuer_Name": "No ISIN Co",
            },
            {
                "SCRIP_CD": "999998",
                "Scrip_Name": "No Symbol Co",
                "GROUP": "X",
                "FACE_VALUE": "10.00",
                "ISIN_NUMBER": "INE999Z99999",
                "scrip_id": "",
                "Issuer_Name": "No Symbol Co",
            },
        ]
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        records = BseSecurityMasterProvider().fetch_master()

        assert records == []

"""Tests for NseCorporateActionsProvider, mocked via respx."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import respx

from stk.providers.base import RawCorporateAction
from stk.providers.nse.corpactions import NseCorporateActionsProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.nseindia.com/api/corporates-corporateActions"


class TestFetchActions:
    @respx.mock
    def test_parses_actions_subject_unparsed(self):
        payload = json.loads((FIXTURES / "nse" / "corporate_actions_trimmed.json").read_text())
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        actions = NseCorporateActionsProvider().fetch_actions()

        assert len(actions) == len(payload)
        first = actions[0]
        assert isinstance(first, RawCorporateAction)
        assert first.symbol == "MCX"
        assert first.exchange == "NSE"
        assert first.isin == "INE745G01035"
        assert first.ex_date == date(2026, 1, 2)
        assert "Face Value Split" in first.subject_raw  # UNPARSED -- verbatim text preserved
        assert first.source == "nse_corp_actions"
        assert first.source_hash  # non-empty

    @respx.mock
    def test_since_adds_date_range_params(self):
        route = respx.get(URL).mock(return_value=httpx.Response(200, json=[]))

        NseCorporateActionsProvider().fetch_actions(date(2026, 1, 1))

        request = route.calls.last.request
        assert "from_date=01-01-2026" in str(request.url)
        assert "to_date=" in str(request.url)

    @respx.mock
    def test_blank_symbol_or_subject_skipped(self):
        payload = [
            {"symbol": "", "isin": "INE000A00000", "exDate": "01-Jan-2026", "subject": "Bonus 1:1"},
            {"symbol": "REALCO", "isin": "INE000A00001", "exDate": "01-Jan-2026", "subject": ""},
        ]
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        actions = NseCorporateActionsProvider().fetch_actions()

        assert actions == []

    @respx.mock
    def test_same_content_produces_same_source_hash(self):
        row = {
            "symbol": "TESTCO", "isin": "INE000A00000", "exDate": "01-Jan-2026",
            "recDate": "01-Jan-2026", "subject": "Bonus 1:1", "caBroadcastDate": None,
        }
        respx.get(URL).mock(return_value=httpx.Response(200, json=[row, dict(row)]))

        actions = NseCorporateActionsProvider().fetch_actions()

        assert actions[0].source_hash == actions[1].source_hash

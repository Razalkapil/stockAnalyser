"""Tests for NseFundamentalsProvider, mocked via respx."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import NotSupportedError
from stk.providers.base import FilingRef, FundamentalsSnapshotIn, Period, SecurityRef
from stk.providers.nse.fundamentals import NseFundamentalsProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.nseindia.com/api/corporates-financial-results"


class TestIsApproximate:
    def test_is_not_approximate(self):
        assert NseFundamentalsProvider().is_approximate is False


class TestFetchFilingsIndex:
    @respx.mock
    def test_parses_filing_refs(self):
        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        refs = NseFundamentalsProvider().fetch_filings_index(date(2020, 1, 1), Period.QUARTERLY)

        assert len(refs) == len(payload)
        first = refs[0]
        assert isinstance(first, FilingRef)
        assert first.security_isin == "INE002A01018"
        assert first.period_type == Period.QUARTERLY
        assert first.period_end == date(2024, 12, 31)
        assert first.filing_system == "financial_results"
        assert first.broadcast_at is not None

    @respx.mock
    def test_since_filters_out_older_filings(self):
        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        refs = NseFundamentalsProvider().fetch_filings_index(date(2099, 1, 1), Period.QUARTERLY)

        assert refs == []

    def test_half_yearly_not_supported(self):
        with pytest.raises(NotSupportedError):
            NseFundamentalsProvider().fetch_filings_index(date(2020, 1, 1), Period.HALF_YEARLY)


class TestFetchStatements:
    @respx.mock
    def test_parses_snapshots_as_metadata(self):
        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        snapshots = NseFundamentalsProvider().fetch_statements(
            SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE"),
            Period.QUARTERLY,
        )

        assert len(snapshots) == len(payload)
        first = snapshots[0]
        assert isinstance(first, FundamentalsSnapshotIn)
        assert first.security_isin == "INE002A01018"
        assert first.provider == "nse_filings"
        assert first.statement_type == "meta"  # metadata only -- see module docstring
        assert first.is_approximate is False
        assert first.data["seqNumber"]  # raw filing metadata preserved
        assert first.source_url is not None

    @respx.mock
    def test_limit_caps_results(self):
        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        snapshots = NseFundamentalsProvider().fetch_statements(
            SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE"),
            Period.QUARTERLY,
            limit=2,
        )

        assert len(snapshots) == 2

    def test_half_yearly_not_supported(self):
        with pytest.raises(NotSupportedError):
            NseFundamentalsProvider().fetch_statements(
                SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE"),
                Period.HALF_YEARLY,
            )

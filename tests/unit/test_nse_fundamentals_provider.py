"""Tests for NseFundamentalsProvider, mocked via respx."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import NotSupportedError, ProviderUnavailable
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


# --- the newer "Integrated Filing" system (live-verified 2026-09-19) ------------------------------

INTEGRATED_URL = "https://www.nseindia.com/api/integrated-filing-results"
REL = SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE")


def integrated_payload() -> dict:
    return json.loads((FIXTURES / "nse" / "integrated_filing_listing_trimmed.json").read_text())


class TestIntegratedFilings:
    @respx.mock
    def test_asks_for_the_symbol_with_enough_rows_and_the_right_type(self):
        route = respx.get(INTEGRATED_URL).mock(
            return_value=httpx.Response(200, json=integrated_payload()))
        NseFundamentalsProvider().fetch_integrated_statements(REL)
        q = dict(route.calls.last.request.url.params)
        assert q["symbol"] == "RELIANCE" and q["type"] == "Integrated Filing- Financials"
        assert q["index"] == "equities" and q["period_ended"] == "all" and int(q["size"]) >= 100

    @respx.mock
    def test_maps_rows_using_the_callers_isin_and_marks_the_filing_system(self):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=integrated_payload()))
        snaps = NseFundamentalsProvider().fetch_integrated_statements(REL)
        assert len(snaps) == 6
        assert {s.security_isin for s in snaps} == {"INE002A01018"}  # the row carries no ISIN
        assert {s.filing_system for s in snaps} == {"integrated_filing"}
        assert {s.statement_type for s in snaps} == {"meta"}
        assert all(isinstance(s, FundamentalsSnapshotIn) for s in snaps)

    @respx.mock
    def test_a_march_filing_is_the_full_year_and_the_others_are_quarters(self):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=integrated_payload()))
        by = {(s.period_end, s.consolidated): s for s in
              NseFundamentalsProvider().fetch_integrated_statements(REL)
              if s.security_isin and s.data["symbol"] == "RELIANCE"}
        assert by[(date(2026, 3, 31), True)].period_type == Period.ANNUAL
        assert by[(date(2026, 6, 30), True)].period_type == Period.QUARTERLY
        assert by[(date(2026, 6, 30), False)].consolidated is False

    @respx.mock
    def test_broadcast_falls_back_for_revisions_whose_broadcast_is_null(self):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=integrated_payload()))
        snaps = NseFundamentalsProvider().fetch_integrated_statements(REL)
        revision = next(s for s in snaps if s.data["symbol"] == "INTERARCH")
        assert revision.is_restated is True and revision.data["broadcast_Date"] is None
        assert revision.broadcast_at == datetime(2026, 9, 19, 15, 17, 4)  # revised_Date
        original = next(s for s in snaps if s.data["symbol"] == "RELIANCE")
        assert original.is_restated is False and original.broadcast_at == datetime(
            2026, 7, 17, 19, 50, 3)

    @respx.mock
    def test_each_row_is_a_distinct_snapshot_and_never_collides_with_the_legacy_hashes(self):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=integrated_payload()))
        snaps = NseFundamentalsProvider().fetch_integrated_statements(REL)
        assert len({s.source_hash for s in snaps}) == len(snaps)
        import hashlib  # noqa: PLC0415

        assert hashlib.sha256(b"175608").hexdigest() not in {s.source_hash for s in snaps}

    @respx.mock
    def test_newest_first_and_limited(self):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=integrated_payload()))
        snaps = NseFundamentalsProvider().fetch_integrated_statements(REL, limit=2)
        assert len(snaps) == 2
        assert snaps[0].broadcast_at >= snaps[1].broadcast_at

    @respx.mock
    def test_a_truncated_history_is_refused_not_stored(self):
        payload = integrated_payload()
        payload["totalCount"] = 500  # more exist than were returned
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(ProviderUnavailable, match="truncated"):
            NseFundamentalsProvider().fetch_integrated_statements(REL)

    @respx.mock
    @pytest.mark.parametrize("body", [[], {"data": "x"}, {"nodata": []}])
    def test_an_unexpected_shape_is_an_error_not_an_empty_history(self, body):
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(ProviderUnavailable):
            NseFundamentalsProvider().fetch_integrated_statements(REL)

    @respx.mock
    def test_rows_missing_a_period_or_id_are_skipped(self):
        payload = integrated_payload()
        payload["data"][0]["qe_Date"] = ""
        payload["data"][1]["seq_Id"] = None
        respx.get(INTEGRATED_URL).mock(return_value=httpx.Response(200, json=payload))
        assert len(NseFundamentalsProvider().fetch_integrated_statements(REL)) == 4

    def test_a_provider_without_the_capability_says_so(self):
        from stk.providers.base import FundamentalsProvider  # noqa: PLC0415

        class Legacy(FundamentalsProvider):
            is_approximate = False  # type: ignore[assignment]

            def fetch_filings_index(self, since, period): return []
            def fetch_statements(self, security, period_type, limit=12): return []

        with pytest.raises(NotSupportedError):
            Legacy().fetch_integrated_statements(REL)

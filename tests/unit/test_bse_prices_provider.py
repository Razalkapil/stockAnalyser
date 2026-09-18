"""Tests for BseUdiffProvider, mocked via respx (no live network in the
default test run -- see the `live` marker tests for real endpoint checks).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import ContentValidationError, DataNotPublished, NotSupportedError
from stk.providers.bse.prices import BSE_UDIFF_AVAILABLE_FROM, BseUdiffProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20260917_F_0000.CSV"

# The real BSE SPA shell is ~14KB; a short stand-in with the right
# content-type is enough to exercise the html-shell -> DataNotPublished path.
_SPA_SHELL_HTML = "<!DOCTYPE html><html><head><title>BSE</title></head><body></body></html>"


def _csv_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "application/octet-stream"})


class TestFetchEod:
    @respx.mock
    def test_fetches_and_returns_artifact(self):
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        respx.get(URL).mock(return_value=_csv_response(text))

        provider = BseUdiffProvider()
        artifact = provider.fetch_eod(date(2026, 9, 17), "BSE")

        assert artifact.source == "bse_udiff"
        assert artifact.business_date == date(2026, 9, 17)
        assert b"TradDt" in artifact.content

    @respx.mock
    def test_spa_shell_raises_data_not_published(self):
        """The confirmed-live BSE trap: a weekend, holiday, or invalid date
        returns HTTP 200 with content-type text/html and the same SPA
        shell every time -- treated as DataNotPublished, not a hard failure."""
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text=_SPA_SHELL_HTML, headers={"content-type": "text/html"}
            )
        )

        provider = BseUdiffProvider()
        with pytest.raises(DataNotPublished):
            provider.fetch_eod(date(2026, 9, 17), "BSE")

    @respx.mock
    def test_genuinely_corrupt_csv_raises_content_validation_error(self):
        """Not text/html, but also doesn't look like the expected CSV --
        must still be caught, distinguishing real corruption from the
        SPA-shell "not published" case."""
        respx.get(URL).mock(return_value=_csv_response("garbage,not,udiff\n1,2,3\n"))

        provider = BseUdiffProvider()
        with pytest.raises(ContentValidationError):
            provider.fetch_eod(date(2026, 9, 17), "BSE")

    def test_non_bse_exchange_rejected(self):
        provider = BseUdiffProvider()
        with pytest.raises(ValueError, match="only supports BSE"):
            provider.fetch_eod(date(2026, 9, 17), "NSE")

    def test_date_before_udiff_start_raises_not_supported(self):
        provider = BseUdiffProvider()
        before = date(2024, 7, 7)
        assert before < BSE_UDIFF_AVAILABLE_FROM
        with pytest.raises(NotSupportedError):
            provider.fetch_eod(before, "BSE")


class TestParseEod:
    @respx.mock
    def test_parses_real_fixture_into_canonical_bars(self):
        text = (FIXTURES / "bse" / "udiff_20260917.CSV").read_text()
        respx.get(URL).mock(return_value=_csv_response(text))

        provider = BseUdiffProvider()
        artifact = provider.fetch_eod(date(2026, 9, 17), "BSE")
        bars = list(provider.parse_eod(artifact))

        assert bars
        assert all(b.exchange == "BSE" for b in bars)
        assert all(b.source == "bse_udiff" for b in bars)
        assert all(b.isin for b in bars)
        first = bars[0]
        assert first.date == date(2026, 9, 17)
        assert first.symbol
        assert first.close > 0


class TestCapabilities:
    def test_capabilities(self):
        provider = BseUdiffProvider()
        caps = provider.capabilities
        assert caps.exchanges == frozenset({"BSE"})
        assert caps.earliest_date == BSE_UDIFF_AVAILABLE_FROM
        assert caps.supports_delivery is False

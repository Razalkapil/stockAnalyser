"""Tests for NseSecBhavdataProvider, mocked via respx (no live network in
the default test run -- see the `live` marker tests for real endpoint checks).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import ContentValidationError, DataNotPublished
from stk.providers.nse.prices import NseSecBhavdataProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_17092026.csv"


def _csv_response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/csv"})


class TestFetchEod:
    @respx.mock
    def test_fetches_and_returns_artifact(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(return_value=_csv_response(text))

        provider = NseSecBhavdataProvider()
        artifact = provider.fetch_eod(date(2026, 9, 17), "NSE")

        assert artifact.source == "nse_sec_bhavdata"
        assert artifact.business_date == date(2026, 9, 17)
        assert b"SYMBOL" in artifact.content

    @respx.mock
    def test_404_raises_data_not_published(self):
        respx.get(URL).mock(return_value=httpx.Response(404))

        provider = NseSecBhavdataProvider()
        with pytest.raises(DataNotPublished):
            provider.fetch_eod(date(2026, 9, 17), "NSE")

    @respx.mock
    def test_html_error_page_raises_content_validation_error(self):
        """Defence-in-depth: even though NSE's archive host has not been
        observed doing the BSE-style 200-with-HTML trick, the guard is
        applied uniformly."""
        html = "<html><body>error</body></html>"
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
        )

        provider = NseSecBhavdataProvider()
        with pytest.raises(ContentValidationError):
            provider.fetch_eod(date(2026, 9, 17), "NSE")

    def test_non_nse_exchange_rejected(self):
        provider = NseSecBhavdataProvider()
        with pytest.raises(ValueError, match="NSE"):
            provider.fetch_eod(date(2026, 9, 17), "BSE")


class TestParseEod:
    @respx.mock
    def test_end_to_end_fetch_then_parse(self):
        text = (FIXTURES / "nse" / "sec_bhavdata_full_17092026.csv").read_text()
        respx.get(URL).mock(return_value=_csv_response(text))

        provider = NseSecBhavdataProvider()
        artifact = provider.fetch_eod(date(2026, 9, 17), "NSE")
        bars = list(provider.parse_eod(artifact))

        assert len(bars) == 50
        assert bars[0].symbol == "20MICRONS"


class TestCapabilities:
    def test_declares_nse_only_with_delivery_support(self):
        caps = NseSecBhavdataProvider().capabilities
        assert caps.exchanges == frozenset({"NSE"})
        assert caps.supports_delivery is True
        assert caps.supports_intraday is False


@pytest.mark.live
class TestLiveEndpoint:
    """Real network smoke test -- excluded from the default run. Run
    explicitly with `pytest -m live` when verifying the endpoint is
    still reachable in this exact shape."""

    def test_fetches_todays_or_recent_real_data(self):
        provider = NseSecBhavdataProvider()
        # Walk back a few days to find a real trading day without
        # depending on a calendar provider in this smoke test.
        for offset in range(1, 6):
            try:
                artifact = provider.fetch_eod(date.today() - timedelta(days=offset), "NSE")
                bars = list(provider.parse_eod(artifact))
                assert len(bars) > 100
                return
            except DataNotPublished:
                continue
        pytest.fail("no real trading day found in the last 5 calendar days")

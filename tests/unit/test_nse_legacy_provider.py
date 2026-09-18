"""Tests for NseLegacyBhavcopyProvider, mocked via respx."""

from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import ContentValidationError, DataNotPublished
from stk.providers.nse.legacy_prices import NseLegacyBhavcopyProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/2010/JAN/cm04JAN2010bhav.csv.zip"


def _zip_bytes(csv_text: str, inner_name: str = "cm04JAN2010bhav.csv") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, csv_text)
    return buf.getvalue()


class TestFetchEod:
    @respx.mock
    def test_fetches_and_returns_artifact(self):
        csv_text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, content=_zip_bytes(csv_text), headers={"content-type": "application/zip"}
            )
        )

        provider = NseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "NSE")
        assert artifact.content.startswith(b"PK")

    @respx.mock
    def test_404_raises_data_not_published(self):
        respx.get(URL).mock(return_value=httpx.Response(404))

        provider = NseLegacyBhavcopyProvider()
        with pytest.raises(DataNotPublished):
            provider.fetch_eod(date(2010, 1, 4), "NSE")

    @respx.mock
    def test_html_error_page_raises_content_validation_error(self):
        html = "<html><body>error</body></html>"
        respx.get(URL).mock(
            return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
        )

        provider = NseLegacyBhavcopyProvider()
        with pytest.raises(ContentValidationError):
            provider.fetch_eod(date(2010, 1, 4), "NSE")

    def test_non_nse_exchange_rejected(self):
        provider = NseLegacyBhavcopyProvider()
        with pytest.raises(ValueError, match="NSE"):
            provider.fetch_eod(date(2010, 1, 4), "BSE")


class TestParseEod:
    @respx.mock
    def test_end_to_end_fetch_then_parse(self):
        csv_text = (FIXTURES / "nse" / "legacy_cm04JAN2010bhav.csv").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, content=_zip_bytes(csv_text), headers={"content-type": "application/zip"}
            )
        )

        provider = NseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "NSE")
        bars = list(provider.parse_eod(artifact))

        assert len(bars) == 50
        assert bars[0].symbol == "20MICRONS"
        assert bars[0].delivery_qty is None


class TestCapabilities:
    def test_declares_2010_earliest_date_no_delivery(self):
        caps = NseLegacyBhavcopyProvider().capabilities
        assert caps.earliest_date == date(2010, 1, 4)
        assert caps.supports_delivery is False


@pytest.mark.live
class TestLiveEndpoint:
    def test_fetches_real_2010_data(self):
        provider = NseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "NSE")
        bars = list(provider.parse_eod(artifact))
        assert len(bars) > 500

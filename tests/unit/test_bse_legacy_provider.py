"""Tests for BseLegacyBhavcopyProvider, mocked via respx.

Mirrors test_nse_legacy_provider.py's structure -- see that file for
why each case matters. BSE-specific: the SPA-shell trap applies to
this zip URL family too (unlike NSE's legacy archive, which 404s
instead), and there is no symbol/ISIN in this format at all, only a
numeric scrip code.
"""

from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx

from stk.core.errors import ContentValidationError, DataNotPublished
from stk.providers.bse.legacy_prices import BseLegacyBhavcopyProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.bseindia.com/download/BhavCopy/Equity/EQ040110_CSV.ZIP"


def _zip_bytes(csv_text: str, inner_name: str = "EQ040110.CSV") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, csv_text)
    return buf.getvalue()


class TestFetchEod:
    @respx.mock
    def test_fetches_and_returns_artifact(self):
        csv_text = (FIXTURES / "bse" / "legacy_EQ040110.CSV").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=_zip_bytes(csv_text),
                headers={"content-type": "application/x-zip-compressed"},
            )
        )

        provider = BseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "BSE")
        assert artifact.content.startswith(b"PK")

    @respx.mock
    def test_spa_shell_raises_data_not_published(self):
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text="<html><title>BSE</title></html>", headers={"content-type": "text/html"}
            )
        )

        provider = BseLegacyBhavcopyProvider()
        with pytest.raises(DataNotPublished):
            provider.fetch_eod(date(2010, 1, 4), "BSE")

    @respx.mock
    def test_corrupt_non_zip_raises_content_validation_error(self):
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, content=b"not a zip", headers={"content-type": "application/octet-stream"}
            )
        )

        provider = BseLegacyBhavcopyProvider()
        with pytest.raises(ContentValidationError):
            provider.fetch_eod(date(2010, 1, 4), "BSE")

    def test_non_bse_exchange_rejected(self):
        provider = BseLegacyBhavcopyProvider()
        with pytest.raises(ValueError, match="BSE"):
            provider.fetch_eod(date(2010, 1, 4), "NSE")


class TestParseEod:
    @respx.mock
    def test_end_to_end_fetch_then_parse(self):
        csv_text = (FIXTURES / "bse" / "legacy_EQ040110.CSV").read_text()
        respx.get(URL).mock(
            return_value=httpx.Response(
                200,
                content=_zip_bytes(csv_text),
                headers={"content-type": "application/x-zip-compressed"},
            )
        )

        provider = BseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "BSE")
        bars = list(provider.parse_eod(artifact))

        assert len(bars) == 50
        assert bars[0].symbol == "526987"  # BSE scrip code, no symbol in this format
        assert bars[0].date == date(2010, 1, 4)
        assert bars[0].delivery_qty is None
        assert bars[0].isin is None


class TestCapabilities:
    def test_declares_2010_earliest_date_no_delivery(self):
        caps = BseLegacyBhavcopyProvider().capabilities
        assert caps.earliest_date == date(2010, 1, 4)
        assert caps.supports_delivery is False
        assert caps.exchanges == frozenset({"BSE"})


@pytest.mark.live
class TestLiveEndpoint:
    def test_fetches_real_2010_data(self):
        provider = BseLegacyBhavcopyProvider()
        artifact = provider.fetch_eod(date(2010, 1, 4), "BSE")
        bars = list(provider.parse_eod(artifact))
        assert len(bars) > 500

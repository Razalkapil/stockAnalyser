"""Unit tests for the NSE UDiFF provider.

The behaviour that matters most here is a negative one: this provider
must NOT quietly become the primary price source. UDiFF carries ISIN
but drops delivery quantity, and delivery is what the short-term seed
strategies trade on -- a swap would silently null out a legitimately
nullable column from 2024-07 onward, which no schema check would catch.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from stk.core.errors import ContentValidationError, NotSupportedError
from stk.providers.base import RawArtifact
from stk.providers.nse.udiff import (
    _URL_TEMPLATE,
    NSE_UDIFF_AVAILABLE_FROM,
    SOURCE,
    NseUdiffProvider,
)
from stk.providers.registry import get_nse_price_provider_for_date, get_price_provider

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nse" / "udiff_20260917.csv"


def _zip_artifact(csv_text: str | None = None) -> RawArtifact:
    text = csv_text if csv_text is not None else FIXTURE.read_text()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BhavCopy_NSE_CM_0_0_0_20260917_F_0000.csv", text)
    return RawArtifact(
        source=SOURCE,
        business_date=date(2026, 9, 17),
        url="https://nsearchives.nseindia.com/content/cm/x.csv.zip",
        content=buffer.getvalue(),
        content_type="application/zip",
        http_status=200,
        fetched_at=datetime.now(UTC),
    )


@pytest.fixture
def provider() -> NseUdiffProvider:
    return NseUdiffProvider()


class TestUrlAndCapabilities:
    def test_url_uses_yyyymmdd(self):
        url = _URL_TEMPLATE.format(date="20260917")
        assert url.endswith("BhavCopy_NSE_CM_0_0_0_20260917_F_0000.csv.zip")

    def test_declares_no_delivery_support(self, provider):
        """The capability that keeps it off the primary path."""
        assert provider.capabilities.supports_delivery is False
        assert provider.capabilities.earliest_date == NSE_UDIFF_AVAILABLE_FROM

    def test_pre_cutover_date_raises(self, provider):
        with pytest.raises(NotSupportedError, match="62424"):
            provider.fetch_eod(date(2024, 7, 5), "NSE")

    def test_wrong_exchange_raises(self, provider):
        with pytest.raises(ValueError, match="only supports NSE"):
            provider.fetch_eod(date(2026, 9, 17), "BSE")


class TestParse:
    def test_yields_isin_bearing_bars(self, provider):
        bars = list(provider.parse_eod(_zip_artifact()))

        assert bars
        assert all(b.isin for b in bars), "every UDiFF row carries an ISIN"
        assert all(b.exchange == "NSE" for b in bars)
        assert all(b.date == date(2026, 9, 17) for b in bars)

    def test_delivery_is_absent_as_declared(self, provider):
        bars = list(provider.parse_eod(_zip_artifact()))
        assert all(b.delivery_qty is None for b in bars)

    def test_a_non_zip_body_is_a_content_validation_error(self, provider):
        artifact = _zip_artifact()
        artifact.content = b"<html>not a zip</html>"
        with pytest.raises(ContentValidationError, match="not a readable zip"):
            list(provider.parse_eod(artifact))


class TestRegistryWiring:
    def test_is_constructible_by_name(self):
        assert isinstance(get_price_provider("nse_udiff"), NseUdiffProvider)

    def test_is_not_the_automatic_choice_for_any_date(self):
        """sec_bhavdata_full must stay primary -- it has delivery data."""
        for probe in (date(2024, 7, 8), date(2026, 9, 17)):
            chosen = get_nse_price_provider_for_date(probe)
            assert not isinstance(chosen, NseUdiffProvider)
            assert chosen.capabilities.supports_delivery is True


@pytest.mark.live
class TestLiveEndpoint:
    def test_udiff_still_serves_a_zip(self, provider):
        artifact = provider.fetch_eod(date(2026, 9, 17), "NSE")
        assert artifact.content[:4] == b"PK\x03\x04"
        bars = list(provider.parse_eod(artifact))
        assert bars and all(b.isin for b in bars)

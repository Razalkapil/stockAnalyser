"""Tests for the provider registry -- the indirection point that lets
ingest code stay decoupled from concrete provider implementations."""

from __future__ import annotations

from datetime import date

import pytest

from stk.core.errors import ConfigError
from stk.providers.base import PriceProvider
from stk.providers.bse.legacy_prices import BseLegacyBhavcopyProvider
from stk.providers.bse.prices import BseUdiffProvider
from stk.providers.nse.prices import NseSecBhavdataProvider
from stk.providers.registry import get_bse_price_provider_for_date, get_price_provider


class TestGetPriceProvider:
    def test_known_name_returns_correct_type(self):
        provider = get_price_provider("nse_sec_bhavdata")
        assert isinstance(provider, NseSecBhavdataProvider)
        assert isinstance(provider, PriceProvider)

    def test_bse_udiff_returns_correct_type(self):
        provider = get_price_provider("bse_udiff")
        assert isinstance(provider, BseUdiffProvider)
        assert isinstance(provider, PriceProvider)

    def test_bse_legacy_bhavcopy_returns_correct_type(self):
        provider = get_price_provider("bse_legacy_bhavcopy")
        assert isinstance(provider, BseLegacyBhavcopyProvider)
        assert isinstance(provider, PriceProvider)

    def test_unknown_name_raises_config_error(self):
        with pytest.raises(ConfigError, match="unknown price provider"):
            get_price_provider("not_a_real_provider")


class TestGetBsePriceProviderForDate:
    def test_before_cutover_returns_legacy(self):
        assert isinstance(
            get_bse_price_provider_for_date(date(2024, 7, 5)), BseLegacyBhavcopyProvider
        )

    def test_on_or_after_cutover_returns_udiff(self):
        assert isinstance(get_bse_price_provider_for_date(date(2024, 7, 8)), BseUdiffProvider)

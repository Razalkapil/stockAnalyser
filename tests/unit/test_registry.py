"""Tests for the provider registry -- the indirection point that lets
ingest code stay decoupled from concrete provider implementations."""

from __future__ import annotations

import pytest

from stk.core.errors import ConfigError
from stk.providers.base import PriceProvider
from stk.providers.nse.prices import NseSecBhavdataProvider
from stk.providers.registry import get_price_provider


class TestGetPriceProvider:
    def test_known_name_returns_correct_type(self):
        provider = get_price_provider("nse_sec_bhavdata")
        assert isinstance(provider, NseSecBhavdataProvider)
        assert isinstance(provider, PriceProvider)

    def test_unknown_name_raises_config_error(self):
        with pytest.raises(ConfigError, match="unknown price provider"):
            get_price_provider("not_a_real_provider")

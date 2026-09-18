"""Tests for the provider registry -- the indirection point that lets
ingest code stay decoupled from concrete provider implementations."""

from __future__ import annotations

from datetime import date

import pytest

from stk.core.errors import ConfigError
from stk.providers.base import CorporateActionsProvider, PriceProvider, SecurityMasterProvider
from stk.providers.bse.legacy_prices import BseLegacyBhavcopyProvider
from stk.providers.bse.master import BseSecurityMasterProvider
from stk.providers.bse.prices import BseUdiffProvider
from stk.providers.nse.corpactions import NseCorporateActionsProvider
from stk.providers.nse.master import NseSecurityMasterProvider
from stk.providers.nse.prices import NseSecBhavdataProvider
from stk.providers.registry import (
    get_bse_price_provider_for_date,
    get_corporate_actions_provider,
    get_price_provider,
    get_security_master_provider,
)


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


class TestGetSecurityMasterProvider:
    def test_nse_equity_l_returns_correct_type(self):
        provider = get_security_master_provider("nse_equity_l")
        assert isinstance(provider, NseSecurityMasterProvider)
        assert isinstance(provider, SecurityMasterProvider)

    def test_bse_scrip_api_returns_correct_type(self):
        provider = get_security_master_provider("bse_scrip_api")
        assert isinstance(provider, BseSecurityMasterProvider)
        assert isinstance(provider, SecurityMasterProvider)

    def test_unknown_name_raises_config_error(self):
        with pytest.raises(ConfigError, match="unknown security master provider"):
            get_security_master_provider("not_a_real_provider")


class TestGetCorporateActionsProvider:
    def test_nse_corp_actions_returns_correct_type(self):
        provider = get_corporate_actions_provider("nse_corp_actions")
        assert isinstance(provider, NseCorporateActionsProvider)
        assert isinstance(provider, CorporateActionsProvider)

    def test_unknown_name_raises_config_error(self):
        with pytest.raises(ConfigError, match="unknown corporate actions provider"):
            get_corporate_actions_provider("not_a_real_provider")

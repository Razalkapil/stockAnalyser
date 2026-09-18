"""Provider construction from config.

Ingest code depends only on the ABCs in providers.base and obtains
instances through this module -- never by importing a concrete
provider class directly. That indirection is what makes swapping to a
paid broker adapter (phase 8) a one-config-line change: flip
providers.prices.NSE to "kite" in config/env/prod.yaml and add the
mapping here, and nothing in ingest/, domain/, or cli/ changes.
"""

from __future__ import annotations

from datetime import date

from stk.core.errors import ConfigError
from stk.providers.base import PriceProvider

# Confirmed by the phase-0 history spike (docs/adr/0003): sec_bhavdata_full
# is available from this date onward and is preferred over the legacy
# format whenever both cover a date, because it also carries delivery data.
SEC_BHAVDATA_AVAILABLE_FROM = date(2019, 9, 30)


def get_price_provider(name: str) -> PriceProvider:
    """Construct a PriceProvider by its config name (see providers.prices in defaults.yaml)."""
    if name == "nse_sec_bhavdata":
        from stk.providers.nse.prices import NseSecBhavdataProvider  # noqa: PLC0415

        return NseSecBhavdataProvider()

    if name == "nse_legacy_bhavcopy":
        from stk.providers.nse.legacy_prices import NseLegacyBhavcopyProvider  # noqa: PLC0415

        return NseLegacyBhavcopyProvider()

    # bse_udiff and a future kite/broker adapter register here as they land.
    raise ConfigError(f"unknown price provider: {name!r}")


def get_nse_price_provider_for_date(business_date: date) -> PriceProvider:
    """Automatic source selection for NSE prices by date, per the
    confirmed availability windows in docs/adr/0003-historical-price-source.md:

        2010-01-04 .. 2019-09-29   nse_legacy_bhavcopy  (no delivery, no ISIN)
        2019-09-30 onward          nse_sec_bhavdata     (has delivery, no ISIN)

    Both the nightly ingest and the backfill command must go through
    this single function for source selection, so the boundary date
    only needs to be correct in one place.
    """
    if business_date >= SEC_BHAVDATA_AVAILABLE_FROM:
        return get_price_provider("nse_sec_bhavdata")
    return get_price_provider("nse_legacy_bhavcopy")

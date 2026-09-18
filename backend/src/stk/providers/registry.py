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
from stk.providers.base import PriceProvider, SecurityMasterProvider

# Confirmed by the phase-0 history spike (docs/adr/0003): sec_bhavdata_full
# is available from this date onward and is preferred over the legacy
# format whenever both cover a date, because it also carries delivery data.
SEC_BHAVDATA_AVAILABLE_FROM = date(2019, 9, 30)

# Confirmed by direct probe (spike step 4, docs/adr/0003): BSE's UDiFF
# format starts here, the same industry-wide cutover date as NSE's.
# The legacy EQ*.CSV.ZIP format covers everything before it, back to
# at least 2010-01-04, with no gap at the boundary.
BSE_UDIFF_AVAILABLE_FROM = date(2024, 7, 8)


def get_price_provider(name: str) -> PriceProvider:
    """Construct a PriceProvider by its config name (see providers.prices in defaults.yaml)."""
    if name == "nse_sec_bhavdata":
        from stk.providers.nse.prices import NseSecBhavdataProvider  # noqa: PLC0415

        return NseSecBhavdataProvider()

    if name == "nse_legacy_bhavcopy":
        from stk.providers.nse.legacy_prices import NseLegacyBhavcopyProvider  # noqa: PLC0415

        return NseLegacyBhavcopyProvider()

    if name == "bse_udiff":
        from stk.providers.bse.prices import BseUdiffProvider  # noqa: PLC0415

        return BseUdiffProvider()

    if name == "bse_legacy_bhavcopy":
        from stk.providers.bse.legacy_prices import BseLegacyBhavcopyProvider  # noqa: PLC0415

        return BseLegacyBhavcopyProvider()

    # A future kite/broker adapter registers here as it lands.
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


def get_bse_price_provider_for_date(business_date: date) -> PriceProvider:
    """Automatic source selection for BSE prices by date, mirroring
    get_nse_price_provider_for_date -- see this module's docstring and
    docs/adr/0003-historical-price-source.md for the confirmed boundary:

        2010-01-04 .. 2024-07-05   bse_legacy_bhavcopy  (no delivery, no ISIN, no symbol)
        2024-07-08 onward          bse_udiff            (no delivery, has ISIN)

    A date before 2010-01-04 is not covered by either source and
    reaches BseLegacyBhavcopyProvider.fetch_eod, which does not itself
    guard that boundary -- callers relying on automatic selection get
    whatever BSE's archive actually returns for a date that old (most
    likely the SPA shell -> DataNotPublished), which is an honest
    "unknown" rather than a fabricated NotSupportedError for a boundary
    nobody has verified.
    """
    if business_date >= BSE_UDIFF_AVAILABLE_FROM:
        return get_price_provider("bse_udiff")
    return get_price_provider("bse_legacy_bhavcopy")


def get_security_master_provider(name: str) -> SecurityMasterProvider:
    """Construct a SecurityMasterProvider by its config name (see
    providers.security_master in defaults.yaml)."""
    if name == "nse_equity_l":
        from stk.providers.nse.master import NseSecurityMasterProvider  # noqa: PLC0415

        return NseSecurityMasterProvider()

    if name == "bse_scrip_api":
        from stk.providers.bse.master import BseSecurityMasterProvider  # noqa: PLC0415

        return BseSecurityMasterProvider()

    raise ConfigError(f"unknown security master provider: {name!r}")

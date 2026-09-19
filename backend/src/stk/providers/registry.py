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
from typing import TYPE_CHECKING

from stk.core.errors import ConfigError
from stk.providers.base import (
    CalendarProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    IntradayProvider,
    PriceProvider,
    SecurityMasterProvider,
)

if TYPE_CHECKING:
    from stk.providers.nse.indices import NseIndicesProvider

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

    if name == "nse_udiff":
        from stk.providers.nse.udiff import NseUdiffProvider  # noqa: PLC0415

        return NseUdiffProvider()

    if name == "yfinance":
        # Feature-flagged at construction, not at call sites. A caller
        # that forgot to check cannot accidentally put approximate,
        # survivorship-biased prices into a backtest -- see
        # providers/yfinance/prices.py's docstring.
        from stk.config.settings import get_settings  # noqa: PLC0415

        if not get_settings().providers.enable_yfinance_fallback:
            raise ConfigError(
                "the yfinance provider is disabled. It is approximate, rate-limited and "
                "survivorship-biased, and is never the critical path. Set "
                "providers.enable_yfinance_fallback: true to use it deliberately."
            )

        from stk.providers.yfinance.prices import YFinancePriceProvider  # noqa: PLC0415

        return YFinancePriceProvider()

    if name == "bse_legacy_bhavcopy":
        from stk.providers.bse.legacy_prices import BseLegacyBhavcopyProvider  # noqa: PLC0415

        return BseLegacyBhavcopyProvider()

    if name == "kite":
        # Documented stub: raises NotSupportedError from its constructor with the upgrade notes.
        from stk.providers.broker.kite import KitePriceProvider  # noqa: PLC0415

        KitePriceProvider()

    raise ConfigError(f"unknown price provider: {name!r}")


def get_intraday_provider(name: str | None = None) -> IntradayProvider:
    """The DELAYED intraday candle source for the paper-trading poller.

    Gated by its OWN switch, ``providers.enable_yfinance_intraday``, and independent of
    ``enable_yfinance_fallback``: turning intraday candles on for the playground must not put
    Yahoo anywhere near the end-of-day price pipeline.
    """
    from stk.config.settings import get_settings  # noqa: PLC0415

    settings = get_settings().providers
    chosen = name or settings.intraday
    if chosen == "yfinance_intraday":
        if not settings.enable_yfinance_intraday:
            raise ConfigError(
                "the intraday provider is disabled. Set providers.enable_yfinance_intraday: "
                "true to let the paper-trading poller use delayed Yahoo candles."
            )
        from stk.providers.yfinance.intraday import YFinanceIntradayProvider  # noqa: PLC0415

        return YFinanceIntradayProvider()
    raise ConfigError(f"unknown intraday provider: {chosen!r}")


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


def get_calendar_provider(name: str) -> CalendarProvider:
    """Construct a CalendarProvider by its config name (see
    providers.calendar in defaults.yaml)."""
    if name == "nse_holiday_master":
        from stk.providers.nse.calendar import NseHolidayMasterProvider  # noqa: PLC0415

        return NseHolidayMasterProvider()

    raise ConfigError(f"unknown calendar provider: {name!r}")


def get_indices_provider(name: str = "nse_indices") -> NseIndicesProvider:
    """Construct the index (benchmark) provider by name.

    Not behind an ABC yet: there is exactly one implementation and no
    second shape to generalise from, and inventing an interface from a
    single example is how you get an interface that fits only that
    example. It still goes through the registry so ingest/ never
    imports the concrete module.
    """
    if name == "nse_indices":
        from stk.providers.nse.indices import NseIndicesProvider  # noqa: PLC0415

        return NseIndicesProvider()

    raise ConfigError(f"unknown indices provider: {name!r}")


def get_corporate_actions_provider(name: str) -> CorporateActionsProvider:
    """Construct a CorporateActionsProvider by its config name (see
    providers.corp_actions in defaults.yaml)."""
    if name == "nse_corp_actions":
        from stk.providers.nse.corpactions import NseCorporateActionsProvider  # noqa: PLC0415

        return NseCorporateActionsProvider()

    raise ConfigError(f"unknown corporate actions provider: {name!r}")


def get_fundamentals_provider(name: str) -> FundamentalsProvider:
    """Construct a FundamentalsProvider by its config name (see
    providers.fundamentals in defaults.yaml)."""
    if name == "nse_filings":
        from stk.providers.nse.fundamentals import NseFundamentalsProvider  # noqa: PLC0415

        return NseFundamentalsProvider()

    raise ConfigError(f"unknown fundamentals provider: {name!r}")

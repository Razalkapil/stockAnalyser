"""Provider construction from config.

Ingest code depends only on the ABCs in providers.base and obtains
instances through this module -- never by importing a concrete
provider class directly. That indirection is what makes swapping to a
paid broker adapter (phase 8) a one-config-line change: flip
providers.prices.NSE to "kite" in config/env/prod.yaml and add the
mapping here, and nothing in ingest/, domain/, or cli/ changes.
"""

from __future__ import annotations

from stk.core.errors import ConfigError
from stk.providers.base import PriceProvider


def get_price_provider(name: str) -> PriceProvider:
    """Construct a PriceProvider by its config name (see providers.prices in defaults.yaml)."""
    if name == "nse_sec_bhavdata":
        # Lazy import: registry.py is the one place allowed to know
        # about concrete providers; importing them all eagerly would
        # pull in every provider's dependencies even when unused.
        from stk.providers.nse.prices import NseSecBhavdataProvider  # noqa: PLC0415

        return NseSecBhavdataProvider()

    # bse_udiff and a future kite/broker adapter register here as they land.
    raise ConfigError(f"unknown price provider: {name!r}")

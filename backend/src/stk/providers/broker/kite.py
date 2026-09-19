"""Zerodha Kite Connect adapter -- a deliberate, documented STUB.

Why it exists: the brief keeps a paid real-time source as the upgrade path from the free,
15-minute-delayed feed. This file marks exactly where that adapter goes and what it must do, so
the upgrade is one class and one config line, not a rewrite. It is not implemented because it
needs a paid Kite Connect subscription and an interactive daily login (the access token expires
every morning), neither of which exists for this project yet.

To implement it:

1. ``KitePriceProvider(PriceProvider)`` for end-of-day bars if wanted, and a
   ``KiteIntradayProvider(IntradayProvider)`` whose ``fetch_candles_raw`` returns the verbatim
   ``historical_data`` response and whose ``parse_candles`` turns it into ``IntradayCandle`` (IST
   aware, prices as ``Decimal``). Raw bytes are persisted before parsing, as for every provider.
2. Register it in ``stk.providers.registry`` (``get_intraday_provider`` /
   ``get_price_provider``) and select it with ``providers.intraday: kite`` in
   ``config/env/prod.yaml``. Nothing in ``ingest/``, ``playground/`` or ``api/`` changes -- they
   only see the ABCs.
3. Set ``ProviderCapabilities(is_realtime=True, is_approximate=False)``. The poller's staleness
   check and the UI's "delayed" pill both read that, and drop the delay warning on their own.
4. Keep the credential in ``.env`` (never committed) and make a missing/expired token fail
   loudly, not fall back to another source.
"""

from __future__ import annotations

from stk.core.errors import NotSupportedError


class KitePriceProvider:
    """Placeholder. Constructing it raises, so selecting ``kite`` in config fails at startup with
    an explanation rather than at the first poll."""

    def __init__(self) -> None:
        raise NotSupportedError(
            "the Kite Connect adapter is not implemented (it needs a paid subscription and a "
            "daily login). See the module docstring of stk.providers.broker.kite."
        )

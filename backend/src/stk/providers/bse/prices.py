"""BSE UDiFF price provider.

Unlike NSE, BSE has only one confirmed live price source: the UDiFF
bhavcopy, available from 2024-07-08 onward (the same industry-wide
cutover date as NSE's UDiFF, per NSE circular 62424 -- both exchanges
moved to the shared UDiFF format together). BSE's pre-UDiFF history
depth was NOT investigated (the phase-0 history spike's step 4, per
docs/adr/0003-historical-price-source.md) -- this is a known,
documented gap, not an oversight. Requesting an earlier date raises
NotSupportedError rather than silently returning nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from stk.core.errors import ContentValidationError, NotSupportedError
from stk.core.time import format_yyyymmdd
from stk.ingest.normalise import parse_udiff
from stk.providers.base import CanonicalBar, PriceProvider, ProviderCapabilities, RawArtifact
from stk.providers.bse.archives import fetch_bse_csv_file

_URL_TEMPLATE = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date}_F_0000.CSV"
SOURCE = "bse_udiff"
BSE_UDIFF_AVAILABLE_FROM = date(2024, 7, 8)


class BseUdiffProvider(PriceProvider):
    """PriceProvider backed by BSE's UDiFF daily bhavcopy."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"BSE"}),
            earliest_date=BSE_UDIFF_AVAILABLE_FROM,
            supports_delivery=False,
            supports_intraday=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if exchange != "BSE":
            raise ValueError(f"{type(self).__name__} only supports BSE, got {exchange!r}")
        if business_date < BSE_UDIFF_AVAILABLE_FROM:
            raise NotSupportedError(
                f"BSE price history before {BSE_UDIFF_AVAILABLE_FROM.isoformat()} is not "
                "implemented -- see docs/adr/0003-historical-price-source.md (spike step 4 "
                "was deferred, not attempted)"
            )

        url = _URL_TEMPLATE.format(date=format_yyyymmdd(business_date))
        return fetch_bse_csv_file(
            url,
            source=SOURCE,
            business_date=business_date,
            expected_header_token="TradDt",
        )

    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        text = artifact.content.decode("utf-8", errors="strict")
        try:
            yield from parse_udiff(text, exchange="BSE", source=SOURCE)
        except KeyError as exc:
            raise ContentValidationError(
                artifact.url, f"missing expected column {exc}", artifact.content
            ) from exc

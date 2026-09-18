"""NSE sec_bhavdata_full price provider.

This is the PRIMARY historical price source (see the module docstring
in stk.ingest.normalise and docs/adr/0003 once the phase-0 history
spike is complete): it predates the UDiFF format, carries OHLCV +
delivery in one file, and appears continuous back through NSE's
archive. UDiFF is a separate, ISIN-bearing companion provider used for
the security-master join, not the primary price source.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from stk.core.errors import ContentValidationError
from stk.core.time import format_ddmmyyyy_compact
from stk.ingest.normalise import parse_sec_bhavdata_full
from stk.providers.base import CanonicalBar, PriceProvider, ProviderCapabilities, RawArtifact
from stk.providers.nse.archives import fetch_csv_file

_URL_TEMPLATE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
SOURCE = "nse_sec_bhavdata"


class NseSecBhavdataProvider(PriceProvider):
    """PriceProvider backed by NSE's sec_bhavdata_full daily file."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"NSE"}),
            earliest_date=None,  # confirmed by the phase-0 history spike, not hardcoded here
            supports_delivery=True,
            supports_intraday=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if exchange != "NSE":
            raise ValueError(f"{type(self).__name__} only supports NSE, got {exchange!r}")

        url = _URL_TEMPLATE.format(date=format_ddmmyyyy_compact(business_date))
        return fetch_csv_file(
            url,
            source=SOURCE,
            business_date=business_date,
            expected_header_token="SYMBOL",
        )

    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        text = artifact.content.decode("utf-8", errors="strict")
        try:
            yield from parse_sec_bhavdata_full(text, source=SOURCE)
        except KeyError as exc:
            raise ContentValidationError(
                artifact.url, f"missing expected column {exc}", artifact.content
            ) from exc

"""NSE UDiFF price provider -- the ISIN-bearing companion.

    https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

Available from 2024-07-08 (NSE circular 62424's cutover). Verified live
2026-09-19 for both that first date and a recent one.

WHY THIS IS REGISTERED BUT NOT THE DEFAULT. UDiFF carries ISIN, which
sec_bhavdata_full does not. It does NOT carry delivery quantity or
delivery percentage, which sec_bhavdata_full does and which the
short-term seed strategies need. So sec_bhavdata_full remains the
primary source for prices (see registry.get_nse_price_provider_for_date,
unchanged), and this provider exists for the identity information:
fetching it for a date gives an authoritative symbol -> ISIN mapping
straight from the exchange for that session.

Using this as the price source would silently drop delivery data from
every bar from 2024-07 onward, which no test would catch because the
column is legitimately nullable.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import date

from stk.core.errors import ContentValidationError, NotSupportedError
from stk.core.time import format_yyyymmdd
from stk.ingest.normalise import parse_udiff
from stk.providers.base import CanonicalBar, PriceProvider, ProviderCapabilities, RawArtifact
from stk.providers.nse.archives import fetch_zip_file

_URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
)
SOURCE = "nse_udiff"
NSE_UDIFF_AVAILABLE_FROM = date(2024, 7, 8)


class NseUdiffProvider(PriceProvider):
    """PriceProvider backed by NSE's UDiFF daily bhavcopy."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"NSE"}),
            earliest_date=NSE_UDIFF_AVAILABLE_FROM,
            # The whole reason this provider is not the primary source.
            supports_delivery=False,
            supports_intraday=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if exchange != "NSE":
            raise ValueError(f"{type(self).__name__} only supports NSE, got {exchange!r}")
        if business_date < NSE_UDIFF_AVAILABLE_FROM:
            raise NotSupportedError(
                f"NSE UDiFF does not exist before {NSE_UDIFF_AVAILABLE_FROM.isoformat()} "
                "(NSE circular 62424) -- use sec_bhavdata_full or the legacy archive"
            )

        url = _URL_TEMPLATE.format(date=format_yyyymmdd(business_date))
        return fetch_zip_file(url, source=SOURCE, business_date=business_date)

    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(artifact.content))
            names = archive.namelist()
            if not names:
                raise ContentValidationError(artifact.url, "zip archive is empty", b"")
            text = archive.read(names[0]).decode("utf-8-sig")
        except zipfile.BadZipFile as exc:
            raise ContentValidationError(
                artifact.url, f"not a readable zip: {exc}", artifact.content[:200]
            ) from exc

        return parse_udiff(text, exchange="NSE", source=SOURCE)

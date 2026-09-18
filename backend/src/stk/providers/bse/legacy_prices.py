"""BSE legacy bhavcopy price provider (2010 through 2024-07-05).

Confirmed by direct probe on 2026-09-18 (the deferred phase-0 history
spike step 4, see docs/adr/0003-historical-price-source.md): BSE's
current download host still serves this format at its original URL
pattern, back to at least 2010-01-04 and continuously through
2024-07-05 -- the Friday before the industry-wide UDiFF cutover on
2024-07-08, the same date NSE's own format changed. No gap, no
overlap: the last legacy date and the first UDiFF date are adjacent
trading days.

No delivery data, no ISIN, no symbol -- only a numeric scrip code. See
normalise.parse_bse_legacy_bhavcopy for what fields are and aren't
populated.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from datetime import date
from io import BytesIO

from stk.core.errors import ContentValidationError
from stk.core.time import format_ddmmyy_compact
from stk.ingest.normalise import parse_bse_legacy_bhavcopy
from stk.providers.base import CanonicalBar, PriceProvider, ProviderCapabilities, RawArtifact
from stk.providers.bse.archives import fetch_bse_zip_file

_URL_TEMPLATE = "https://www.bseindia.com/download/BhavCopy/Equity/EQ{dm}_CSV.ZIP"
SOURCE = "bse_legacy_bhavcopy"


class BseLegacyBhavcopyProvider(PriceProvider):
    """PriceProvider backed by BSE's legacy per-date EQ*.CSV.ZIP archive."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"BSE"}),
            earliest_date=date(2010, 1, 4),  # confirmed reachable by direct probe
            supports_delivery=False,
            supports_intraday=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if exchange != "BSE":
            raise ValueError(f"{type(self).__name__} only supports BSE, got {exchange!r}")

        url = _URL_TEMPLATE.format(dm=format_ddmmyy_compact(business_date))
        return fetch_bse_zip_file(url, source=SOURCE, business_date=business_date)

    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        try:
            with zipfile.ZipFile(BytesIO(artifact.content)) as zf:
                names = zf.namelist()
                if len(names) != 1:
                    raise ContentValidationError(
                        artifact.url,
                        f"expected exactly one file in the zip, found {names}",
                        artifact.content,
                    )
                text = zf.read(names[0]).decode("utf-8", errors="strict")
        except zipfile.BadZipFile as exc:
            raise ContentValidationError(
                artifact.url, f"not a valid zip file: {exc}", artifact.content
            ) from exc

        if artifact.business_date is None:
            raise ContentValidationError(
                artifact.url, "no business_date on artifact -- required to date this file's rows",
                artifact.content,
            )

        try:
            yield from parse_bse_legacy_bhavcopy(
                text, business_date=artifact.business_date, source=SOURCE
            )
        except KeyError as exc:
            raise ContentValidationError(
                artifact.url, f"missing expected column {exc}", artifact.content
            ) from exc

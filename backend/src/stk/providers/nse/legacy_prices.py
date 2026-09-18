"""NSE legacy bhavcopy price provider (2010 through ~2019-10-01).

Confirmed by the phase-0 history spike (docs/adr/0003) as the ONLY
source reaching back to 2010 -- NSE's own current archive still serves
this retired-in-name-only format at its original URL pattern, unlike
the even-older path referenced in outdated tutorials
(/content/historical/EQUITIES/... predating a 2015-ish reorganisation,
which does 404). No delivery data, no ISIN: see normalise.parse_legacy_bhavcopy
for what fields are and aren't populated.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from datetime import date
from io import BytesIO

from stk.core.errors import ContentValidationError
from stk.ingest.normalise import parse_legacy_bhavcopy
from stk.providers.base import CanonicalBar, PriceProvider, ProviderCapabilities, RawArtifact
from stk.providers.nse.archives import fetch_zip_file

_URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
    "{year}/{mon}/cm{dm}bhav.csv.zip"
)
SOURCE = "nse_legacy_bhavcopy"


class NseLegacyBhavcopyProvider(PriceProvider):
    """PriceProvider backed by NSE's legacy per-date cm*bhav.csv.zip archive."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=SOURCE,
            exchanges=frozenset({"NSE"}),
            earliest_date=date(2010, 1, 4),  # confirmed reachable by the history spike
            supports_delivery=False,
            supports_intraday=False,
        )

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if exchange != "NSE":
            raise ValueError(f"{type(self).__name__} only supports NSE, got {exchange!r}")

        mon = business_date.strftime("%b").upper()
        dm = business_date.strftime("%d%b%Y").upper()
        url = _URL_TEMPLATE.format(year=business_date.year, mon=mon, dm=dm)
        return fetch_zip_file(url, source=SOURCE, business_date=business_date)

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

        try:
            yield from parse_legacy_bhavcopy(text, source=SOURCE)
        except KeyError as exc:
            raise ContentValidationError(
                artifact.url, f"missing expected column {exc}", artifact.content
            ) from exc

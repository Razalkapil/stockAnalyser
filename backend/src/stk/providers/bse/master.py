"""BSE security-master provider.

Unlike the bhavcopy downloads, this is a JSON API on a different host
(api.bseindia.com, not www.bseindia.com) that requires a Referer header
-- verified 2026-09-18, see docs/data-sources.md. No cookie handshake
needed, unlike NSE's www.nseindia.com/api/*.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from stk.core.errors import ProviderUnavailable
from stk.core.http import DEFAULT_UA, validate_json_response
from stk.providers.base import MasterRecord, SecurityMasterProvider

_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
_REFERER = "https://www.bseindia.com/"
SOURCE = "bse_scrip_api"


def _decimal_or_none(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    value = raw.strip()
    return Decimal(value) if value else None


class BseSecurityMasterProvider(SecurityMasterProvider):
    """SecurityMasterProvider backed by BSE's ListofScripData JSON API."""

    def fetch_master(self, *, timeout_s: float = 30.0) -> list[MasterRecord]:
        try:
            response = httpx.get(
                _URL,
                headers={"User-Agent": DEFAULT_UA, "Referer": _REFERER},
                timeout=timeout_s,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"transport error fetching {_URL}: {exc}") from exc

        payload = validate_json_response(response, url=_URL)
        if not isinstance(payload, list):
            raise ProviderUnavailable(f"{_URL} did not return a JSON array")

        records = []
        for row in payload:
            isin = (row.get("ISIN_NUMBER") or "").strip()
            symbol = (row.get("scrip_id") or "").strip()
            if not isin or not symbol:
                # Blank ISIN/scrip_id is real (some BSE-listed entities
                # lack one) -- skip rather than guess, per the build
                # plan's ISIN-merge edge cases.
                continue
            records.append(
                MasterRecord(
                    isin=isin,
                    symbol=symbol,
                    company_name=(row.get("Issuer_Name") or row.get("Scrip_Name") or "").strip(),
                    exchange="BSE",
                    series=(row.get("GROUP") or "").strip() or None,
                    exchange_token=(row.get("SCRIP_CD") or "").strip() or None,
                    face_value=_decimal_or_none(row.get("FACE_VALUE")),
                )
            )
        return records

"""NSE corporate-actions provider.

Verified live 2026-09-18: unlike the vague folklore that
www.nseindia.com/api/* universally needs a primed cookie jar plus a
Referer, this specific endpoint answered 200 with a plain non-default
User-Agent alone -- no cookie handshake, no Referer required in
practice. A Referer is still sent defensively (cheap, and other
www.nseindia.com/api/* endpoints may be stricter), but nothing here
depends on a cookie jar. Update docs/data-sources.md if a future check
finds this has tightened.

Subjects are returned UNPARSED, per CorporateActionsProvider's
contract -- stk.ingest.corpactions.parse_subject is the single place
that turns free text into typed, price/volume-adjusting facts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import httpx

from stk.core.errors import ProviderUnavailable
from stk.core.http import BROWSER_UA, validate_json_response
from stk.providers.base import CorporateActionsProvider, RawCorporateAction

_URL = "https://www.nseindia.com/api/corporates-corporateActions"
_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-corporate-actions"
SOURCE = "nse_corp_actions"


def _parse_ddmmmyyyy_or_none(raw: str | None) -> date | None:
    if not raw or raw == "-":
        return None
    return datetime.strptime(raw.strip(), "%d-%b-%Y").date()


def _source_hash(row: dict) -> str:
    """Stable hash of the fields that define this action's identity and
    content -- used as raw_artifacts-style idempotency key so a
    re-fetch of an unchanged action never inserts a duplicate row, but
    NSE correcting a subject or a date DOES produce a new, detectable
    row (same principle as raw_artifacts' sha256-on-content check)."""
    stable = {
        "symbol": row.get("symbol"), "isin": row.get("isin"), "exDate": row.get("exDate"),
        "recDate": row.get("recDate"), "subject": row.get("subject"),
        "caBroadcastDate": row.get("caBroadcastDate"),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


class NseCorporateActionsProvider(CorporateActionsProvider):
    """CorporateActionsProvider backed by NSE's corporates-corporateActions API."""

    def fetch_actions(
        self, since: date | None = None, *, timeout_s: float = 30.0
    ) -> list[RawCorporateAction]:
        params = {"index": "equities"}
        if since is not None:
            params["from_date"] = since.strftime("%d-%m-%Y")
            params["to_date"] = date.today().strftime("%d-%m-%Y")

        try:
            response = httpx.get(
                _URL,
                params=params,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Referer": _REFERER,
                    "Accept": "application/json",
                },
                timeout=timeout_s,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"transport error fetching {_URL}: {exc}") from exc

        payload = validate_json_response(response, url=_URL)
        if not isinstance(payload, list):
            raise ProviderUnavailable(f"{_URL} did not return a JSON array")

        captured_at = datetime.now(UTC)
        actions = []
        for row in payload:
            symbol = (row.get("symbol") or "").strip()
            subject = (row.get("subject") or "").strip()
            if not symbol or not subject:
                continue
            actions.append(
                RawCorporateAction(
                    symbol=symbol,
                    exchange="NSE",
                    isin=(row.get("isin") or "").strip() or None,
                    ex_date=_parse_ddmmmyyyy_or_none(row.get("exDate")),
                    record_date=_parse_ddmmmyyyy_or_none(row.get("recDate")),
                    bc_start_date=_parse_ddmmmyyyy_or_none(row.get("bcStartDate")),
                    bc_end_date=_parse_ddmmmyyyy_or_none(row.get("bcEndDate")),
                    subject_raw=subject,
                    source=SOURCE,
                    source_hash=_source_hash(row),
                    captured_at=captured_at,
                )
            )
        return actions

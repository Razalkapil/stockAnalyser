"""NSE fundamentals provider -- filing METADATA, not parsed line items.

Verified live 2026-09-18: `corporates-financial-results` returns each
filing's point-in-time metadata (broadcast date, audited/consolidated
flags, period, an XBRL document link) but -- contrary to the build
plan's original research assumption ("official, no XBRL parsing
needed") -- `resultDetailedDataLink` (the field that would carry
pre-parsed structured line items) was empty on every sampled row, for
both a broad equities scan and a single-symbol query. Actual income/
balance/cashflow figures live only in the linked XBRL document.

CONSEQUENCE, stated plainly rather than glossed over: this provider
gives genuine, official, point-in-time filing metadata -- suitable for
knowledge-date-correct backtesting of "when did the market first know
this filing existed" -- but NOT parsed financial figures. XBRL parsing
is a separate, substantial scope (a real XML schema per indAs/format
combination) deliberately deferred rather than attempted partially;
``FundamentalsSnapshotIn.data`` here holds the filing's own metadata
fields (including the XBRL URL) so nothing is lost, and
``statement_type="meta"`` marks it honestly rather than mislabelling
it as parsed "income"/"balance"/"cashflow" data it is not.

Only "Quarterly" and "Annual" period values were confirmed to filter
correctly by live probe (distinct, plausible row counts). "Half-Yearly"
and Period.TTM's API-side query values were NOT reliably confirmed
(ambiguous responses during probing) -- requesting them raises
NotSupportedError rather than guessing at an unverified query string.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

import httpx

from stk.core.errors import NotSupportedError, ProviderUnavailable
from stk.core.http import BROWSER_UA, validate_json_response
from stk.providers.base import (
    FilingRef,
    FundamentalsProvider,
    FundamentalsSnapshotIn,
    Period,
    SecurityRef,
)

_URL = "https://www.nseindia.com/api/corporates-financial-results"
SOURCE = "nse_filings"

_PERIOD_QUERY_VALUE = {
    Period.QUARTERLY: "Quarterly",
    Period.ANNUAL: "Annual",
}


def _parse_broadcast_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.strptime(raw.strip(), "%d-%b-%Y %H:%M:%S")


def _fetch_rows(params: dict[str, str], *, timeout_s: float = 30.0) -> list[dict]:
    try:
        response = httpx.get(
            _URL,
            params=params,
            headers={"User-Agent": BROWSER_UA},
            timeout=timeout_s,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"transport error fetching {_URL}: {exc}") from exc

    payload = validate_json_response(response, url=_URL)
    if not isinstance(payload, list):
        raise ProviderUnavailable(f"{_URL} did not return a JSON array")
    return payload


def _row_to_snapshot(row: dict, *, period_type: Period) -> FundamentalsSnapshotIn | None:
    isin = (row.get("isin") or "").strip()
    to_date = (row.get("toDate") or "").strip()
    seq_number = (row.get("seqNumber") or "").strip()
    if not isin or not to_date or not seq_number:
        return None

    period_end = datetime.strptime(to_date, "%d-%b-%Y").date()
    consolidated_raw = (row.get("consolidated") or "").strip().lower()
    audited_raw = (row.get("audited") or "").strip().lower()
    broadcast_at = _parse_broadcast_at(row.get("broadCastDate"))

    return FundamentalsSnapshotIn(
        security_isin=isin,
        provider=SOURCE,
        statement_type="meta",  # see this module's docstring -- metadata, not parsed figures
        period_type=period_type,
        period_end=period_end,
        consolidated="consolidated" in consolidated_raw and "non" not in consolidated_raw,
        audited=audited_raw == "audited",
        filing_system="financial_results",
        broadcast_at=broadcast_at,
        captured_at=datetime.now(UTC),
        is_approximate=False,  # official NSE filing metadata, not a third-party estimate
        data=row,
        source_url=row.get("xbrl") or None,
        source_hash=hashlib.sha256(seq_number.encode()).hexdigest(),
    )


class NseFundamentalsProvider(FundamentalsProvider):
    """FundamentalsProvider backed by NSE's corporates-financial-results API."""

    @property
    def is_approximate(self) -> bool:
        return False

    def fetch_filings_index(self, since: date, period: Period) -> list[FilingRef]:
        if period not in _PERIOD_QUERY_VALUE:
            raise NotSupportedError(
                f"{type(self).__name__} does not have a confirmed API query value for {period!r}"
            )
        rows = _fetch_rows({"index": "equities", "period": _PERIOD_QUERY_VALUE[period]})

        refs = []
        for row in rows:
            isin = (row.get("isin") or "").strip()
            to_date = (row.get("toDate") or "").strip()
            if not isin or not to_date:
                continue
            broadcast_at = _parse_broadcast_at(row.get("broadCastDate"))
            if since is not None and broadcast_at is not None and broadcast_at.date() < since:
                continue
            refs.append(
                FilingRef(
                    security_isin=isin,
                    period_type=period,
                    period_end=datetime.strptime(to_date, "%d-%b-%Y").date(),
                    filing_system="financial_results",
                    broadcast_at=broadcast_at,
                    source_url=row.get("xbrl") or None,
                )
            )
        return refs

    def fetch_statements(
        self, security: SecurityRef, period_type: Period, limit: int = 12
    ) -> list[FundamentalsSnapshotIn]:
        if period_type not in _PERIOD_QUERY_VALUE:
            raise NotSupportedError(
                f"{type(self).__name__} does not have a confirmed API query value "
                f"for {period_type!r}"
            )
        rows = _fetch_rows(
            {
                "index": "equities",
                "period": _PERIOD_QUERY_VALUE[period_type],
                "symbol": security.symbol,
            }
        )

        snapshots = []
        for row in rows:
            snapshot = _row_to_snapshot(row, period_type=period_type)
            if snapshot is not None:
                snapshots.append(snapshot)

        snapshots.sort(key=lambda s: s.broadcast_at or datetime.min, reverse=True)
        return snapshots[:limit]

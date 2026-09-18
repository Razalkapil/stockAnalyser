"""NSE trading-holiday calendar provider.

Endpoint (re-verified live 2026-09-19):

    https://www.nseindia.com/api/holiday-master?type=trading&year=YYYY

Two findings from that probe, both correcting earlier assumptions:

1. **The `year` parameter works, and history reaches back to 2011.**
   The build plan assumed this endpoint served only the current year,
   which would have left 2011-2025 with no authoritative calendar.
   Confirmed live: every year from 2011 to 2026 returns a populated
   `CM` (capital market / equities) list. A `financial_year` parameter
   is silently IGNORED -- it returns the current year's data, which is
   exactly the kind of quiet wrong answer that makes a caller think it
   asked a question it did not.

2. **An out-of-range year is a SILENT 200, not a 404.** 2010 returns
   `{}` and 2027 returns a payload whose `CM` list is absent/empty --
   both with HTTP 200 and a valid JSON content-type. Treating that as
   "no holidays that year" would fabricate a calendar in which every
   weekday is a trading day, and `stk doctor` would then cheerfully
   report ~250 missing trading days for 2010. So an empty segment list
   raises DataNotPublished, the same way BSE's SPA-shell 200 does.
   This is the same class of trap docs/data-sources.md documents for
   BSE, appearing on a completely different host.

Segment codes in the payload: `CM` is the equities segment we want.
`CBM` (corporate bond market) is NOT it -- it happens to be the first
key in the JSON object, which makes it an easy and wrong default.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx

from stk.core.errors import DataNotPublished, ParseError, ProviderUnavailable
from stk.core.http import BROWSER_UA, validate_json_response
from stk.providers.base import CalendarProvider, HolidayRecord, RawArtifact

_URL = "https://www.nseindia.com/api/holiday-master"
_REFERER = "https://www.nseindia.com/resources/exchange-communication-holidays"
SOURCE = "nse_holiday_master"

#: Capital-market (equities) segment key in the holiday-master payload.
EQUITY_SEGMENT = "CM"

#: Earliest year confirmed to return data (2010 returns an empty payload).
EARLIEST_YEAR = 2011


class NseHolidayMasterProvider(CalendarProvider):
    """CalendarProvider backed by NSE's holiday-master API."""

    def fetch_holidays_artifact(self, year: int, *, timeout_s: float = 30.0) -> RawArtifact:
        params = {"type": "trading", "year": str(year)}
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

        validate_json_response(response, url=str(response.url))
        return RawArtifact(
            source=SOURCE,
            business_date=date(year, 1, 1),
            url=str(response.url),
            content=response.content,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            fetched_at=datetime.now(UTC),
        )

    def parse_holidays(
        self, artifact: RawArtifact, segment: str = EQUITY_SEGMENT
    ) -> list[HolidayRecord]:
        """Holiday rows for one segment, dates parsed strictly.

        An absent or empty segment list raises DataNotPublished rather
        than returning [] -- see this module's docstring for why an
        empty calendar is far more dangerous than a missing one.
        """
        payload = validate_json_response_bytes(artifact)
        rows = payload.get(segment)
        if not rows:
            raise DataNotPublished(
                f"{artifact.url} returned no {segment} holiday rows "
                f"(segments present: {sorted(payload)}). NSE serves HTTP 200 with an "
                "empty payload for out-of-range years; treating that as 'no holidays' "
                "would fabricate a full year of trading days."
            )

        records = []
        for row in rows:
            raw_date = (row.get("tradingDate") or "").strip()
            if not raw_date:
                raise ParseError(f"holiday row with no tradingDate: {row!r}")
            try:
                # Explicit format, never dateutil inference -- see the
                # project's normalisation rules.
                trading_date = datetime.strptime(raw_date, "%d-%b-%Y").date()
            except ValueError as exc:
                raise ParseError(f"unparseable holiday tradingDate {raw_date!r}: {exc}") from exc
            records.append(
                HolidayRecord(
                    trading_date=trading_date,
                    description=(row.get("description") or "").strip() or "Unspecified holiday",
                    segment=segment,
                )
            )
        return records

    def trading_days(self, start: date, end: date, exchange: str) -> list[date]:
        """All trading days in [start, end], weekday-intersected.

        Imports the pure calendar rule from domain/ rather than
        re-deriving weekday arithmetic here -- the provider's job is
        raw facts, the decision is domain logic.
        """
        from stk.domain.calendar import build_trading_day_set  # noqa: PLC0415

        holidays: set[date] = set()
        for year in range(start.year, end.year + 1):
            holidays.update(h.trading_date for h in self.fetch_holidays(year))
        return sorted(build_trading_day_set(start, end, holidays))


def validate_json_response_bytes(artifact: RawArtifact) -> dict:
    """Re-parse a persisted artifact's bytes as a JSON object.

    Separate from core.http.validate_json_response because that one
    validates a live httpx.Response; this parses bytes already on disk,
    which is the whole point of persisting raw artifacts (re-parsing
    never needs the network).
    """
    try:
        payload = json.loads(artifact.content)
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON in artifact from {artifact.url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ParseError(
            f"expected a JSON object from {artifact.url}, got {type(payload).__name__}"
        )
    return payload

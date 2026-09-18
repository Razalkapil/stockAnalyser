"""Unit tests for the NSE holiday-master provider.

The two behaviours that carry real risk here are both about NOT
trusting a successful-looking response: an out-of-range year returns
HTTP 200 with an empty payload (which, taken at face value, fabricates
a year in which every weekday traded), and the payload's first key is
CBM (corporate bonds), not the CM equities segment we actually want.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from stk.core.errors import DataNotPublished, ParseError
from stk.domain.calendar import build_trading_day_set
from stk.providers.base import RawArtifact
from stk.providers.nse.calendar import EQUITY_SEGMENT, SOURCE, NseHolidayMasterProvider

FIXTURE = Path(__file__).parent.parent / "fixtures" / "nse" / "holiday_master.json"


def _artifact(payload: dict | bytes) -> RawArtifact:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return RawArtifact(
        source=SOURCE,
        business_date=date(2026, 1, 1),
        url="https://www.nseindia.com/api/holiday-master?type=trading&year=2026",
        content=content,
        content_type="application/json",
        http_status=200,
        fetched_at=datetime.now(UTC),
    )


@pytest.fixture
def provider() -> NseHolidayMasterProvider:
    return NseHolidayMasterProvider()


class TestParseHolidays:
    def test_parses_the_real_fixture(self, provider):
        artifact = _artifact(FIXTURE.read_bytes())
        records = provider.parse_holidays(artifact, "CBM")

        assert records
        assert all(r.segment == "CBM" for r in records)
        republic_day = [r for r in records if r.trading_date == date(2026, 1, 26)]
        assert republic_day and republic_day[0].description == "Republic Day"

    def test_weekend_holidays_are_kept_in_the_raw_records(self, provider):
        """NSE lists holidays falling on a Saturday/Sunday. The PROVIDER
        must not drop them -- the weekday intersection belongs to
        domain.calendar, so there is exactly one place that rule lives
        and one place to test it."""
        artifact = _artifact(FIXTURE.read_bytes())
        records = provider.parse_holidays(artifact, "CBM")

        weekend_holidays = [r for r in records if r.trading_date.weekday() >= 5]
        assert weekend_holidays, "fixture should contain at least one weekend-falling holiday"

        # ...and they make no difference once domain/ applies the rule.
        holiday_dates = {r.trading_date for r in records}
        trading = build_trading_day_set(date(2026, 1, 1), date(2026, 12, 31), holiday_dates)
        assert not any(d.weekday() >= 5 for d in trading)

    def test_empty_segment_raises_rather_than_fabricating_a_year(self, provider):
        """An out-of-range year (2010, 2027) returns HTTP 200 with no CM
        rows. Returning [] would mean "no holidays in 2010", i.e. ~250
        fabricated trading days, and doctor would then report every one
        of them as a missing ingest."""
        with pytest.raises(DataNotPublished, match="no CM holiday rows"):
            provider.parse_holidays(_artifact({"CBM": [{"tradingDate": "26-Jan-2010"}]}))

    def test_completely_empty_payload_raises(self, provider):
        with pytest.raises(DataNotPublished):
            provider.parse_holidays(_artifact({}))

    def test_unparseable_date_raises_parse_error(self, provider):
        payload = {EQUITY_SEGMENT: [{"tradingDate": "2026-01-26", "description": "Republic Day"}]}
        with pytest.raises(ParseError, match="unparseable holiday tradingDate"):
            provider.parse_holidays(_artifact(payload))

    def test_missing_date_raises_parse_error(self, provider):
        payload = {EQUITY_SEGMENT: [{"description": "Republic Day"}]}
        with pytest.raises(ParseError, match="no tradingDate"):
            provider.parse_holidays(_artifact(payload))

    def test_missing_description_gets_a_placeholder_not_a_crash(self, provider):
        payload = {EQUITY_SEGMENT: [{"tradingDate": "26-Jan-2026", "description": None}]}
        records = provider.parse_holidays(_artifact(payload))
        assert records[0].description == "Unspecified holiday"

    def test_non_object_payload_raises(self, provider):
        with pytest.raises(ParseError, match="expected a JSON object"):
            provider.parse_holidays(_artifact(b"[1, 2, 3]"))

    def test_default_segment_is_equities_not_the_first_json_key(self, provider):
        """CBM (corporate bond market) is the first key in NSE's payload
        and is emphatically not the equities calendar."""
        payload = {
            "CBM": [{"tradingDate": "15-Jan-2026", "description": "Bond-only holiday"}],
            "CM": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}],
        }
        records = provider.parse_holidays(_artifact(payload))
        assert [r.trading_date for r in records] == [date(2026, 1, 26)]


@pytest.mark.live
class TestLiveEndpoint:
    """Documented shape checks. Run deliberately: `pytest -m live`."""

    def test_current_year_is_reachable(self, provider):
        records = provider.fetch_holidays(date.today().year)
        assert records

    def test_history_reaches_2011(self, provider):
        """The finding that justified using this endpoint for the whole
        backfill range rather than only the current year."""
        records = provider.fetch_holidays(2011)
        assert records
        assert all(r.trading_date.year == 2011 for r in records)

    def test_out_of_range_year_is_a_silent_200_handled_as_not_published(self, provider):
        with pytest.raises(DataNotPublished):
            provider.fetch_holidays(2010)

"""Integration tests for ingest_corporate_actions: fetch -> parse -> upsert."""

from __future__ import annotations

import httpx
import pytest
import respx

from stk.core.errors import ParseError
from stk.ingest.corpactions import UnparsedCorporateActionsError, ingest_corporate_actions
from stk.store.db.engine import connect, migrate

URL = "https://www.nseindia.com/api/corporates-corporateActions"


def _row(symbol="TESTCO", isin="INE000A00000", subject="Bonus 1:1", ex_date="01-Jan-2026"):
    return {
        "symbol": symbol, "isin": isin, "exDate": ex_date, "recDate": ex_date,
        "bcStartDate": "-", "bcEndDate": "-", "subject": subject, "caBroadcastDate": None,
    }


class TestIngestCorporateActions:
    @respx.mock
    def test_parsed_action_upserted_with_factors(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        respx.get(URL).mock(return_value=httpx.Response(200, json=[_row()]))

        result = ingest_corporate_actions(sqlite_path=sqlite_path)

        assert result.fetched == 1
        assert result.upserted == 1
        assert result.unparsed == 0

        conn = connect(sqlite_path)
        try:
            row = conn.execute(
                "SELECT * FROM corporate_actions WHERE symbol='TESTCO'"
            ).fetchone()
        finally:
            conn.close()
        assert row["parse_status"] == "parsed"
        assert row["action_type"] == "BONUS"
        assert row["price_factor"] == pytest.approx(0.5)
        assert row["subject_raw"] == "Bonus 1:1"

    @respx.mock
    def test_unparsed_subject_raises_when_fail_on_unparsed_true(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json=[_row(subject="Something Unrecognisable Happened")]
            )
        )

        with pytest.raises(ParseError):
            ingest_corporate_actions(sqlite_path=sqlite_path, fail_on_unparsed=True)

        conn = connect(sqlite_path)
        try:
            job = conn.execute(
                "SELECT status, error_type FROM job_runs WHERE job_name='ingest_corporate_actions'"
            ).fetchone()
        finally:
            conn.close()
        assert job["status"] == "failed"
        assert job["error_type"] == "UnparsedCorporateActionsError"  # a ParseError subclass

    @respx.mock
    def test_one_unparsed_subject_never_hides_the_real_split_behind_it(self, tmp_path):
        """Regression, found on real data: the ingest used to raise on the FIRST unparsed
        subject, so every row after it -- including real splits -- was never stored. It must
        finish storing everything and only THEN fail, naming every offender."""
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        respx.get(URL).mock(return_value=httpx.Response(200, json=[
            _row(symbol="AAA", subject="Something Unrecognisable Happened"),
            _row(symbol="SPLITCO", isin="INE000B00000",
                 subject="Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- "
                         "Per Share"),
            _row(symbol="BBB", isin="INE000C00000", subject="Another Mystery"),
            _row(symbol="BONUSCO", isin="INE000D00000", subject="Bonus 1:1"),
        ]))

        with pytest.raises(UnparsedCorporateActionsError) as exc_info:
            ingest_corporate_actions(sqlite_path=sqlite_path, fail_on_unparsed=True)

        err = exc_info.value
        assert isinstance(err, ParseError)  # existing handlers still catch it
        assert {sym for sym, _ in err.unparsed} == {"AAA", "BBB"}  # ALL offenders, not just one
        assert err.result.upserted == 4 and err.result.unparsed == 2
        assert err.result.new_ex_dates  # the caller can still tell the price series is stale

        conn = connect(sqlite_path)
        try:
            stored = {r["symbol"]: r["parse_status"] for r in
                      conn.execute("SELECT symbol, parse_status FROM corporate_actions")}
        finally:
            conn.close()
        assert stored == {"AAA": "unparsed", "SPLITCO": "parsed", "BBB": "unparsed",
                          "BONUSCO": "parsed"}

    @respx.mock
    def test_unparsed_subject_recorded_when_fail_on_unparsed_false(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, json=[_row(subject="Something Unrecognisable Happened")]
            )
        )

        result = ingest_corporate_actions(sqlite_path=sqlite_path, fail_on_unparsed=False)

        assert result.unparsed == 1
        conn = connect(sqlite_path)
        try:
            row = conn.execute("SELECT parse_status FROM corporate_actions").fetchone()
        finally:
            conn.close()
        assert row["parse_status"] == "unparsed"

    @respx.mock
    def test_security_id_resolved_via_listings(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        conn = connect(sqlite_path)
        try:
            conn.execute(
                """INSERT INTO securities
                   (security_id, isin, canonical_symbol, company_name, primary_exchange,
                    status, first_seen_on, last_seen_on, updated_at)
                   VALUES (1, 'INE000A00000', 'TESTCO', 'Test Co', 'NSE',
                           'ACTIVE', '2020-01-01', '2026-01-01', '2026-01-01')"""
            )
            conn.execute(
                """INSERT INTO listings
                   (security_id, exchange, symbol, series, status, source, updated_at)
                   VALUES (1, 'NSE', 'TESTCO', 'EQ', 'ACTIVE', 'test', '2026-01-01')"""
            )
        finally:
            conn.close()

        respx.get(URL).mock(return_value=httpx.Response(200, json=[_row()]))
        ingest_corporate_actions(sqlite_path=sqlite_path)

        conn = connect(sqlite_path)
        try:
            row = conn.execute("SELECT security_id FROM corporate_actions").fetchone()
        finally:
            conn.close()
        assert row["security_id"] == 1

    @respx.mock
    def test_rerunning_is_idempotent(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        respx.get(URL).mock(return_value=httpx.Response(200, json=[_row()]))

        for _ in range(2):
            ingest_corporate_actions(sqlite_path=sqlite_path)

        conn = connect(sqlite_path)
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM corporate_actions").fetchone()["c"]
        finally:
            conn.close()
        assert count == 1  # same source_hash both times -- ON CONFLICT DO NOTHING

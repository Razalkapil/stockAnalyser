"""Integration tests for ingest_fundamentals_for_security."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from stk.ingest.fundamentals import ingest_fundamentals_for_security
from stk.providers.base import SecurityRef
from stk.store.db.engine import connect, migrate

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://www.nseindia.com/api/corporates-financial-results"
SECURITY = SecurityRef(isin="INE002A01018", symbol="RELIANCE", exchange="NSE")


def _insert_security(conn) -> None:
    conn.execute(
        """INSERT INTO securities
           (security_id, isin, canonical_symbol, company_name, primary_exchange,
            status, first_seen_on, last_seen_on, updated_at)
           VALUES (1, 'INE002A01018', 'RELIANCE', 'Reliance Industries Limited', 'NSE',
                   'ACTIVE', '2020-01-01', '2026-01-01', '2026-01-01')"""
    )


class TestIngestFundamentalsForSecurity:
    @respx.mock
    def test_snapshots_upserted_when_security_resolves(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        conn = connect(sqlite_path)
        try:
            _insert_security(conn)
        finally:
            conn.close()

        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        result = ingest_fundamentals_for_security(SECURITY, sqlite_path=sqlite_path)

        assert result.fetched == len(payload)
        assert result.upserted == len(payload)

        conn = connect(sqlite_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM fundamentals_snapshots"
            ).fetchone()["c"]
        finally:
            conn.close()
        assert count == len(payload)

    @respx.mock
    def test_unresolved_security_skipped_not_a_failure(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)  # no securities row inserted

        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        result = ingest_fundamentals_for_security(SECURITY, sqlite_path=sqlite_path)

        assert result.fetched == len(payload)
        assert result.upserted == 0

    @respx.mock
    def test_rerunning_is_idempotent(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        conn = connect(sqlite_path)
        try:
            _insert_security(conn)
        finally:
            conn.close()

        payload = json.loads(
            (FIXTURES / "nse" / "financial_results_reliance_trimmed.json").read_text()
        )
        respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

        for _ in range(2):
            ingest_fundamentals_for_security(SECURITY, sqlite_path=sqlite_path)

        conn = connect(sqlite_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM fundamentals_snapshots"
            ).fetchone()["c"]
        finally:
            conn.close()
        assert count == len(payload)  # not doubled

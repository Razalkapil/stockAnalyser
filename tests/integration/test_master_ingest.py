"""Integration tests for ingest_security_master's ISIN-keyed merge.

Mocks both providers' HTTP calls via respx and asserts against the
resulting securities/listings/symbol_history rows -- the merge logic
itself (ISIN dedup, NSE-preferred primary_exchange, rename detection)
is the thing worth testing here, not HTTP plumbing already covered by
the provider unit tests.
"""

from __future__ import annotations

import httpx
import respx

from stk.ingest.master import ingest_security_master
from stk.store.db.engine import connect, migrate

EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_MASTER_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)

_NSE_CSV_HEADER = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, "
    "MARKET LOT, ISIN NUMBER, FACE VALUE"
)


def _nse_row(symbol: str, isin: str, name: str = "Test Co", series: str = "EQ") -> str:
    return f"{symbol},{name},{series},01-JAN-2020,10,1,{isin},10"


def _bse_row(scrip_cd: str, isin: str, symbol: str, name: str = "Test Co Ltd") -> dict:
    return {
        "SCRIP_CD": scrip_cd, "Scrip_Name": name, "GROUP": "A", "FACE_VALUE": "10.00",
        "ISIN_NUMBER": isin, "scrip_id": symbol, "Issuer_Name": name,
    }


def _mock_nse(rows: list[str]) -> None:
    text = "\n".join([_NSE_CSV_HEADER, *rows]) + "\n"
    respx.get(EQUITY_L_URL).mock(
        return_value=httpx.Response(200, text=text, headers={"content-type": "text/csv"})
    )


def _mock_bse(rows: list[dict]) -> None:
    respx.get(BSE_MASTER_URL).mock(return_value=httpx.Response(200, json=rows))


class TestIngestSecurityMaster:
    @respx.mock
    def test_nse_and_bse_same_isin_merge_into_one_security(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        _mock_nse([_nse_row("RELIANCE", "INE002A01018")])
        _mock_bse([_bse_row("500325", "INE002A01018", "RIL")])

        result = ingest_security_master(sqlite_path=sqlite_path)

        assert result.securities_upserted == 1
        assert result.listings_upserted == 2

        conn = connect(sqlite_path)
        try:
            sec = conn.execute("SELECT * FROM securities WHERE isin='INE002A01018'").fetchone()
            listings = conn.execute(
                "SELECT exchange, symbol FROM listings WHERE security_id=? ORDER BY exchange",
                (sec["security_id"],),
            ).fetchall()
        finally:
            conn.close()

        assert sec["primary_exchange"] == "NSE"  # NSE preferred when both exist
        assert sec["canonical_symbol"] == "RELIANCE"
        assert {(r["exchange"], r["symbol"]) for r in listings} == {
            ("NSE", "RELIANCE"), ("BSE", "RIL"),
        }

    @respx.mock
    def test_bse_only_isin_uses_bse_as_primary(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        _mock_nse([])
        _mock_bse([_bse_row("500001", "INE001B02020", "BSEONLY")])

        ingest_security_master(sqlite_path=sqlite_path)

        conn = connect(sqlite_path)
        try:
            sec = conn.execute("SELECT * FROM securities WHERE isin='INE001B02020'").fetchone()
        finally:
            conn.close()
        assert sec["primary_exchange"] == "BSE"
        assert sec["canonical_symbol"] == "BSEONLY"

    @respx.mock
    def test_rerunning_is_idempotent(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)
        _mock_nse([_nse_row("RELIANCE", "INE002A01018")])
        _mock_bse([_bse_row("500325", "INE002A01018", "RIL")])

        for _ in range(2):
            ingest_security_master(sqlite_path=sqlite_path)

        conn = connect(sqlite_path)
        try:
            sec_count = conn.execute("SELECT COUNT(*) AS c FROM securities").fetchone()["c"]
            listing_count = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
            history_count = conn.execute("SELECT COUNT(*) AS c FROM symbol_history").fetchone()["c"]
        finally:
            conn.close()
        assert sec_count == 1
        assert listing_count == 2
        assert history_count == 2  # one per (exchange, symbol), not doubled on re-run

    @respx.mock
    def test_symbol_rename_tracked_in_symbol_history(self, tmp_path):
        sqlite_path = tmp_path / "app.db"
        migrate(sqlite_path)

        _mock_nse([_nse_row("OLDNAME", "INE003C03030")])
        _mock_bse([])
        ingest_security_master(sqlite_path=sqlite_path)

        respx.reset()
        _mock_nse([_nse_row("NEWNAME", "INE003C03030")])
        _mock_bse([])
        result = ingest_security_master(sqlite_path=sqlite_path)

        assert result.renames == 1

        conn = connect(sqlite_path)
        try:
            active = conn.execute(
                "SELECT symbol, status FROM listings WHERE exchange='NSE' ORDER BY symbol"
            ).fetchall()
            history = conn.execute(
                "SELECT symbol, valid_to FROM symbol_history WHERE exchange='NSE' ORDER BY symbol"
            ).fetchall()
        finally:
            conn.close()

        assert {(r["symbol"], r["status"]) for r in active} == {
            ("OLDNAME", "INACTIVE"), ("NEWNAME", "ACTIVE"),
        }
        old_row = next(r for r in history if r["symbol"] == "OLDNAME")
        new_row = next(r for r in history if r["symbol"] == "NEWNAME")
        assert old_row["valid_to"] is not None
        assert new_row["valid_to"] is None

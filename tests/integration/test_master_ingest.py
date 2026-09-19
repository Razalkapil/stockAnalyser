"""Integration tests for ingest_security_master's ISIN-keyed merge.

Mocks both providers' HTTP calls via respx and asserts against the
resulting securities/listings/symbol_history rows -- the merge logic
itself (ISIN dedup, NSE-preferred primary_exchange, rename detection)
is the thing worth testing here, not HTTP plumbing already covered by
the provider unit tests.
"""

from __future__ import annotations

import contextlib

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


# --- suspension / delisting from absence across snapshots --------------------------------------

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

from stk.config.universe import LifecycleConfig  # noqa: E402
from stk.core.errors import ProviderError  # noqa: E402
from stk.domain.universe import lifecycle_status  # noqa: E402

CFG = LifecycleConfig(suspend_after_missed=1, delist_after_missed=3, max_absent_fraction=0.5)
D0 = date(2026, 1, 5)


class TestLifecycleRule:
    @pytest.mark.parametrize(("missed", "expected"), [
        (0, "ACTIVE"), (1, "SUSPENDED"), (2, "SUSPENDED"), (3, "DELISTED"), (50, "DELISTED")])
    def test_thresholds(self, missed, expected):
        assert lifecycle_status(missed, suspend_after=1, delist_after=3) == expected

    def test_inverted_thresholds_are_refused(self):
        with pytest.raises(ValueError):
            lifecycle_status(1, suspend_after=5, delist_after=2)


def _isin(name: str) -> str:
    """A stable ISIN per symbol number: dropping a name must not re-label the others."""
    n = 0 if name in ("OLD", "NEW") else int(name[1:])
    return f"INE{n:03d}A01010"


def snap(names: list[str], *, bse: list[tuple[str, str, str]] | None = None) -> None:
    """One master snapshot: NSE symbols A0..; BSE rows are (scrip, isin, symbol)."""
    respx.reset()
    _mock_nse([_nse_row(n, _isin(n)) for n in names])
    _mock_bse([_bse_row(*b) for b in (bse or [])])


def run(db, day, cfg=CFG):
    return ingest_security_master(sqlite_path=db, lifecycle=cfg, today=day)


def status_of(db, symbol):
    conn = connect(db)
    r = conn.execute(
        "SELECT s.status, l.missed_snapshots FROM securities s JOIN listings l "
        "ON l.security_id=s.security_id WHERE l.symbol=?", (symbol,)).fetchone()
    conn.close()
    return (r["status"], r["missed_snapshots"])


UNIVERSE = [f"S{i}" for i in range(10)]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "app.db"
    migrate(p)
    return p


class TestLifecycle:
    @respx.mock
    def test_absent_once_is_suspended_then_delisted_and_back_when_it_returns(self, db):
        snap(UNIVERSE)
        run(db, D0)
        assert status_of(db, "S3") == ("ACTIVE", 0)

        gone = [s for s in UNIVERSE if s != "S3"]
        snap(gone)
        r = run(db, D0 + timedelta(days=7))
        assert status_of(db, "S3") == ("SUSPENDED", 1) and r.suspended == 1 and r.delisted == 0

        run_days = [D0 + timedelta(days=14), D0 + timedelta(days=21)]
        r = run(db, run_days[0])
        assert status_of(db, "S3") == ("SUSPENDED", 2)
        r = run(db, run_days[1])
        assert status_of(db, "S3") == ("DELISTED", 3) and r.delisted == 1

        snap(UNIVERSE)  # it comes back
        run(db, D0 + timedelta(days=28))
        assert status_of(db, "S3") == ("ACTIVE", 0)
        assert status_of(db, "S4") == ("ACTIVE", 0)  # never touched

    @respx.mock
    def test_rerunning_the_same_day_never_counts_an_absence_twice(self, db):
        snap(UNIVERSE)
        run(db, D0)
        snap([s for s in UNIVERSE if s != "S3"])
        for _ in range(4):
            run(db, D0 + timedelta(days=7))
        assert status_of(db, "S3") == ("SUSPENDED", 1)

    @respx.mock
    def test_a_security_still_listed_on_the_other_exchange_is_not_gone(self, db):
        both = [("500001", "INE000A01010", "B0")]
        snap(UNIVERSE, bse=both)  # S0 has ISIN INE000A01010 too: listed on NSE AND BSE
        run(db, D0)
        snap([s for s in UNIVERSE if s != "S0"], bse=both)  # gone from NSE only
        run(db, D0 + timedelta(days=7))
        assert status_of(db, "S0") == ("ACTIVE", 1)  # NSE listing missed, BSE listing present
        conn = connect(db)
        assert conn.execute("SELECT status FROM securities WHERE isin='INE000A01010'"
                            ).fetchone()["status"] == "ACTIVE"

    @respx.mock
    def test_an_exchange_whose_fetch_failed_is_not_counted(self, db):
        snap(UNIVERSE, bse=[("500001", "INE900A01010", "BONLY")])
        run(db, D0)
        respx.reset()
        respx.get(EQUITY_L_URL).mock(return_value=httpx.Response(503))  # NSE down
        _mock_bse([_bse_row("500001", "INE900A01010", "BONLY")])
        with contextlib.suppress(ProviderError):
            run(db, D0 + timedelta(days=7))
        for s in UNIVERSE:
            assert status_of(db, s) == ("ACTIVE", 0), s  # an outage is not a delisting

    @respx.mock
    def test_a_snapshot_missing_most_listings_is_treated_as_broken(self, db):
        snap(UNIVERSE)
        run(db, D0)
        snap(UNIVERSE[:2])  # 8 of 10 vanished: a truncated file, not 8 delistings
        r = run(db, D0 + timedelta(days=7), LifecycleConfig(
            suspend_after_missed=1, delist_after_missed=3, max_absent_fraction=0.5))
        assert r.degraded and r.suspended == 0 and r.delisted == 0
        for s in UNIVERSE:
            assert status_of(db, s) == ("ACTIVE", 0), s
        conn = connect(db)
        row = conn.execute("SELECT status, metrics_json FROM job_runs "
                           "WHERE job_name='ingest_security_master' ORDER BY run_id DESC"
                           ).fetchone()
        assert row["status"] == "degraded" and "snapshot_looked_broken" in row["metrics_json"]

    @respx.mock
    def test_a_renamed_listing_is_not_mistaken_for_a_delisting(self, db):
        snap(["OLD", *UNIVERSE[1:]])
        run(db, D0)
        snap(["NEW", *UNIVERSE[1:]])  # same ISIN INE000A01010, new symbol
        r = run(db, D0 + timedelta(days=7))
        assert r.renames == 1
        conn = connect(db)
        assert conn.execute("SELECT status FROM securities WHERE isin='INE000A01010'"
                            ).fetchone()["status"] == "ACTIVE"

    def test_the_committed_thresholds_are_sane(self):
        from stk.config.universe import load_universe_config  # noqa: PLC0415

        c = load_universe_config().lifecycle
        assert 1 <= c.suspend_after_missed <= c.delist_after_missed
        assert 0 < c.max_absent_fraction < 0.5

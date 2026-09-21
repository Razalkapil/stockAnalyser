"""NSE symbol-change history -> symbol_history.

The fixture is a trimmed copy of the real symbolchange.csv (fetched 2026-09-19): no header row,
a blank company name, a name with a leading space, and the TELCO -> TATAMOTORS -> TMPV chain.
Without this, a rename older than the first master snapshot was invisible: UNOMINDA's 2022 bonus
never reached the MINDAIND bars, a phantom 49% crash in the adjusted series.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from stk.core.errors import ParseError
from stk.ingest.instruments import fund_symbols, inherit_classes_from_renames
from stk.ingest.master import UNKNOWN_START, apply_symbol_changes
from stk.providers.base import RawArtifact, SymbolChange
from stk.providers.nse.master import NseSecurityMasterProvider
from stk.store.db.engine import connect, migrate

FIXTURE = Path(__file__).parents[1] / "fixtures" / "nse" / "symbolchange_trimmed.csv"


def _artifact(content: bytes) -> RawArtifact:
    return RawArtifact(source="nse_symbolchange", business_date=date(2026, 9, 19), url="u",
                       content=content, content_type="text/csv", http_status=200,
                       fetched_at=datetime.now(UTC))


def _parse(content: bytes) -> list[SymbolChange]:
    return NseSecurityMasterProvider().parse_symbol_changes(_artifact(content))


class TestParse:
    def test_the_real_file_parses(self):
        changes = _parse(FIXTURE.read_bytes())
        assert len(changes) == 10
        mindaind = next(c for c in changes if c.old_symbol == "MINDAIND")
        assert (mindaind.new_symbol, mindaind.effective_date) == ("UNOMINDA", date(2022, 8, 5))
        assert mindaind.company_name == "UNO Minda Limited"
        assert next(c for c in changes if c.old_symbol == "780LTFL30").company_name is None

    @pytest.mark.parametrize("content", [
        b"<!DOCTYPE html><html>",  # an HTML shell
        b"Name,OLD,NEW\n",  # a column dropped
        b"Name,OLD,NEW,2022-08-05\n",  # a date format change
        b"Name,,NEW,05-AUG-2022\n",
        b"\n",
    ])
    def test_an_unexpected_shape_fails_loudly(self, content):
        with pytest.raises(ParseError):
            _parse(content)


@pytest.fixture
def conn(tmp_path):
    sqlite_path = tmp_path / "app.db"
    migrate(sqlite_path)
    c = connect(sqlite_path)
    for sid, symbol in ((1, "UNOMINDA"), (2, "TMPV"), (3, "DTIL"), (4, "DPTL")):
        c.execute(
            "INSERT INTO securities (security_id, isin, canonical_symbol, company_name, "
            "primary_exchange, status, first_seen_on, last_seen_on, updated_at) "
            "VALUES (?, ?, ?, 'x', 'NSE', 'ACTIVE', '2026-09-18', '2026-09-18', '2026-09-18')",
            (sid, f"INE{sid:09d}", symbol),
        )
        c.execute(
            "INSERT INTO listings (security_id, exchange, symbol, series, status, source, "
            "updated_at) VALUES (?, 'NSE', ?, 'EQ', 'ACTIVE', 'test', '2026-09-18')",
            (sid, symbol),
        )
    yield c
    c.close()


def _history(conn, symbol):
    return conn.execute(
        "SELECT security_id, valid_from, valid_to FROM symbol_history "
        "WHERE exchange='NSE' AND symbol=?", (symbol,),
    ).fetchall()


class TestApply:
    def test_an_old_symbol_is_linked_to_the_new_symbols_security(self, conn):
        result = apply_symbol_changes(conn, _parse(FIXTURE.read_bytes()))

        (row,) = _history(conn, "MINDAIND")
        assert (row["security_id"], row["valid_from"], row["valid_to"]) == (
            1, UNKNOWN_START, "2022-08-05")
        assert result.inserted >= 1

    def test_a_chain_resolves_in_one_pass(self, conn):
        apply_symbol_changes(conn, _parse(FIXTURE.read_bytes()))

        (tatamotors,) = _history(conn, "TATAMOTORS")
        assert (tatamotors["security_id"], tatamotors["valid_from"], tatamotors["valid_to"]) == (
            2, "2003-12-26", "2025-10-24")  # it BECAME TATAMOTORS on the TELCO change
        (telco,) = _history(conn, "TELCO")
        assert (telco["security_id"], telco["valid_to"]) == (2, "2003-12-26")

    def test_a_reused_old_symbol_is_never_linked(self, conn):
        """DTIL became DPTL in 2010, and DTIL is now another company's symbol. Linking it would
        apply DPTL's corporate actions to that other company's bars."""
        result = apply_symbol_changes(conn, _parse(FIXTURE.read_bytes()))

        assert result.conflicts == ["DTIL"]
        assert [r["security_id"] for r in _history(conn, "DTIL")] == []

    def test_changes_for_securities_no_longer_listed_are_counted_not_failed(self, conn):
        result = apply_symbol_changes(conn, _parse(FIXTURE.read_bytes()))
        assert result.unresolved > 0  # e.g. ZYDUSLIFE is not in this test's master

    def test_rerunning_is_idempotent(self, conn):
        changes = _parse(FIXTURE.read_bytes())
        first = apply_symbol_changes(conn, changes)
        second = apply_symbol_changes(conn, changes)

        assert second.inserted == 0
        assert second.already_known == first.inserted
        assert len(_history(conn, "MINDAIND")) == 1


@pytest.mark.live
def test_live_symbolchange_csv_still_has_its_documented_shape():
    provider = NseSecurityMasterProvider()
    changes = provider.parse_symbol_changes(provider.fetch_symbol_changes_artifact())
    assert len(changes) > 1000
    assert any(c.old_symbol == "MINDAIND" and c.new_symbol == "UNOMINDA" for c in changes)


class TestClassInheritance:
    def _classify(self, conn, symbol, cls):
        conn.execute("INSERT INTO instrument_class (exchange, symbol, isin, class, source_date, "
                     "updated_at) VALUES ('NSE', ?, 'INF1', ?, '2026-09-18', 'x')", (symbol, cls))

    def test_an_old_etf_symbol_becomes_a_fund(self, conn):
        """ICICI500 -> BSE500IETF: the old symbol traded as a 'stock' in backtests until 2024."""
        self._classify(conn, "BSE500IETF", "fund")
        changes = [SymbolChange(exchange="NSE", old_symbol="ICICI500", new_symbol="BSE500IETF",
                                effective_date=date(2024, 1, 1))]
        assert inherit_classes_from_renames(conn, changes, now="t") == 1
        assert fund_symbols(conn, "NSE") == {"BSE500IETF", "ICICI500"}

    def test_a_chain_reaches_todays_class(self, conn):
        self._classify(conn, "C", "fund")
        changes = [
            SymbolChange(exchange="NSE", old_symbol="A", new_symbol="B",
                         effective_date=date(2020, 1, 1)),
            SymbolChange(exchange="NSE", old_symbol="B", new_symbol="C",
                         effective_date=date(2023, 1, 1)),
        ]
        assert inherit_classes_from_renames(conn, changes, now="t") == 2
        assert fund_symbols(conn, "NSE") == {"A", "B", "C"}

    def test_an_existing_class_is_never_overwritten(self, conn):
        """A reused symbol already carries the class of what trades under it today."""
        self._classify(conn, "NEWETF", "fund")
        self._classify(conn, "OLDSYM", "equity")
        changes = [SymbolChange(exchange="NSE", old_symbol="OLDSYM", new_symbol="NEWETF",
                                effective_date=date(2024, 1, 1))]
        assert inherit_classes_from_renames(conn, changes, now="t") == 0
        assert "OLDSYM" not in fund_symbols(conn, "NSE")

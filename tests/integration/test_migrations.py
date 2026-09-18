"""Integration tests for the SQLite migration runner."""

from __future__ import annotations

import sqlite3

from stk.store.db.engine import connect, migrate

CA_INSERT_SQL = """
    INSERT INTO corporate_actions
        (symbol, exchange, subject_raw, parse_status, parser_version,
         source, source_hash, captured_at)
    VALUES
        (:symbol, :exchange, :subject_raw, :parse_status, :parser_version,
         :source, :source_hash, :captured_at)
"""

SECURITY_INSERT_SQL = """
    INSERT INTO securities
        (isin, canonical_symbol, company_name, primary_exchange,
         status, first_seen_on, last_seen_on, updated_at)
    VALUES (?,?,?,?,?,?,?,?)
"""


class TestMigrate:
    def test_creates_all_phase1_tables(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            tables = {
                r["name"]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        expected = {
            "securities",
            "listings",
            "symbol_history",
            "corporate_actions",
            "fundamentals_snapshots",
            "job_runs",
            "raw_artifacts",
            "trading_calendar",
            "universe_current",
            "schema_migrations",
        }
        assert expected.issubset(tables)

    def test_records_applied_migration(self, tmp_db_path):
        applied = migrate(tmp_db_path)
        assert "init" in applied

    def test_is_idempotent_second_call_applies_nothing(self, tmp_db_path):
        migrate(tmp_db_path)
        second = migrate(tmp_db_path)
        assert second == []

    def test_wal_mode_enabled(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode.lower() == "wal"

    def test_foreign_keys_enabled(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        finally:
            conn.close()
        assert fk == 1

    def test_insert_and_query_security(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            conn.execute(
                SECURITY_INSERT_SQL,
                (
                    "INE009A01021", "INFY", "Infosys Ltd", "NSE", "ACTIVE",
                    "2010-01-01", "2026-09-17", "2026-09-17",
                ),
            )
            row = conn.execute(
                "SELECT * FROM securities WHERE isin=?", ("INE009A01021",)
            ).fetchone()
        finally:
            conn.close()
        assert row["canonical_symbol"] == "INFY"

    def test_invalid_status_rejected_by_check_constraint(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            raised = False
            try:
                conn.execute(
                    SECURITY_INSERT_SQL,
                    ("X", "X", "X", "NSE", "NOT_A_REAL_STATUS",
                     "2010-01-01", "2026-09-17", "2026-09-17"),
                )
            except sqlite3.IntegrityError:
                raised = True
        finally:
            conn.close()
        assert raised

    def test_corporate_actions_unique_source_hash_prevents_duplicate_insert(self, tmp_db_path):
        """This UNIQUE constraint is the idempotency backbone for the CA table."""
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        try:
            row = {
                "symbol": "INFY", "exchange": "NSE", "subject_raw": "Bonus 1:1",
                "parse_status": "parsed", "parser_version": 1,
                "source": "nse_corp_actions", "source_hash": "abc123",
                "captured_at": "2026-09-17T00:00:00",
            }
            conn.execute(CA_INSERT_SQL, row)
            raised = False
            try:
                conn.execute(CA_INSERT_SQL, row)
            except sqlite3.IntegrityError:
                raised = True
        finally:
            conn.close()
        assert raised

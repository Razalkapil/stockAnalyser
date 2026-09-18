"""SQLite connection factory, pragmas, and the forward-only migration runner.

No Alembic: the schema is small and a future Postgres swap is easier
with hand-written, understood SQL than with generated migration diffs.
Migrations are plain numbered .sql files in migrations/, applied in
order, tracked in schema_migrations.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from stk.core.errors import ConfigError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the app's standard pragmas applied."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; callers use explicit tx
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction context manager (conn is opened in autocommit mode)."""
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _discover_migrations() -> list[tuple[int, str, Path]]:
    """Return (sequence_number, name, path) for every migrations/*.sql file, sorted."""
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        stem = path.stem  # e.g. "0001_init"
        seq_str, _, name = stem.partition("_")
        if not seq_str.isdigit():
            raise ConfigError(f"migration file {path.name} does not start with a numeric sequence")
        migrations.append((int(seq_str), name, path))
    return migrations


def migrate(db_path: Path) -> list[str]:
    """Apply all pending migrations in order. Returns the names applied."""
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  sequence INTEGER PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        applied_seqs = {
            row["sequence"] for row in conn.execute("SELECT sequence FROM schema_migrations")
        }

        applied_names = []
        for seq, name, path in _discover_migrations():
            if seq in applied_seqs:
                continue
            sql = path.read_text()
            # executescript() issues its own implicit COMMIT/BEGIN around
            # DDL in the underlying SQLite driver, so it cannot be nested
            # inside our explicit transaction() helper -- run it directly,
            # then record the migration in its own small transaction.
            conn.executescript(sql)
            with transaction(conn):
                conn.execute(
                    "INSERT INTO schema_migrations (sequence, name) VALUES (?, ?)",
                    (seq, name),
                )
            applied_names.append(name)

        return applied_names
    finally:
        conn.close()

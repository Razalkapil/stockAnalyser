"""SQLite connection factory, pragmas, and the forward-only migration runner.

No Alembic: the schema is small and a future Postgres swap is easier
with hand-written, understood SQL than with generated migration diffs.
Migrations are plain numbered .sql files in migrations/, applied in
order, tracked in schema_migrations.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from stk.core.errors import ConfigError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_savepoint_ids = itertools.count(1)

_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
)


def connect(db_path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection with the app's standard pragmas applied.

    `check_same_thread=False` is for a caller that hands ONE connection between threads strictly
    one at a time (the API's per-request dependency); it does not make concurrent use safe.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # autocommit; callers use explicit tx
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction context manager (conn is opened in autocommit mode).

    NESTS: called while a transaction is already open (a helper that is itself transactional,
    used inside a larger atomic operation) it becomes a SAVEPOINT, so the inner block rolls back
    on its own error and the outer transaction still decides the whole. Without this, composing
    two individually-transactional operations raised "cannot start a transaction within a
    transaction".
    """
    if conn.in_transaction:
        name = f"sp_{next(_savepoint_ids)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except Exception:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
        return

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

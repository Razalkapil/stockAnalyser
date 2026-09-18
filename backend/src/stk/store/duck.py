"""DuckDB connection factory, view registration, and named-SQL access.

This is the ONLY way anything outside store/ reads the parquet lake.
The build plan's rule: "every adjusted-price consumer goes through
store/queries/prices.sql -- never opens a parquet path directly." A
consumer that globs its own parquet paths silently stops seeing new
datasets, misses the securities-master join, and has to re-derive the
hive-partitioning arguments correctly every time.

Two things here are less obvious than they look:

1. **Missing datasets register as EMPTY TYPED VIEWS, not errors.** A
   fresh checkout has no bars_daily_adjusted yet; a BSE-only install
   has no NSE partitions. "No data yet" is a normal early-pipeline
   state, so the view exists with the right columns and zero rows,
   and a query against it returns nothing instead of blowing up. This
   matches the empty-glob branch already in ingest.liquidity.

2. **Dimension attach has two modes, and which one ran is reported.**
   DuckDB's sqlite_scanner is not bundled; `ATTACH ... (TYPE SQLITE)`
   downloads it from extensions.duckdb.org on first use. That breaks
   offline development and would put a network fetch inside CI, so
   when the extension is unavailable we read the three dimension
   tables through Python's sqlite3 and register them as Arrow tables
   instead. Both modes are read-only views over the same file and
   return the same rows -- but the mode is logged and surfaced by
   `stk doctor`, because "which engine read my dimensions" is exactly
   the kind of thing you want to know when a join behaves oddly.

The connection is in-memory. The build plan mentions a disposable
data/duck.db; it is an optimisation for view-definition reuse that
buys nothing while every process registers its views in milliseconds,
so it is deliberately not implemented yet.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import structlog

from stk.core.errors import ConfigError
from stk.store.parquet.schema import (
    BARS_DAILY_ADJUSTED_SCHEMA,
    BARS_DAILY_SCHEMA,
    INDICES_DAILY_SCHEMA,
    LIQUIDITY_DAILY_SCHEMA,
)

log = structlog.get_logger(__name__)

_QUERY_PACKAGE = "stk.store.queries"

# Dataset name -> (path glob relative to parquet_root, Arrow schema used
# for the empty-view fallback).
_DATASETS: dict[str, tuple[str, pa.Schema]] = {
    "bars_daily": ("bars_daily/exchange=*/year=*/data.parquet", BARS_DAILY_SCHEMA),
    "bars_daily_adjusted": (
        "bars_daily_adjusted/exchange=*/year=*/data.parquet",
        BARS_DAILY_ADJUSTED_SCHEMA,
    ),
    "liquidity_daily": (
        "features/liquidity_daily/exchange=*/year=*/data.parquet",
        LIQUIDITY_DAILY_SCHEMA,
    ),
    # No exchange level: NSE's index archive only, BSE is a documented
    # gap (docs/data-sources.md).
    "indices_daily": ("indices_daily/year=*/data.parquet", INDICES_DAILY_SCHEMA),
}

_DIMENSION_TABLES = ("securities", "listings", "symbol_history")


class DimensionMode(StrEnum):
    """How SQLite dimensions were made visible to DuckDB."""

    SQLITE_SCANNER = "sqlite_scanner"
    ARROW_COPY = "arrow_copy"
    NONE = "none"


def _register_one_view(
    con: duckdb.DuckDBPyConnection, parquet_root: Path, name: str, glob: str, schema: pa.Schema
) -> None:
    pattern = str(parquet_root / glob)
    if not list(parquet_root.glob(glob)):
        # Empty typed view: the dataset has not been ingested yet. See
        # this module's docstring -- this is a normal state, not an error.
        empty = schema.empty_table()
        con.register(f"_empty_{name}", empty)
        con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM "_empty_{name}"')
        return
    # The glob is inlined rather than bound: DuckDB cannot prepare a
    # CREATE VIEW whose source is a parameter. Single quotes are escaped
    # by doubling, which is all a filesystem path can contain that would
    # break out of the literal.
    escaped = pattern.replace("'", "''")
    con.execute(
        f'CREATE OR REPLACE VIEW "{name}" AS '
        f"SELECT * FROM read_parquet('{escaped}', hive_partitioning := true)"
    )


def register_views(con: duckdb.DuckDBPyConnection, parquet_root: Path) -> None:
    """Register one view per parquet dataset over ``parquet_root``."""
    for name, (glob, schema) in _DATASETS.items():
        _register_one_view(con, parquet_root, name, glob, schema)


def _attach_via_arrow(con: duckdb.DuckDBPyConnection, sqlite_path: Path) -> None:
    """Read the dimension tables through sqlite3 and register them as
    Arrow tables. Equivalent, read-only, and needs no extension."""
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table in _DIMENSION_TABLES:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
            if rows:
                arrow = pa.Table.from_pylist(rows)
            else:
                # An empty dimension table still needs its COLUMNS, or
                # every join against it fails with a binder error rather
                # than simply matching nothing. A not-yet-ingested
                # securities master is a normal state (see
                # ingest.liquidity's known-limitation docstring), so
                # build the empty table from the real column list.
                columns = [
                    str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
                ]
                arrow = pa.table({name: pa.array([], type=pa.string()) for name in columns})
            con.register(f"_arrow_dim_{table}", arrow)
            con.execute(
                f'CREATE OR REPLACE VIEW "dim_{table}" AS SELECT * FROM "_arrow_dim_{table}"'
            )
    finally:
        conn.close()


def attach_dimensions(
    con: duckdb.DuckDBPyConnection, sqlite_path: Path, *, allow_extension: bool = True
) -> DimensionMode:
    """Expose securities/listings/symbol_history as dim_* views, READ ONLY.

    Returns which mode was used. ``allow_extension=False`` forces the
    Arrow path -- tests and CI use it so that no run can reach the
    network for an extension download.
    """
    if not sqlite_path.exists():
        raise ConfigError(
            f"cannot attach dimensions: {sqlite_path} does not exist "
            "(run `stk db migrate` first)"
        )

    if allow_extension:
        try:
            con.execute("INSTALL sqlite")
            con.execute("LOAD sqlite")
            con.execute(f"ATTACH '{sqlite_path}' AS dim_db (TYPE SQLITE, READ_ONLY)")
            for table in _DIMENSION_TABLES:
                con.execute(
                    f'CREATE OR REPLACE VIEW "dim_{table}" AS SELECT * FROM dim_db."{table}"'
                )
            log.info("duck.dimensions_attached", mode=DimensionMode.SQLITE_SCANNER.value)
            return DimensionMode.SQLITE_SCANNER
        except (duckdb.IOException, duckdb.CatalogException, duckdb.Error) as exc:
            log.info(
                "duck.sqlite_scanner_unavailable",
                error=str(exc),
                falling_back_to=DimensionMode.ARROW_COPY.value,
            )

    _attach_via_arrow(con, sqlite_path)
    log.info("duck.dimensions_attached", mode=DimensionMode.ARROW_COPY.value)
    return DimensionMode.ARROW_COPY


class DuckSession:
    """A DuckDB connection plus the metadata a caller may need about it."""

    def __init__(self, con: duckdb.DuckDBPyConnection, dimension_mode: DimensionMode) -> None:
        self.con = con
        self.dimension_mode = dimension_mode

    def sql(
        self, query_name: str, params: Sequence[Any] | None = None
    ) -> duckdb.DuckDBPyConnection:
        return run_query(self.con, query_name, params)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> DuckSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def connect(
    parquet_root: Path,
    sqlite_path: Path | None = None,
    *,
    allow_extension: bool = True,
) -> DuckSession:
    """Open an in-memory DuckDB session with views (and dimensions) registered."""
    con = duckdb.connect(":memory:")
    register_views(con, parquet_root)
    mode = DimensionMode.NONE
    if sqlite_path is not None:
        mode = attach_dimensions(con, sqlite_path, allow_extension=allow_extension)
    return DuckSession(con, mode)


def _load_named_queries() -> dict[str, str]:
    """Parse every store/queries/*.sql into {name: sql}, split on `-- name:` headers."""
    queries: dict[str, str] = {}
    for entry in resources.files(_QUERY_PACKAGE).iterdir():
        if not entry.name.endswith(".sql"):
            continue
        current: str | None = None
        buffer: list[str] = []
        for line in entry.read_text().splitlines():
            if line.startswith("-- name:"):
                if current is not None:
                    queries[current] = "\n".join(buffer).strip()
                current = line.removeprefix("-- name:").strip()
                buffer = []
                continue
            if current is not None:
                buffer.append(line)
        if current is not None:
            queries[current] = "\n".join(buffer).strip()
    return queries


_QUERY_CACHE: dict[str, str] | None = None


def named_query(name: str) -> str:
    """The SQL text registered under ``name``, or a loud KeyError."""
    global _QUERY_CACHE  # noqa: PLW0603 -- read-only, process-wide memoisation
    if _QUERY_CACHE is None:
        _QUERY_CACHE = _load_named_queries()
    if name not in _QUERY_CACHE:
        raise KeyError(
            f"no named query {name!r} in {_QUERY_PACKAGE}; "
            f"known queries: {sorted(_QUERY_CACHE)}"
        )
    return _QUERY_CACHE[name]


def run_query(
    con: duckdb.DuckDBPyConnection, name: str, params: Sequence[Any] | None = None
) -> duckdb.DuckDBPyConnection:
    """Execute a named query from store/queries/ with positional params.

    Returns the connection, so callers chain .fetchall()/.arrow() as
    they would on a raw execute().
    """
    return con.execute(named_query(name), list(params) if params else None)

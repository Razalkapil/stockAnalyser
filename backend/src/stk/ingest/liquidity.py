"""Liquidity feature computation and the tradeable-universe snapshot.

Reads already-ingested bars_daily parquet (never re-fetches anything --
this is a pure derived-feature step, like bars_daily_adjusted), computes
per-symbol trailing-window liquidity metrics with DuckDB, and writes two
things:

  1. features/liquidity_daily/exchange=.../year=.../data.parquet -- one
     row per (exchange, symbol, date), fully rebuildable, matching
     LIQUIDITY_DAILY_SCHEMA. Written via the same overwrite-by-partition
     upsert_partition used by bars_daily, keyed on `date`.
  2. SQLite `universe_current` -- truncate-and-replace for the given
     as_of_date, joined against `listings`/`securities` to resolve each
     symbol's security_id (see ingest.master, once it lands, for how
     that table gets populated).

The domain.universe.is_liquid RULE itself lives in domain/universe.py
as a pure function -- this module's job is only to gather the metrics
that rule needs and apply it, not to encode the thresholds itself.

KNOWN LIMITATION: until a SecurityMasterProvider has populated
`securities`/`listings` (a separate, not-yet-landed ingest step), no
symbol resolves to a security_id, so step 2 above upserts nothing --
`universe_current` stays empty. Step 1 (the parquet features) is
unaffected, since it is keyed by (exchange, symbol, date), not
security_id. This is a deliberate, load-bearing ordering: the parquet
feature build must not silently wait on or fail because of an
unrelated ingest step.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from glob import glob as glob_files
from pathlib import Path

import duckdb
import pyarrow as pa

from stk.config.universe import UniverseConfig
from stk.domain.universe import LiquidityMetrics, LiquidityThresholds, is_liquid
from stk.store.parquet.layout import bars_daily_partition, liquidity_daily_partition
from stk.store.parquet.schema import LIQUIDITY_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition


class LiquidityResult:
    def __init__(
        self, as_of_date: date, exchange: str, symbols_evaluated: int, symbols_liquid: int
    ) -> None:
        self.as_of_date = as_of_date
        self.exchange = exchange
        self.symbols_evaluated = symbols_evaluated
        self.symbols_liquid = symbols_liquid


def _bars_glob(parquet_root: Path, exchange: str) -> str:
    """A glob over every year partition ingested so far for one exchange.

    Deliberately not narrowed to a couple of recent years -- listed_days
    needs the symbol's FULL history, and the whole dataset is small
    (~150-200MB for 15 years, per docs/BUILD_PLAN.md's own sizing), so
    scanning it all is cheap relative to correctness.
    """
    exchange_dir = bars_daily_partition(parquet_root, exchange, 0).parent.parent
    return str(exchange_dir / "year=*" / "data.parquet")


def compute_liquidity_metrics(
    parquet_root: Path,
    *,
    exchange: str,
    as_of_date: date,
    lookback_days: int,
) -> pa.Table:
    """Compute one row per symbol with a bar on or before as_of_date,
    matching LIQUIDITY_DAILY_SCHEMA (is_liquid filled in by the caller
    after applying domain.universe.is_liquid, not computed in SQL).
    """
    glob = _bars_glob(parquet_root, exchange)
    if not glob_files(glob):
        # No bars ingested yet for this exchange -- an empty features
        # table, not an error: the whole point of a fully-rebuildable
        # derived feature is that "nothing to compute from yet" is a
        # normal, early-pipeline state.
        return LIQUIDITY_DAILY_SCHEMA.empty_table().select(
            ["symbol", "median_turnover_20d", "median_volume_20d", "median_trades_20d",
             "median_delivery_pct_20d", "avg_price_20d", "listed_days"]
        )

    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(
            """
            WITH scanned AS (
                SELECT * FROM read_parquet(?, hive_partitioning=true)
                WHERE exchange = ? AND date <= ?
            ),
            ranked AS (
                SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM scanned
            ),
            windowed AS (
                SELECT * FROM ranked WHERE rn <= ?
            ),
            listed AS (
                SELECT symbol, COUNT(DISTINCT date) AS listed_days
                FROM scanned
                GROUP BY symbol
            )
            SELECT
                w.symbol AS symbol,
                median(w.turnover) AS median_turnover_20d,
                median(w.volume) AS median_volume_20d,
                median(w.trades) AS median_trades_20d,
                median(w.delivery_pct) AS median_delivery_pct_20d,
                avg(w.close) AS avg_price_20d,
                l.listed_days AS listed_days
            FROM windowed w
            JOIN listed l USING (symbol)
            GROUP BY w.symbol, l.listed_days
            ORDER BY w.symbol
            """,
            [glob, exchange, as_of_date.isoformat(), lookback_days],
        ).fetchall()
        columns = [d[0] for d in con.description] if con.description else []
    finally:
        con.close()

    return pa.Table.from_pylist([dict(zip(columns, row, strict=True)) for row in rows])


def build_liquidity_daily_table(
    metrics_table: pa.Table, *, exchange: str, as_of_date: date, thresholds: LiquidityThresholds
) -> pa.Table:
    """Apply domain.universe.is_liquid to each row and shape the result
    into LIQUIDITY_DAILY_SCHEMA. Kept separate from the DuckDB query
    above so the pure-Python decision rule application is easy to
    unit-test with a hand-built input table."""
    rows = metrics_table.to_pylist()
    out_rows = []
    for row in rows:
        metrics = LiquidityMetrics(
            median_turnover_20d=row["median_turnover_20d"],
            median_volume_20d=row["median_volume_20d"],
            median_trades_20d=row["median_trades_20d"],
            avg_price_20d=row["avg_price_20d"],
            listed_days=row["listed_days"],
        )
        passed, _reason = is_liquid(metrics, thresholds)
        out_rows.append(
            {
                "date": as_of_date,
                "exchange": exchange,
                "symbol": row["symbol"],
                "security_id": None,
                "median_turnover_20d": row["median_turnover_20d"],
                "median_volume_20d": row["median_volume_20d"],
                "median_trades_20d": row["median_trades_20d"],
                "median_delivery_pct_20d": row["median_delivery_pct_20d"],
                "avg_price_20d": row["avg_price_20d"],
                "listed_days": row["listed_days"],
                "is_liquid": passed,
            }
        )
    if not out_rows:
        return LIQUIDITY_DAILY_SCHEMA.empty_table()
    return pa.Table.from_pylist(out_rows, schema=LIQUIDITY_DAILY_SCHEMA)


def _refresh_universe_current(
    conn: sqlite3.Connection, *, exchange: str, as_of_date: date, liquidity_table: pa.Table
) -> None:
    """Truncate-and-replace universe_current for symbols resolvable to a
    security_id via listings/securities. Symbols with no matching
    listing are skipped (see this module's docstring's known
    limitation) rather than failing the whole job -- an unresolvable
    symbol is an expected state before the security master has been
    ingested, not a data-integrity problem."""
    rows = liquidity_table.to_pylist()
    for row in rows:
        match = conn.execute(
            "SELECT security_id FROM listings WHERE exchange=? AND symbol=?",
            (exchange, row["symbol"]),
        ).fetchone()
        if match is None:
            continue
        reason = (
            "passes all liquidity thresholds" if row["is_liquid"] else "fails liquidity thresholds"
        )
        conn.execute(
            """INSERT INTO universe_current (security_id, as_of_date, is_liquid, reason)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (security_id) DO UPDATE SET
                 as_of_date=excluded.as_of_date,
                 is_liquid=excluded.is_liquid,
                 reason=excluded.reason""",
            (match["security_id"], as_of_date.isoformat(), int(row["is_liquid"]), reason),
        )


def compute_liquidity_for_date(
    as_of_date: date,
    *,
    exchange: str,
    sqlite_path: Path,
    parquet_root: Path,
    universe_config: UniverseConfig,
) -> LiquidityResult:
    """Compute and persist one exchange's liquidity features for one date.

    Idempotent like every other ingest step here: re-running for the
    same (exchange, date) overwrites that date's rows in the parquet
    partition (upsert_partition) and re-upserts universe_current by
    security_id, converging to the same state.
    """
    from stk.store.db.engine import connect  # noqa: PLC0415

    metrics = compute_liquidity_metrics(
        parquet_root,
        exchange=exchange,
        as_of_date=as_of_date,
        lookback_days=universe_config.liquidity.lookback_days,
    )
    table = build_liquidity_daily_table(
        metrics,
        exchange=exchange,
        as_of_date=as_of_date,
        thresholds=universe_config.liquidity.to_thresholds(),
    )

    partition_path = liquidity_daily_partition(parquet_root, exchange, as_of_date.year)
    upsert_partition(
        partition_path, table, schema=LIQUIDITY_DAILY_SCHEMA, replace_dates={as_of_date}
    )

    conn = connect(sqlite_path)
    try:
        _refresh_universe_current(
            conn, exchange=exchange, as_of_date=as_of_date, liquidity_table=table
        )
    finally:
        conn.close()

    liquid_count = sum(1 for row in table.column("is_liquid").to_pylist() if row)
    return LiquidityResult(as_of_date, exchange, table.num_rows, liquid_count)

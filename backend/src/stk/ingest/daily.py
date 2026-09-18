"""Nightly ingest orchestration.

Phase 1 scope: NSE prices only (via NseSecBhavdataProvider). BSE
prices, corporate actions, fundamentals, and the security-master
refresh follow the identical pattern established here as their
provider adapters land -- see providers/registry.py and the build
plan's phase-1 scope for what's next.

Idempotency is achieved at three layers (see the module docstrings in
ingest.raw_store and store.parquet.writer for the mechanisms):
raw bytes are content-addressed, parquet writes overwrite-by-partition,
and this orchestrator's own job_runs rows are pure observability, never
a re-run lock -- calling this function twice for the same date is
always safe and converges to the same on-disk state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa

from stk.core.errors import DataNotPublished
from stk.core.time import today_ist
from stk.ingest.assertions import assert_bars_sane
from stk.ingest.jobs import JobSkipped, job_run
from stk.ingest.raw_store import persist_artifact
from stk.providers.base import CanonicalBar
from stk.store.db.engine import connect
from stk.store.parquet.layout import bars_daily_partition
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition


class IngestResult:
    def __init__(self, business_date: date, status: str, rows_written: int = 0) -> None:
        self.business_date = business_date
        self.status = status  # success | skipped_holiday | degraded
        self.rows_written = rows_written


def _bars_to_table(bars: list[CanonicalBar]) -> pa.Table:
    """Convert parsed CanonicalBar pydantic models into an Arrow table
    matching BARS_DAILY_SCHEMA. Decimal fields are cast to float64 at
    this boundary -- the schema stores prices as float64 (see
    schema.py); Decimal is used up to this point for exact arithmetic
    in the parser, not carried into the columnar store."""
    ingested_at = datetime.now(UTC)

    def f(v: object) -> float | None:
        return float(v) if v is not None else None  # type: ignore[arg-type]

    n = len(bars)
    return pa.table(
        {
            "date": pa.array([b.date for b in bars], type=pa.date32()),
            "exchange": pa.array([b.exchange for b in bars]).dictionary_encode(),
            "symbol": [b.symbol for b in bars],
            "security_id": pa.array([b.security_id for b in bars], type=pa.int32()),
            "isin": pa.array([b.isin for b in bars], type=pa.string()),
            "series": pa.array([b.series for b in bars]).dictionary_encode(),
            "instrument_type": pa.array([b.instrument_type for b in bars]).dictionary_encode(),
            "open": [f(b.open) for b in bars],
            "high": [f(b.high) for b in bars],
            "low": [f(b.low) for b in bars],
            "close": [f(b.close) for b in bars],
            "prev_close": [f(b.prev_close) for b in bars],
            "last": [f(b.last) for b in bars],
            "vwap": [f(b.vwap) for b in bars],
            "volume": [b.volume for b in bars],
            "turnover": [f(b.turnover) for b in bars],
            "trades": pa.array([b.trades for b in bars], type=pa.int64()),
            "delivery_qty": pa.array([b.delivery_qty for b in bars], type=pa.int64()),
            "delivery_pct": pa.array([f(b.delivery_pct) for b in bars], type=pa.float64()),
            "settle_price": pa.array([f(b.settle_price) for b in bars], type=pa.float64()),
            "source": pa.array([b.source for b in bars]).dictionary_encode(),
            "ingested_at": pa.array([ingested_at] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=BARS_DAILY_SCHEMA,
    )


def ingest_nse_prices_for_date(
    business_date: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
) -> IngestResult:
    """Ingest one day of NSE prices end-to-end: fetch, validate, persist
    raw, parse, sanity-check, and atomically write the year partition.

    Safe to call repeatedly for the same date (see module docstring).
    """
    # Lazy import: avoids a module-level dependency edge from the
    # generic orchestrator onto one specific provider.
    from stk.providers.nse.prices import NseSecBhavdataProvider  # noqa: PLC0415

    provider = NseSecBhavdataProvider()
    conn = connect(sqlite_path)
    try:
        # Everything -- including the fetch itself -- happens inside ONE
        # job_run() scope, so a content-validation failure during fetch
        # is recorded just as reliably as a failure during parsing. See
        # jobs.py's module docstring for why this single-scope structure
        # replaced an earlier version that checked "should I skip?"
        # before opening the scope.
        with job_run(conn, "ingest_nse_prices", business_date=business_date) as handle:
            try:
                artifact = provider.fetch_eod(business_date, "NSE")
            except DataNotPublished as exc:
                raise JobSkipped(str(exc)) from exc

            persist_artifact(raw_root, conn, artifact)

            bars = list(provider.parse_eod(artifact))
            assert_bars_sane(bars, context=f"NSE {business_date.isoformat()}")

            table = _bars_to_table(bars)
            partition_path = bars_daily_partition(parquet_root, "NSE", business_date.year)
            rows_written = upsert_partition(
                partition_path, table, schema=BARS_DAILY_SCHEMA, replace_dates={business_date}
            )

            handle.rows_in = len(bars)
            handle.rows_written = rows_written

        if handle.skipped:
            return IngestResult(business_date, status="skipped_holiday")
        return IngestResult(business_date, status="success", rows_written=handle.rows_written or 0)
    finally:
        conn.close()


def resolve_business_date(requested: date | None) -> date:
    """Default to today (IST) if no date is explicitly requested."""
    return requested if requested is not None else today_ist()

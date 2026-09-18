"""Nightly ingest orchestration.

NSE and BSE prices both go through _ingest_prices_for_date, the shared
orchestration body -- fetch, validate, persist raw, parse, sanity-check,
atomic partition write, all inside one job_run() scope. Corporate
actions, fundamentals, and the security-master refresh follow the same
pattern as their provider adapters land -- see providers/registry.py
and the build plan's phase-1 scope for what's next.

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
from stk.ingest.assertions import assert_bars_match_requested_date, assert_bars_sane
from stk.ingest.jobs import JobSkipped, job_run
from stk.ingest.raw_store import persist_artifact
from stk.providers.base import CanonicalBar, PriceProvider
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


def _ingest_prices_for_date(
    business_date: date,
    *,
    exchange: str,
    job_name: str,
    provider: PriceProvider,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
) -> IngestResult:
    """Shared orchestration body for one exchange's daily price ingest.

    Everything -- including the fetch itself -- happens inside ONE
    job_run() scope, so a content-validation failure during fetch is
    recorded just as reliably as a failure during parsing. See jobs.py's
    module docstring for why this single-scope structure replaced an
    earlier version that checked "should I skip?" before opening the
    scope.
    """
    conn = connect(sqlite_path)
    try:
        with job_run(conn, job_name, business_date=business_date) as handle:
            try:
                artifact = provider.fetch_eod(business_date, exchange)
            except DataNotPublished as exc:
                raise JobSkipped(str(exc)) from exc

            persist_artifact(raw_root, conn, artifact)

            bars = list(provider.parse_eod(artifact))
            context = f"{exchange} {business_date.isoformat()}"
            assert_bars_sane(bars, context=context)
            assert_bars_match_requested_date(bars, business_date, context=context)

            table = _bars_to_table(bars)
            partition_path = bars_daily_partition(parquet_root, exchange, business_date.year)
            # upsert_partition returns the CUMULATIVE row count of the
            # resulting partition file (all dates in that year, not just
            # this one) -- that is the right thing for it to return (its
            # own docstring says so), but it is the wrong number to
            # report as "rows written for this date". A live backfill
            # run surfaced this: reported counts climbed across
            # consecutive days in the same year instead of reflecting
            # each day's actual row count. handle.rows_written must be
            # THIS ingest's row count, i.e. len(bars).
            partition_total_rows = upsert_partition(
                partition_path, table, schema=BARS_DAILY_SCHEMA, replace_dates={business_date}
            )

            handle.rows_in = len(bars)
            handle.rows_written = len(bars)
            handle.metrics["partition_total_rows"] = partition_total_rows

        if handle.skipped:
            return IngestResult(business_date, status="skipped_holiday")
        return IngestResult(business_date, status="success", rows_written=handle.rows_written or 0)
    finally:
        conn.close()


def ingest_nse_prices_for_date(
    business_date: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
) -> IngestResult:
    """Ingest one day of NSE prices end-to-end: fetch, validate, persist
    raw, parse, sanity-check, and atomically write the year partition.

    Source (sec_bhavdata_full vs the legacy pre-2019-09-30 archive) is
    selected automatically by date -- see
    providers.registry.get_nse_price_provider_for_date. Safe to call
    repeatedly for the same date (see module docstring).
    """
    from stk.providers.registry import get_nse_price_provider_for_date  # noqa: PLC0415

    provider = get_nse_price_provider_for_date(business_date)
    return _ingest_prices_for_date(
        business_date,
        exchange="NSE",
        job_name="ingest_nse_prices",
        provider=provider,
        sqlite_path=sqlite_path,
        parquet_root=parquet_root,
        raw_root=raw_root,
    )


def ingest_bse_prices_for_date(
    business_date: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
) -> IngestResult:
    """Ingest one day of BSE prices end-to-end, identical pipeline shape
    to ingest_nse_prices_for_date.

    Only one BSE source is registered (UDiFF, from 2024-07-08) -- see
    providers.bse.prices.BseUdiffProvider. A date before that raises
    NotSupportedError from fetch_eod, which is NOT caught as a skip: an
    unimplemented history gap is a different fact from "not a trading
    day" and must show up as a failure, not a silent skipped_holiday.
    """
    from stk.providers.registry import get_price_provider  # noqa: PLC0415

    provider = get_price_provider("bse_udiff")
    return _ingest_prices_for_date(
        business_date,
        exchange="BSE",
        job_name="ingest_bse_prices",
        provider=provider,
        sqlite_path=sqlite_path,
        parquet_root=parquet_root,
        raw_root=raw_root,
    )


def resolve_business_date(requested: date | None) -> date:
    """Default to today (IST) if no date is explicitly requested."""
    return requested if requested is not None else today_ist()

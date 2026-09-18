"""Index (benchmark) ingest.

Same shape as ingest.daily's price path -- fetch, validate, persist
raw, parse, assert, atomic partition write, all inside one job_run
scope -- but for NSE's all-index close file rather than a bhavcopy.
See providers/nse/indices.py for what the endpoint is and what its
probe established.

Phase 2 needs this: every backtest metric that means anything
(alpha, beta, excess return) is relative to a benchmark, and the UI
contract in the build plan pins `niftyCurve` and `niftyReturnPct` as
first-class API fields.

KNOWN LIMITATION, deliberately not papered over: coverage starts
2012-02-21, while the price lake reaches 2010-01-04. A backtest
starting before Feb 2012 has price data but no benchmark for its first
two years. That is a fact about the free data, and `stk doctor` can
surface it; fabricating a benchmark by, say, back-projecting from a
later series would be far worse than an honest gap.

BSE/SENSEX is NOT ingested -- see docs/data-sources.md. NSE's file
covers NSE indices only, and no free BSE index archive was confirmed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa

from stk.core.errors import DataNotPublished
from stk.ingest.assertions import (
    assert_index_bars_match_requested_date,
    assert_index_bars_sane,
)
from stk.ingest.jobs import JobSkipped, job_run
from stk.ingest.normalise import IndexBar, parse_ind_close_all
from stk.ingest.raw_store import persist_artifact
from stk.store.db.engine import connect
from stk.store.parquet.layout import indices_daily_partition
from stk.store.parquet.schema import INDICES_DAILY_SCHEMA
from stk.store.parquet.writer import upsert_partition


class IndicesIngestResult:
    def __init__(self, business_date: date, status: str, rows_written: int = 0) -> None:
        self.business_date = business_date
        self.status = status  # success | skipped_holiday
        self.rows_written = rows_written


def _to_table(bars: list[IndexBar]) -> pa.Table:
    ingested_at = datetime.now(UTC)

    def f(v: object) -> float | None:
        return float(v) if v is not None else None  # type: ignore[arg-type]

    n = len(bars)
    return pa.table(
        {
            "date": pa.array([b.date for b in bars], type=pa.date32()),
            "index_name": [b.index_name for b in bars],
            "index_code": pa.array([b.index_code for b in bars]).dictionary_encode(),
            "open": pa.array([f(b.open) for b in bars], type=pa.float64()),
            "high": pa.array([f(b.high) for b in bars], type=pa.float64()),
            "low": pa.array([f(b.low) for b in bars], type=pa.float64()),
            "close": [f(b.close) for b in bars],
            "points_change": pa.array([f(b.points_change) for b in bars], type=pa.float64()),
            "pct_change": pa.array([f(b.pct_change) for b in bars], type=pa.float64()),
            "volume": pa.array([b.volume for b in bars], type=pa.int64()),
            "turnover": pa.array([f(b.turnover) for b in bars], type=pa.float64()),
            "pe": pa.array([f(b.pe) for b in bars], type=pa.float64()),
            "pb": pa.array([f(b.pb) for b in bars], type=pa.float64()),
            "div_yield": pa.array([f(b.div_yield) for b in bars], type=pa.float64()),
            "source": pa.array([b.source for b in bars]).dictionary_encode(),
            "ingested_at": pa.array([ingested_at] * n, type=pa.timestamp("us", tz="UTC")),
        },
        schema=INDICES_DAILY_SCHEMA,
    )


def ingest_indices_for_date(
    business_date: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
    provider_name: str = "nse_indices",
) -> IndicesIngestResult:
    """Ingest one day of NSE index closes end-to-end. Idempotent."""
    from stk.providers.registry import get_indices_provider  # noqa: PLC0415

    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_indices", business_date=business_date) as handle:
            provider = get_indices_provider(provider_name)
            try:
                artifact = provider.fetch_indices(business_date)
            except DataNotPublished as exc:
                raise JobSkipped(str(exc)) from exc

            persist_artifact(raw_root, conn, artifact)

            bars = parse_ind_close_all(artifact.content.decode("utf-8-sig"))
            context = f"indices {business_date.isoformat()}"
            assert_index_bars_sane(bars, context=context)
            assert_index_bars_match_requested_date(bars, business_date, context=context)

            # indices_daily has no `symbol` column, so the writer's
            # default (symbol, date) sort key does not apply here.
            upsert_partition(
                indices_daily_partition(parquet_root, business_date.year),
                _to_table(bars),
                schema=INDICES_DAILY_SCHEMA,
                replace_dates={business_date},
                sort_keys=[("index_name", "ascending"), ("date", "ascending")],
                manifest_root=parquet_root,
                dataset="indices_daily",
                exchange=None,
                year=business_date.year,
            )

            handle.rows_in = len(bars)
            handle.rows_written = len(bars)

        if handle.skipped:
            return IndicesIngestResult(business_date, status="skipped_holiday")
        return IndicesIngestResult(
            business_date, status="success", rows_written=handle.rows_written or 0
        )
    finally:
        conn.close()

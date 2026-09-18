"""Fundamentals ingest: fetch a security's filings and upsert into
fundamentals_snapshots.

Unlike prices, this is a per-symbol fetch (FundamentalsProvider.fetch_statements
takes one SecurityRef), so ingest_fundamentals_for_security handles one
security at a time -- callers loop over the securities they care about
(typically the liquid universe, once phases 2+ need it) rather than
this module doing a full-market sweep itself.

fundamentals_snapshots is NEVER updated in place (see its schema
comment in the migration) -- a new capture is always a new row, kept
distinct by its UNIQUE(provider, security_id, statement_type,
period_type, period_end, consolidated, source_hash). Re-ingesting an
unchanged filing is a no-op via ON CONFLICT DO NOTHING; NSE revising a
filing produces a new source_hash and therefore a new row, preserving
the old one -- point-in-time history is never overwritten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stk.ingest.jobs import job_run
from stk.providers.base import FundamentalsSnapshotIn, Period, SecurityRef
from stk.providers.registry import get_fundamentals_provider
from stk.store.db.engine import connect


class FundamentalsIngestResult:
    def __init__(self, fetched: int, upserted: int) -> None:
        self.fetched = fetched
        self.upserted = upserted


def _resolve_security_id(conn: sqlite3.Connection, isin: str) -> int | None:
    row = conn.execute("SELECT security_id FROM securities WHERE isin=?", (isin,)).fetchone()
    return int(row["security_id"]) if row is not None else None


def upsert_snapshot(conn: sqlite3.Connection, snapshot: FundamentalsSnapshotIn) -> bool:
    security_id = _resolve_security_id(conn, snapshot.security_isin)
    if security_id is None:
        # No security master entry for this ISIN yet -- skip rather
        # than fail; same documented ordering dependency as
        # ingest.liquidity's universe_current upsert.
        return False

    cursor = conn.execute(
        """INSERT INTO fundamentals_snapshots
               (security_id, provider, statement_type, period_type, period_end,
                fiscal_year, fiscal_quarter, consolidated, audited, filing_system,
                broadcast_at, captured_at, is_approximate, is_restated, currency,
                unit_multiplier, data_json, source_url, source_hash, parser_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
           ON CONFLICT (provider, security_id, statement_type, period_type, period_end,
                        consolidated, source_hash) DO NOTHING""",
        (
            security_id, snapshot.provider, snapshot.statement_type, snapshot.period_type.value,
            snapshot.period_end.isoformat(), snapshot.fiscal_year, snapshot.fiscal_quarter,
            int(snapshot.consolidated) if snapshot.consolidated is not None else None,
            int(snapshot.audited) if snapshot.audited is not None else None,
            snapshot.filing_system,
            snapshot.broadcast_at.isoformat() if snapshot.broadcast_at else None,
            snapshot.captured_at.isoformat(), int(snapshot.is_approximate),
            int(snapshot.is_restated), snapshot.currency, snapshot.unit_multiplier,
            json.dumps(snapshot.data), snapshot.source_url, snapshot.source_hash,
        ),
    )
    return cursor.rowcount > 0


def ingest_fundamentals_for_security(
    security: SecurityRef,
    *,
    sqlite_path: Path,
    period_type: Period = Period.QUARTERLY,
    limit: int = 12,
    provider_name: str = "nse_filings",
) -> FundamentalsIngestResult:
    """Fetch one security's recent filings and upsert into
    fundamentals_snapshots. One job_run scope covers fetch through
    upsert, same pattern as every other ingest orchestrator here.
    """
    conn = connect(sqlite_path)
    try:
        with job_run(conn, "ingest_fundamentals", business_date=None) as handle:
            provider = get_fundamentals_provider(provider_name)
            snapshots = provider.fetch_statements(security, period_type, limit=limit)

            upserted = sum(1 for snap in snapshots if upsert_snapshot(conn, snap))

            handle.rows_in = len(snapshots)
            handle.rows_written = upserted

        return FundamentalsIngestResult(len(snapshots), upserted)
    finally:
        conn.close()

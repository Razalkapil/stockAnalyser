"""Sweep the liquid universe's filing metadata (quarterly + annual) into fundamentals_snapshots.

``ingest_fundamentals_for_security`` is per security and opens its own job_run,
which is right for one symbol and wrong for a thousand: it would bury
``stk doctor``'s window in job rows. The sweep uses ONE job_run for the whole
pass and reuses the same upsert, so the storage semantics (never update in
place; a revised filing is a new row) are identical.

A failure on one security is counted and the sweep moves on -- and marks the
job ``degraded`` -- rather than aborting a long run over one bad response.
"""

from __future__ import annotations

import time
from pathlib import Path

import structlog

from stk.core.errors import ProviderError
from stk.ingest.fundamentals import upsert_snapshot
from stk.ingest.jobs import job_run
from stk.providers.base import Period, SecurityRef
from stk.providers.registry import get_fundamentals_provider
from stk.store.db.engine import connect

log = structlog.get_logger(__name__)


class SweepResult:
    def __init__(self) -> None:
        self.securities = 0
        self.filings_upserted = 0
        self.failures = 0


def sweep_liquid_universe(
    *,
    sqlite_path: Path,
    limit: int | None = None,
    per_security_limit: int = 40,
    throttle_s: float = 1.0,
    provider_name: str = "nse_filings",
) -> SweepResult:
    conn = connect(sqlite_path)
    result = SweepResult()
    try:
        with job_run(conn, "ingest_fundamentals_sweep", business_date=None) as handle:
            rows = conn.execute(
                """SELECT s.isin, s.canonical_symbol
                   FROM universe_current u JOIN securities s ON s.security_id = u.security_id
                   WHERE u.is_liquid = 1 AND s.canonical_symbol IS NOT NULL
                   ORDER BY s.canonical_symbol"""
            ).fetchall()
            if limit:
                rows = rows[:limit]
            handle.rows_in = len(rows)
            provider = get_fundamentals_provider(provider_name)
            for row in rows:
                security = SecurityRef(isin=row["isin"], symbol=row["canonical_symbol"],
                                       exchange="NSE")
                result.securities += 1
                for period in (Period.QUARTERLY, Period.ANNUAL):
                    try:
                        snaps = provider.fetch_statements(
                            security, period, limit=per_security_limit
                        )
                    except ProviderError as exc:
                        log.warning("fundamentals_sweep_failed", symbol=security.symbol,
                                    period=period.value, error=str(exc))
                        result.failures += 1
                        handle.degraded = True
                        continue
                    result.filings_upserted += sum(1 for s in snaps if upsert_snapshot(conn, s))
                    time.sleep(throttle_s)
            handle.rows_written = result.filings_upserted
            handle.metrics = {"securities": result.securities, "failures": result.failures}
        return result
    finally:
        conn.close()

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

from stk.core.errors import NotSupportedError, ProviderError
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
        #: Symbols with at least one failed fetch, so `failures=1` in the job's metrics can be
        #: traced back to a security without grepping the log. Bounded to a handful in the
        #: metrics -- a run with everything failing would otherwise blow the metrics_json past
        #: anything worth reading.
        self.failed_symbols: list[str] = []


def sweep_liquid_universe(
    *,
    sqlite_path: Path,
    limit: int | None = None,
    per_security_limit: int = 40,
    throttle_s: float = 1.0,
    provider_name: str = "nse_filings",
    integrated_only: bool = False,
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
                for period in () if integrated_only else (Period.QUARTERLY, Period.ANNUAL):
                    try:
                        snaps = provider.fetch_statements(
                            security, period, limit=per_security_limit
                        )
                    except ProviderError as exc:
                        log.warning("fundamentals_sweep_failed", symbol=security.symbol,
                                    period=period.value, error=str(exc))
                        result.failures += 1
                        result.failed_symbols.append(security.symbol)
                        handle.degraded = True
                        continue
                    result.filings_upserted += sum(1 for s in snaps if upsert_snapshot(conn, s))
                    time.sleep(throttle_s)
                # The newer system that replaced the legacy feed after ~Dec 2024: without it every
                # fundamental is 18+ months stale.
                try:
                    snaps = provider.fetch_integrated_statements(
                        security, limit=per_security_limit)
                except NotSupportedError:
                    snaps = []
                except ProviderError as exc:
                    log.warning("fundamentals_sweep_failed", symbol=security.symbol,
                                period="integrated", error=str(exc))
                    result.failures += 1
                    result.failed_symbols.append(security.symbol)
                    handle.degraded = True
                    snaps = []
                result.filings_upserted += sum(1 for s in snaps if upsert_snapshot(conn, s))
                time.sleep(throttle_s)
            handle.rows_written = result.filings_upserted
            handle.metrics = {"securities": result.securities, "failures": result.failures}
            if result.failed_symbols:
                # Capped: metrics_json is meant to stay a glance-able one-liner in the banner,
                # not a dump. "which symbol" beats "how many" -- if there are more than the cap
                # names, that itself is worth showing instead of a longer list.
                shown = result.failed_symbols[:10]
                more = len(result.failed_symbols) - len(shown)
                handle.metrics["failed_symbols"] = (
                    ", ".join(shown) + (f" (+{more} more)" if more else "")
                )
        return result
    finally:
        conn.close()

"""Historical price backfill.

Reuses ingest_nse_prices_for_date for every date -- non-negotiable per
the build plan: the backfill must not have its own parser or its own
idempotency logic. It only adds: sequential iteration over a date
range, a politeness throttle against the exchange archive host,
resilience to per-date failures (record and continue rather than abort
the whole range), and a summary at the end.

Weekends are skipped without even attempting a fetch (cheap, certain).
Actual trading holidays are NOT filtered out here -- there is no
CalendarProvider wired up yet in phase 1 (see the build plan's open
items) -- so a holiday weekday reaches ingest_nse_prices_for_date,
which already handles "not yet published / doesn't exist" via
DataNotPublished -> JobSkipped -> status="skipped_holiday". This means
a full backfill run works correctly today; it will just do a few
thousand more no-op HTTP requests than strictly necessary until a real
calendar provider lands.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from stk.core.errors import IngestAssertionError, ProviderError
from stk.core.time import is_weekend
from stk.ingest.daily import IngestResult, ingest_nse_prices_for_date


@dataclass
class BackfillSummary:
    total_dates: int = 0
    succeeded: int = 0
    skipped_holidays: int = 0
    failed_dates: list[date] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_dates


def backfill_nse_prices(
    start: date,
    end: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
    throttle_s: float = 1.0,
    on_progress: object | None = None,
) -> BackfillSummary:
    """Ingest every weekday in [start, end] (inclusive), sequentially.

    On a per-date failure (network error, content validation failure,
    or a sanity-assertion trip), the date is recorded in the summary
    and iteration CONTINUES -- a single bad day must not abort a
    multi-year backfill. Callers should re-run the backfill for just
    the failed dates once the underlying issue is understood (the
    idempotency guarantees make that safe and cheap).

    ``on_progress``, if given, is called as ``on_progress(current_date,
    result_or_none, error_or_none)`` after each date -- used by the CLI
    for a progress indicator; kept untyped here to avoid a callback
    protocol for one caller.
    """
    summary = BackfillSummary()
    current = start

    while current <= end:
        if is_weekend(current):
            current += timedelta(days=1)
            continue

        summary.total_dates += 1
        result: IngestResult | None = None
        error: Exception | None = None

        try:
            result = ingest_nse_prices_for_date(
                current, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
            )
            if result.status == "skipped_holiday":
                summary.skipped_holidays += 1
            else:
                summary.succeeded += 1
        except (ProviderError, IngestAssertionError) as exc:
            error = exc
            summary.failed_dates.append(current)

        if on_progress is not None:
            on_progress(current, result, error)  # type: ignore[operator]

        time.sleep(throttle_s)
        current += timedelta(days=1)

    return summary

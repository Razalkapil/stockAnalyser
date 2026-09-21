"""Historical price backfill.

Reuses the same per-exchange ingest function (ingest_nse_prices_for_date
or ingest_bse_prices_for_date) for every date -- non-negotiable per the
build plan: the backfill must not have its own parser or its own
idempotency logic. It only adds: sequential iteration over a date
range, a politeness throttle against the exchange archive host,
resilience to per-date failures (record and continue rather than abort
the whole range), and a summary at the end.

Weekends are skipped without even attempting a fetch (cheap, certain).
Trading holidays are skipped too, but deliberately NOT by a second
date filter here: ingest_{nse,bse}_prices_for_date consults
trading_calendar itself before fetching, so the holiday rule lives in
exactly one place and the nightly job and the backfill cannot drift
apart. Populate the calendar with `stk ingest calendar` to get that
saving; without it, a holiday weekday still reaches the fetch and is
handled by DataNotPublished -> JobSkipped -> status="skipped_holiday",
costing a wasted request but never a wrong answer.

That ordering is the point: the calendar is an optimisation and a
cross-check, never a new trust boundary. A date the calendar has no
opinion about is fetched, not skipped.

BSE prices now have two confirmed sources spanning 2010-01-04 to
present (bse_legacy_bhavcopy and bse_udiff, selected automatically by
date -- see providers.registry.get_bse_price_provider_for_date), so
NotSupportedError is no longer expected during a normal BSE backfill.
It is still not caught per-date below and still propagates and aborts
the whole range immediately if it ever does occur (e.g. a provider
constructed directly for a date outside its own coverage) -- a known,
permanent gap must never be silently recorded as thousands of per-date
"failed" rows, which would bury the one signal (an unexpected failure
on a date that SHOULD work) that this function's per-date
continue-on-failure behaviour exists to surface.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from stk.core.errors import IngestAssertionError, NotSupportedError, ProviderError
from stk.core.time import is_weekend
from stk.ingest.daily import IngestResult, ingest_bse_prices_for_date, ingest_nse_prices_for_date
from stk.ingest.indices import IndicesIngestResult, ingest_indices_for_date


@dataclass
class BackfillSummary:
    total_dates: int = 0
    succeeded: int = 0
    skipped_holidays: int = 0
    failed_dates: list[date] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_dates


def _backfill_prices(
    ingest_one_date: Callable[[date], IngestResult | IndicesIngestResult],
    start: date,
    end: date,
    *,
    throttle_s: float,
    on_progress: object | None,
) -> BackfillSummary:
    """Shared date-range iteration used by both backfill_nse_prices and
    backfill_bse_prices. ``ingest_one_date`` is one of the two
    per-exchange ingest functions, already bound to its sqlite/parquet/
    raw paths by the caller.

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
        result: IngestResult | IndicesIngestResult | None = None
        error: Exception | None = None

        try:
            result = ingest_one_date(current)
            if result.status == "skipped_holiday":
                summary.skipped_holidays += 1
            else:
                summary.succeeded += 1
        except NotSupportedError:
            # A known, permanent gap (e.g. BSE before its UDiFF start),
            # not a per-date fluke -- see this module's docstring for why
            # this must abort the whole range instead of being recorded
            # as a wall of per-date failures.
            raise
        except (ProviderError, IngestAssertionError) as exc:
            error = exc
            summary.failed_dates.append(current)

        if on_progress is not None:
            on_progress(current, result, error)  # type: ignore[operator]

        time.sleep(throttle_s)
        current += timedelta(days=1)

    return summary


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
    """Ingest every weekday of NSE prices in [start, end] (inclusive), sequentially.

    On a per-date failure (network error, content validation failure,
    or a sanity-assertion trip), the date is recorded in the summary
    and iteration CONTINUES -- a single bad day must not abort a
    multi-year backfill. Callers should re-run the backfill for just
    the failed dates once the underlying issue is understood (the
    idempotency guarantees make that safe and cheap).
    """
    return _backfill_prices(
        lambda d: ingest_nse_prices_for_date(
            d, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        ),
        start,
        end,
        throttle_s=throttle_s,
        on_progress=on_progress,
    )


def backfill_bse_prices(
    start: date,
    end: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
    throttle_s: float = 1.0,
    on_progress: object | None = None,
) -> BackfillSummary:
    """Ingest every weekday of BSE prices in [start, end] (inclusive).

    Identical shape to backfill_nse_prices; see this module's docstring
    for why a date before BSE's UDiFF start (2024-07-08) aborts the
    whole range instead of being recorded as a per-date failure.
    """
    return _backfill_prices(
        lambda d: ingest_bse_prices_for_date(
            d, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        ),
        start,
        end,
        throttle_s=throttle_s,
        on_progress=on_progress,
    )


def backfill_indices(
    start: date,
    end: date,
    *,
    sqlite_path: Path,
    parquet_root: Path,
    raw_root: Path,
    throttle_s: float = 1.0,
    on_progress: object | None = None,
) -> BackfillSummary:
    """Ingest every weekday of NSE index closes in [start, end] (inclusive).

    Same shape as the price backfills, and it exists because indices had NO range fill at all:
    a 2023 hole of 29 trading days (2023-04-10 .. 2023-05-22) came from a hand-run loop that
    stopped early and left no trace, and the benchmark silently went flat across it. A day
    that already has a raw file still re-fetches here; the parquet write is
    overwrite-by-partition, so that is wasteful but never wrong.
    """
    return _backfill_prices(
        lambda d: ingest_indices_for_date(
            d, sqlite_path=sqlite_path, parquet_root=parquet_root, raw_root=raw_root
        ),
        start,
        end,
        throttle_s=throttle_s,
        on_progress=on_progress,
    )

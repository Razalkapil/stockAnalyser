"""`stk ingest` -- nightly ingest commands.

Phase 1 scope: NSE and BSE prices. Corporate actions and fundamentals
follow the same orchestration pattern (see ingest.daily) as their
provider adapters land.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import typer

from stk.config.settings import AppSettings, get_settings
from stk.core.errors import IngestAssertionError, ProviderError
from stk.ingest.daily import (
    IngestResult,
    ingest_bse_prices_for_date,
    ingest_nse_prices_for_date,
    resolve_business_date,
)

app = typer.Typer(help="Nightly data ingest.")


def _run_one(
    exchange: str,
    business_date: date,
    ingest_fn: Callable[..., IngestResult],
    settings: AppSettings,
) -> bool:
    """Run one exchange's ingest, print its outcome, and return whether it succeeded
    (skipped_holiday counts as success -- it is an expected outcome, not a failure)."""
    typer.echo(f"Ingesting {exchange} prices for {business_date.isoformat()}...")
    try:
        result = ingest_fn(
            business_date,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
            raw_root=settings.paths.raw,
        )
    except (ProviderError, IngestAssertionError) as exc:
        typer.secho(f"{exchange} FAILED: {exc}", fg="red", bold=True)
        return False

    if result.status == "skipped_holiday":
        typer.echo(
            f"{exchange} {business_date.isoformat()}: not a trading day "
            "(or not yet published). Skipped."
        )
    else:
        typer.secho(
            f"{exchange} OK: {result.rows_written} rows written for "
            f"{business_date.isoformat()}",
            fg="green",
        )
    return True


@app.command("daily")
def daily(
    date_str: str | None = typer.Option(
        None, "--date", help="YYYY-MM-DD, defaults to today (IST)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-fetch even if a raw artifact for this date exists"
    ),
) -> None:
    """Ingest one day of NSE and BSE prices.

    Both exchanges run even if one fails -- a BSE outage must not lose
    a successful NSE ingest, and vice versa (same job-isolation
    principle as ingest.daily's own per-step job_run scoping). Exits
    non-zero if either exchange failed.
    """
    business_date = resolve_business_date(
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    )
    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    settings.paths.parquet.mkdir(parents=True, exist_ok=True)

    nse_ok = _run_one("NSE", business_date, ingest_nse_prices_for_date, settings)
    bse_ok = _run_one("BSE", business_date, ingest_bse_prices_for_date, settings)

    if not (nse_ok and bse_ok):
        raise typer.Exit(code=1)

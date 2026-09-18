"""`stk ingest` -- nightly ingest commands.

Phase 1 scope: NSE prices only. BSE, corporate actions and fundamentals
follow the same orchestration pattern (see ingest.daily) as their
provider adapters land.
"""

from __future__ import annotations

from datetime import datetime

import typer

from stk.config.settings import get_settings
from stk.core.errors import IngestAssertionError, ProviderError
from stk.ingest.daily import ingest_nse_prices_for_date, resolve_business_date

app = typer.Typer(help="Nightly data ingest.")


@app.command("daily")
def daily(
    date_str: str | None = typer.Option(
        None, "--date", help="YYYY-MM-DD, defaults to today (IST)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-fetch even if a raw artifact for this date exists"
    ),
) -> None:
    """Ingest one day of NSE prices."""
    business_date = resolve_business_date(
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    )
    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    settings.paths.parquet.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Ingesting NSE prices for {business_date.isoformat()}...")
    try:
        result = ingest_nse_prices_for_date(
            business_date,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
            raw_root=settings.paths.raw,
        )
    except (ProviderError, IngestAssertionError) as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    if result.status == "skipped_holiday":
        typer.echo(
            f"{business_date.isoformat()} is not a trading day (or not yet published). Skipped."
        )
    else:
        typer.secho(
            f"OK: {result.rows_written} rows written for {business_date.isoformat()}", fg="green"
        )

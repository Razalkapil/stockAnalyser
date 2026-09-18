"""`stk backfill` -- historical price backfill."""

from __future__ import annotations

from datetime import datetime

import typer

from stk.config.settings import get_settings
from stk.ingest.backfill import backfill_nse_prices

app = typer.Typer(help="Historical price backfill.")


@app.command("prices")
def prices(
    from_date: str = typer.Option(..., "--from", help="YYYY-MM-DD, inclusive"),
    to_date: str = typer.Option(..., "--to", help="YYYY-MM-DD, inclusive"),
    exchange: str = typer.Option("NSE", "--exchange", help="Only NSE is implemented so far"),
    throttle_s: float = typer.Option(1.0, "--throttle-s", help="Delay between requests"),
) -> None:
    """Backfill daily NSE prices over a date range.

    Source (legacy vs sec_bhavdata_full) is selected automatically per
    date -- see providers.registry.get_nse_price_provider_for_date and
    docs/adr/0003-historical-price-source.md for the confirmed
    availability windows. Safe to re-run: already-ingested dates are
    fast no-ops (see the parquet writer and raw-artifact idempotency
    mechanisms), so re-running after a partial failure only re-does the
    dates that actually failed.
    """
    if exchange != "NSE":
        typer.secho(f"Only NSE is implemented so far, got --exchange {exchange!r}", fg="red")
        raise typer.Exit(code=1)

    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    if start > end:
        typer.secho("--from must not be after --to", fg="red")
        raise typer.Exit(code=1)

    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    settings.paths.parquet.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Backfilling NSE prices {start.isoformat()} .. {end.isoformat()}...")

    def _progress(d, result, error) -> None:
        if error is not None:
            typer.secho(f"  {d.isoformat()}: FAILED ({error})", fg="red")
        elif result.status == "skipped_holiday":
            typer.echo(f"  {d.isoformat()}: skipped (non-trading day)")
        else:
            typer.echo(f"  {d.isoformat()}: OK ({result.rows_written} rows)")

    summary = backfill_nse_prices(
        start,
        end,
        sqlite_path=settings.paths.sqlite,
        parquet_root=settings.paths.parquet,
        raw_root=settings.paths.raw,
        throttle_s=throttle_s,
        on_progress=_progress,
    )

    typer.echo("")
    typer.echo(
        f"Done: {summary.succeeded} ingested, {summary.skipped_holidays} skipped "
        f"(non-trading), {len(summary.failed_dates)} failed, "
        f"of {summary.total_dates} weekdays in range."
    )

    if not summary.ok:
        typer.secho(f"Failed dates: {[d.isoformat() for d in summary.failed_dates]}", fg="red")
        raise typer.Exit(code=1)

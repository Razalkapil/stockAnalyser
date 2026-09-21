"""`stk backfill` -- historical price backfill."""

from __future__ import annotations

from datetime import datetime

import typer

from stk.config.settings import get_settings
from stk.core.errors import NotSupportedError
from stk.ingest.backfill import backfill_bse_prices, backfill_indices, backfill_nse_prices

app = typer.Typer(help="Historical price backfill.")

_BACKFILL_FNS = {"NSE": backfill_nse_prices, "BSE": backfill_bse_prices}


@app.command("prices")
def prices(
    from_date: str = typer.Option(..., "--from", help="YYYY-MM-DD, inclusive"),
    to_date: str = typer.Option(..., "--to", help="YYYY-MM-DD, inclusive"),
    exchange: str = typer.Option("NSE", "--exchange", help="NSE or BSE"),
    throttle_s: float = typer.Option(1.0, "--throttle-s", help="Delay between requests"),
) -> None:
    """Backfill daily prices over a date range for one exchange.

    NSE source (legacy vs sec_bhavdata_full) is selected automatically
    per date -- see providers.registry.get_nse_price_provider_for_date
    and docs/adr/0003-historical-price-source.md for the confirmed
    availability windows. BSE has only one confirmed source, UDiFF,
    live from 2024-07-08 -- requesting an earlier BSE date aborts
    immediately with NotSupportedError rather than recording a wall of
    per-date failures for a known, permanent gap (see
    ingest.backfill's module docstring). Safe to re-run: already-
    ingested dates are fast no-ops (see the parquet writer and
    raw-artifact idempotency mechanisms), so re-running after a partial
    failure only re-does the dates that actually failed.
    """
    backfill_fn = _BACKFILL_FNS.get(exchange.upper())
    if backfill_fn is None:
        typer.secho(f"--exchange must be NSE or BSE, got {exchange!r}", fg="red")
        raise typer.Exit(code=1)

    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    if start > end:
        typer.secho("--from must not be after --to", fg="red")
        raise typer.Exit(code=1)

    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    settings.paths.parquet.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Backfilling {exchange.upper()} prices {start.isoformat()} .. {end.isoformat()}...")

    def _progress(d, result, error) -> None:
        if error is not None:
            typer.secho(f"  {d.isoformat()}: FAILED ({error})", fg="red")
        elif result.status == "skipped_holiday":
            typer.echo(f"  {d.isoformat()}: skipped (non-trading day)")
        else:
            typer.echo(f"  {d.isoformat()}: OK ({result.rows_written} rows)")

    try:
        summary = backfill_fn(
            start,
            end,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
            raw_root=settings.paths.raw,
            throttle_s=throttle_s,
            on_progress=_progress,
        )
    except NotSupportedError as exc:
        typer.secho(f"ABORTED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(
        f"Done: {summary.succeeded} ingested, {summary.skipped_holidays} skipped "
        f"(non-trading), {len(summary.failed_dates)} failed, "
        f"of {summary.total_dates} weekdays in range."
    )

    if not summary.ok:
        typer.secho(f"Failed dates: {[d.isoformat() for d in summary.failed_dates]}", fg="red")
        raise typer.Exit(code=1)


@app.command("indices")
def indices(
    from_date: str = typer.Option(..., "--from", help="YYYY-MM-DD, inclusive"),
    to_date: str = typer.Option(..., "--to", help="YYYY-MM-DD, inclusive"),
    throttle_s: float = typer.Option(1.0, "--throttle-s", help="Delay between requests"),
) -> None:
    """Backfill NSE index closes (the benchmark) over a date range.

    Safe to re-run. Days whose file is already on disk but failed to parse are recovered
    offline by `stk ingest indices --reparse` instead, which needs no network.
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    if start > end:
        typer.secho("--from must not be after --to", fg="red")
        raise typer.Exit(code=1)

    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    settings.paths.parquet.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Backfilling NSE indices {start.isoformat()} .. {end.isoformat()}...")

    def _progress(d, result, error) -> None:
        if error is not None:
            typer.secho(f"  {d.isoformat()}: FAILED ({error})", fg="red")
        elif result.status == "skipped_holiday":
            typer.echo(f"  {d.isoformat()}: skipped (no index file)")
        else:
            typer.echo(f"  {d.isoformat()}: OK ({result.rows_written} rows)")

    summary = backfill_indices(
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
        f"Done: {summary.succeeded} ingested, {summary.skipped_holidays} skipped, "
        f"{len(summary.failed_dates)} failed, of {summary.total_dates} weekdays in range."
    )
    if not summary.ok:
        typer.secho(f"Failed dates: {[d.isoformat() for d in summary.failed_dates]}", fg="red")
        raise typer.Exit(code=1)

"""`stk ingest` -- nightly and on-demand ingest commands.

`daily` (NSE + BSE prices) is the nightly path. `master` and
`corpactions` are on-demand/weekly per the build plan, not yet wired
into `daily`. Fundamentals follow the same orchestration pattern once
its provider adapter lands.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import typer

from stk.config.settings import AppSettings, get_settings
from stk.config.universe import load_universe_config
from stk.core.errors import IngestAssertionError, ParseError, ProviderError
from stk.ingest.corpactions import ingest_corporate_actions
from stk.ingest.daily import (
    IngestResult,
    ingest_bse_prices_for_date,
    ingest_nse_prices_for_date,
    resolve_business_date,
)
from stk.ingest.liquidity import compute_liquidity_for_date
from stk.ingest.master import ingest_security_master

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


@app.command("master")
def master() -> None:
    """Refresh securities/listings/symbol_history from NSE + BSE's
    security masters, merged by ISIN.

    Not on the nightly `daily` path yet (weekly/on-demand cadence per
    the build plan) -- run explicitly.
    """
    settings = get_settings()
    result = ingest_security_master(
        sqlite_path=settings.paths.sqlite, exchanges=settings.ingest.exchanges
    )
    typer.secho(
        f"OK: {result.securities_upserted} securities, "
        f"{result.listings_upserted} listings, {result.renames} rename(s)",
        fg="green",
    )


@app.command("corpactions")
def corpactions(
    since_str: str | None = typer.Option(
        None, "--since", help="YYYY-MM-DD; defaults to the provider's own rolling window"
    ),
) -> None:
    """Fetch, parse, and upsert corporate actions (NSE, currently the
    sole source for both exchanges per docs/data-sources.md).

    Exits non-zero on an unparsed subject (ingest.fail_on_unparsed_corp_action) --
    a missed bonus/split must never be silently absorbed.
    """
    settings = get_settings()
    since = datetime.strptime(since_str, "%Y-%m-%d").date() if since_str else None
    try:
        result = ingest_corporate_actions(
            sqlite_path=settings.paths.sqlite,
            since=since,
            fail_on_unparsed=settings.ingest.fail_on_unparsed_corp_action,
        )
    except (ProviderError, IngestAssertionError, ParseError) as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"OK: {result.upserted}/{result.fetched} actions upserted "
        f"({result.unparsed} unparsed)",
        fg="green",
    )


@app.command("liquidity")
def liquidity(
    date_str: str | None = typer.Option(
        None, "--date", help="YYYY-MM-DD, defaults to today (IST)"
    ),
) -> None:
    """Recompute the liquidity feature set and universe_current for one date.

    A pure derived step: reads already-ingested bars_daily parquet,
    never fetches from the network. Safe to re-run -- see
    ingest.liquidity's module docstring for the idempotency mechanism.
    """
    business_date = resolve_business_date(
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    )
    settings = get_settings()
    universe_config = load_universe_config()

    for exchange in settings.ingest.exchanges:
        result = compute_liquidity_for_date(
            business_date,
            exchange=exchange,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
            universe_config=universe_config,
        )
        typer.secho(
            f"{exchange} liquidity {business_date.isoformat()}: "
            f"{result.symbols_liquid}/{result.symbols_evaluated} symbols liquid",
            fg="green",
        )

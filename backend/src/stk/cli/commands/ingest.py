"""`stk ingest` -- nightly and on-demand ingest commands.

`daily` (NSE + BSE prices) is the nightly path. `master`, `corpactions`
and `fundamentals` are on-demand/weekly per the build plan, not yet
wired into `daily`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Annotated

import typer

from stk.config.loader import load_named_yaml
from stk.config.settings import AppSettings, get_settings
from stk.config.universe import load_universe_config
from stk.core.errors import IngestAssertionError, ParseError, ProviderError
from stk.core.time import today_ist
from stk.ingest.adjustments import rebuild_adjusted_bars_job
from stk.ingest.calendar import ingest_calendar_from_bars, ingest_calendar_year
from stk.ingest.corpactions import UnparsedCorporateActionsError, ingest_corporate_actions
from stk.ingest.daily import (
    IngestResult,
    ingest_bse_prices_for_date,
    ingest_nse_prices_for_date,
    resolve_business_date,
)
from stk.ingest.fundamentals import ingest_fundamentals_for_security
from stk.ingest.fundamentals_sweep import sweep_liquid_universe
from stk.ingest.fundamentals_xbrl import (
    DEFAULT_MIN_PERIOD_END,
    ingest_xbrl_documents,
    reparse_from_raw,
)
from stk.ingest.indices import ingest_indices_for_date
from stk.ingest.instruments import ingest_instrument_classes
from stk.ingest.liquidity import compute_liquidity_for_date
from stk.ingest.master import ingest_security_master
from stk.providers.base import Period, SecurityRef

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
    rebuild_adjustments: bool = typer.Option(
        True,
        "--rebuild-adjustments/--no-rebuild-adjustments",
        help="Rebuild bars_daily_adjusted after ingesting (default: on)",
    ),
) -> None:
    """Ingest one day of NSE and BSE prices, then rebuild adjusted bars.

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

    if rebuild_adjustments:
        # Step 6 of the build plan's nightly sequence. Unconditional
        # rather than triggered by new ex-dates, because it is cheap
        # (seconds) and because "did a new ex-date land" is only known
        # after `stk ingest corpactions`, which is a separate command.
        # An adjusted series that is merely rebuilt redundantly costs
        # nothing; one that is stale is silently wrong.
        for exch in settings.ingest.exchanges:
            adj = rebuild_adjusted_bars_job(
                exchange=exch,
                sqlite_path=settings.paths.sqlite,
                parquet_root=settings.paths.parquet,
            )
            if adj.degraded:
                typer.secho(
                    f"{exch} adjustments DEGRADED: {adj.excluded_actions} unusable, "
                    f"{adj.unresolved_actions} unresolved -- see `stk doctor`",
                    fg="yellow",
                )

    if not (nse_ok and bse_ok):
        raise typer.Exit(code=1)


@app.command("calendar")
def calendar(
    year: int | None = typer.Option(
        None, "--year", help="Calendar year to fetch from NSE (default: current IST year)"
    ),
    from_bars: bool = typer.Option(
        False,
        "--from-bars",
        help="Also derive calendar rows from dates present in bars_daily, "
        "for the range the price lake covers",
    ),
    exchange: str = typer.Option("NSE", "--exchange", help="NSE or BSE"),
) -> None:
    """Populate trading_calendar.

    NSE's holiday master is authoritative and reaches back to 2011
    (live-verified 2026-09-19). `--from-bars` additionally derives
    rows from what the price lake actually contains -- honest
    observation, labelled as such in trading_calendar.source, and it
    never overwrites an authoritative row.
    """
    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)

    target_year = year if year is not None else today_ist().year
    typer.echo(f"Fetching {exchange} holiday calendar for {target_year}...")
    try:
        result = ingest_calendar_year(
            target_year,
            exchange=exchange,
            sqlite_path=settings.paths.sqlite,
            raw_root=settings.paths.raw,
            provider_name=settings.providers.calendar,
        )
    except (ProviderError, ParseError) as exc:
        typer.secho(f"calendar FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"{exchange} {result.year}: {result.trading_days} trading days, "
        f"{result.holidays} holidays",
        fg="green",
    )

    if from_bars:
        typer.echo(f"Deriving {exchange} calendar rows from ingested bars...")
        observed = ingest_calendar_from_bars(
            exchange=exchange,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
        )
        if observed.trading_days == 0:
            typer.echo("No bars ingested yet for this exchange -- nothing to derive.")
        else:
            typer.secho(
                f"{exchange}: {observed.trading_days} observed trading days, "
                f"{observed.holidays} inferred non-trading weekdays",
                fg="green",
            )


@app.command("indices")
def indices(
    date_str: str | None = typer.Option(
        None, "--date", help="YYYY-MM-DD, defaults to today (IST)"
    ),
) -> None:
    """Ingest one day of NSE index closes (the Phase-2 benchmark).

    Coverage starts 2012-02-21 -- about two years after the price lake
    begins. See ingest/indices.py for why that gap is left visible
    rather than filled in.
    """
    business_date = resolve_business_date(
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    )
    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Ingesting NSE indices for {business_date.isoformat()}...")
    try:
        result = ingest_indices_for_date(
            business_date,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
            raw_root=settings.paths.raw,
        )
    except (ProviderError, IngestAssertionError, ParseError) as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    if result.status == "skipped_holiday":
        typer.echo(f"{business_date.isoformat()}: no index file published. Skipped.")
    else:
        typer.secho(f"OK: {result.rows_written} index rows written", fg="green")


@app.command("instruments")
def instruments(
    date_str: str | None = typer.Option(
        None, "--date", help="YYYY-MM-DD, defaults to today (IST)"
    ),
    days: int = typer.Option(3, "--days", help="Also read this many earlier weekdays"),
) -> None:
    """Classify traded symbols as company shares or funds (ETFs), from NSE UDiFF's ISINs.

    Scans and backtests exclude funds; they refuse to run until this has been run once.
    """
    start = resolve_business_date(
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None)
    settings = get_settings()
    settings.paths.raw.mkdir(parents=True, exist_ok=True)
    day, done, failed = start, 0, 0
    for _ in range(max(days, 1)):
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        try:
            n = ingest_instrument_classes(day, sqlite_path=settings.paths.sqlite,
                                          raw_root=settings.paths.raw)
            typer.echo(f"{day}: {n} instruments classified")
            done += 1 if n else 0
        except (ProviderError, ParseError) as exc:
            typer.secho(f"{day}: FAILED: {exc}", fg="red")
            failed += 1
        day -= timedelta(days=1)
    if failed and not done:
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
        f"{result.listings_upserted} listings, {result.renames} rename(s); "
        f"newly suspended {result.suspended}, newly delisted {result.delisted}",
        fg="yellow" if result.degraded else "green",
    )
    if result.degraded:
        typer.secho("DEGRADED: a snapshot looked truncated, so absences were NOT counted -- "
                    "see the job_runs metrics.", fg="yellow")


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
    except UnparsedCorporateActionsError as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        typer.echo(f"{exc.result.upserted}/{exc.result.fetched} actions were stored anyway.")
        if exc.result.new_ex_dates:
            typer.echo(
                f"{len(exc.result.new_ex_dates)} new ex-date(s) landed -- run "
                "`stk ingest adjustments` to rebuild the adjusted series (it will be flagged "
                "degraded until the unparsed subjects are handled)."
            )
        raise typer.Exit(code=1) from exc
    except (ProviderError, IngestAssertionError, ParseError) as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"OK: {result.upserted}/{result.fetched} actions upserted "
        f"({result.unparsed} unparsed)",
        fg="green",
    )

    if result.new_ex_dates:
        typer.echo(
            f"{len(result.new_ex_dates)} new ex-date(s) landed -- the adjusted price "
            "series is now stale. Run `stk ingest adjustments` to rebuild it."
        )


@app.command("adjustments")
def adjustments(
    exchange: str | None = typer.Option(
        None, "--exchange", help="NSE or BSE; both if omitted"
    ),
) -> None:
    """Rebuild adjustment_factors and bars_daily_adjusted from corporate_actions.

    Network-free and fully rebuildable. A new ex-date invalidates every
    earlier bar of that symbol, so this always rebuilds a whole
    exchange rather than trying to patch a range.

    Exits non-zero if any exchange's rebuild is degraded -- an action
    that could not be turned into a factor is a real hole in the
    adjusted series, and a hole you cannot see is worse than one you
    can.
    """
    settings = get_settings()
    exchanges = [exchange] if exchange else list(settings.ingest.exchanges)

    degraded = False
    for exch in exchanges:
        typer.echo(f"Rebuilding {exch} adjusted bars...")
        result = rebuild_adjusted_bars_job(
            exchange=exch,
            sqlite_path=settings.paths.sqlite,
            parquet_root=settings.paths.parquet,
        )
        typer.secho(
            f"{exch}: {result.actions_applied} actions -> {result.factor_rows} factor rows, "
            f"{result.bars_written} adjusted bars written",
            fg="green",
        )
        if result.degraded:
            degraded = True
            typer.secho(
                f"{exch} DEGRADED: {result.excluded_actions} action(s) had no usable "
                f"factor, {result.unresolved_actions} could not be resolved to a security. "
                "Those symbols' histories are NOT fully adjusted -- see `stk doctor`.",
                fg="yellow",
                bold=True,
            )

    if degraded:
        raise typer.Exit(code=1)


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


@app.command("fundamentals")
def fundamentals(
    symbol: str = typer.Argument(..., help="NSE trading symbol, e.g. RELIANCE"),
    isin: str = typer.Option(..., "--isin", help="Security ISIN (needed for the fetch and upsert)"),
) -> None:
    """Fetch one security's recent quarterly filings (metadata only --
    see stk.providers.nse.fundamentals's module docstring for why this
    is not parsed financial-statement line items) and upsert into
    fundamentals_snapshots.

    Per-security, not a full-market sweep -- see ingest.fundamentals's
    module docstring for why.
    """
    settings = get_settings()
    security = SecurityRef(isin=isin, symbol=symbol, exchange="NSE")
    try:
        result = ingest_fundamentals_for_security(
            security, sqlite_path=settings.paths.sqlite, period_type=Period.QUARTERLY
        )
    except (ProviderError, IngestAssertionError) as exc:
        typer.secho(f"FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"OK: {result.upserted}/{result.fetched} filings upserted", fg="green")


@app.command("fundamentals-sweep")
def fundamentals_sweep(
    limit: int | None = typer.Option(None, "--limit", help="Only the first N liquid securities"),
    throttle_s: float = typer.Option(1.0, "--throttle-s", help="Delay between requests"),
    integrated_only: bool = typer.Option(
        False, "--integrated-only",
        help="Skip the legacy feed (which stops at Dec 2024) and fetch only the newer "
        "Integrated Filing system"),
) -> None:
    """Fetch filing metadata for the whole liquid universe: the legacy quarterly/annual feed
    (periods up to Dec 2024) and the Integrated Filing system (Mar 2025 onward).

    Run `stk ingest liquidity` and `stk ingest master` first so the universe
    exists. Follow with `stk ingest xbrl` to parse the documents. Safe to re-run.
    """
    settings = get_settings()
    result = sweep_liquid_universe(
        sqlite_path=settings.paths.sqlite, limit=limit, throttle_s=throttle_s,
        integrated_only=integrated_only,
    )
    colour = "yellow" if result.failures else "green"
    typer.secho(
        f"{result.securities} securities, {result.filings_upserted} new filings, "
        f"{result.failures} failed fetches",
        fg=colour,
    )
    if result.securities == 0:
        typer.secho("The universe is empty -- run `stk ingest master` and `stk ingest liquidity`.",
                    fg="yellow")


@app.command("xbrl")
def xbrl(
    limit: int | None = typer.Option(None, "--limit", help="Parse at most N pending filings"),
    symbol: Annotated[
        list[str] | None, typer.Option("--symbol", help="Only these symbols (repeatable)")
    ] = None,
    throttle_s: float = typer.Option(1.0, "--throttle-s", help="Delay between downloads"),
    reparse: bool = typer.Option(
        False, "--reparse",
        help="Re-run the parser over documents already on disk (no network) for filings that "
        "were partial / malformed / unsupported -- after a parser fix"),
    since_period: str = typer.Option(
        DEFAULT_MIN_PERIOD_END, "--since-period",
        help="Only filings whose period ends on/after this date (older ones feed no metric)"),
) -> None:
    """Download and parse the XBRL behind every filing not yet parsed (newest first; standalone
    filings of companies that also file consolidated ones are skipped -- they are never read).

    Raw documents are stored content-addressed before parsing, so fixing the
    parser never needs the network again. Definitive outcomes (unsupported,
    malformed, partial) are recorded and not re-fetched; network failures are
    retried on the next run and mark the job degraded.
    """
    settings = get_settings()
    if reparse:
        rr = reparse_from_raw(sqlite_path=settings.paths.sqlite, raw_root=settings.paths.raw,
                              tag_map=load_named_yaml("xbrl_tags"))
        typer.echo(f"re-parsed {rr.attempted}: {rr.parsed} parsed, {rr.partial} partial, "
                   f"{rr.unsupported} unsupported, {rr.malformed} malformed"
                   + (f"; {rr.transient_failures} raw file(s) missing" if rr.transient_failures
                      else ""))
        return
    result = ingest_xbrl_documents(
        sqlite_path=settings.paths.sqlite,
        raw_root=settings.paths.raw,
        tag_map=load_named_yaml("xbrl_tags"),
        limit=limit,
        symbols=set(symbol or []) or None,
        throttle_s=throttle_s,
        min_period_end=since_period,
    )
    typer.echo(
        f"{result.attempted} attempted: {result.parsed} parsed, {result.partial} partial, "
        f"{result.unsupported} unsupported, {result.malformed} malformed, "
        f"{result.transient_failures} fetch failures; {result.line_items} line items"
    )
    if result.partial:
        typer.secho(f"{result.partial} partial parse(s) were kept OUT of metrics -- see "
                    "fundamentals_parse_status.detail_json", fg="yellow")
    if result.transient_failures:
        raise typer.Exit(code=2)

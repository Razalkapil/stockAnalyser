"""`stk nightly` / `stk weekly` -- the scheduled runs (systemd timers call these)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from stk.cli.orchestrator import nightly_steps, run_catch_up, run_steps, weekly_steps
from stk.config.settings import get_settings
from stk.core.time import now_ist, today_ist
from stk.ingest.calendar import expected_data_date, is_trading_day
from stk.ingest.jobs import JobSkipped, job_run
from stk.store.db.engine import connect

app = typer.Typer(help="Scheduled runs.")


def _finish(report_failed: list[str], degraded: list[str]) -> None:
    if degraded:
        typer.secho(f"DEGRADED: {', '.join(degraded)}", fg="yellow")
    if report_failed:
        typer.secho(f"FAILED: {', '.join(report_failed)} -- see `stk doctor` / job_runs",
                    fg="red", bold=True)
        raise typer.Exit(code=1)
    typer.secho("OK", fg="green")


@app.command("nightly")
def nightly(
    date_str: Annotated[
        str | None, typer.Option("--date", help="YYYY-MM-DD; default today")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Run even if the calendar says it is a holiday")
    ] = False,
    catch_up: Annotated[
        bool,
        typer.Option(
            "--catch-up",
            help="Ingest every trading day missed since the lake was last updated (prices, "
                 "indices, paper-trading EOD for each), then run the full nightly steps for the "
                 "most recent one. Use this instead of a bare `stk nightly` on a machine that is "
                 "not always on -- a plain run only ever does ONE day, so a missed timer firing "
                 "would leave a silent hole in the lake. Mutually exclusive with --date.",
        ),
    ] = False,
) -> None:
    """Corporate actions, prices, indices, liquidity, scan, track, paper EOD, AI review.

    Each step is its own subprocess and its own job_runs row; a failure blocks only what depends
    on it. Exits non-zero if any step failed."""
    if catch_up and date_str:
        raise typer.BadParameter("--catch-up and --date are mutually exclusive")
    settings = get_settings()
    conn = connect(settings.paths.sqlite)
    try:
        if catch_up:
            expected = expected_data_date(conn, now_ist())
            report = run_catch_up(
                conn, exchange=settings.ingest.primary_exchange,
                parquet_root=settings.paths.parquet, expected=expected, echo=typer.echo,
            )
            if report.fell_back_to_backfill:
                raise typer.Exit(code=1)
            failed, degraded = report.failed, report.degraded
        else:
            day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today_ist()
            if not force and is_trading_day(conn, day, settings.ingest.primary_exchange) is False:
                with job_run(conn, "nightly", business_date=day):
                    raise JobSkipped
                typer.echo(f"{day}: not a trading day -- nothing to do.")
                return
            typer.echo(f"nightly {day}")
            report_single = run_steps(conn, nightly_steps(day), prefix="nightly",
                                      business_date=day, echo=typer.echo)
            failed, degraded = report_single.failed, report_single.degraded
    finally:
        conn.close()
    _finish(failed, degraded)


@app.command("weekly")
def weekly() -> None:
    """Security master, calendar, filings + XBRL, then the AI strategy lab."""
    settings = get_settings()
    day = today_ist()
    conn = connect(settings.paths.sqlite)
    try:
        typer.echo(f"weekly {day}")
        report = run_steps(conn, weekly_steps(), prefix="weekly", business_date=day,
                           echo=typer.echo)
    finally:
        conn.close()
    _finish(report.failed, report.degraded)

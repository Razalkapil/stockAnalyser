"""`stk nightly` / `stk weekly` -- the scheduled runs (systemd timers call these)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from stk.cli.orchestrator import nightly_steps, run_steps, weekly_steps
from stk.config.settings import get_settings
from stk.core.time import today_ist
from stk.ingest.calendar import is_trading_day
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
) -> None:
    """Corporate actions, prices, indices, liquidity, scan, track, paper EOD, AI review.

    Each step is its own subprocess and its own job_runs row; a failure blocks only what depends
    on it. Exits non-zero if any step failed."""
    settings = get_settings()
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today_ist()
    conn = connect(settings.paths.sqlite)
    try:
        if not force and is_trading_day(conn, day, settings.ingest.primary_exchange) is False:
            with job_run(conn, "nightly", business_date=day):
                raise JobSkipped
            typer.echo(f"{day}: not a trading day -- nothing to do.")
            return
        typer.echo(f"nightly {day}")
        report = run_steps(conn, nightly_steps(day), prefix="nightly", business_date=day,
                           echo=typer.echo)
    finally:
        conn.close()
    _finish(report.failed, report.degraded)


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

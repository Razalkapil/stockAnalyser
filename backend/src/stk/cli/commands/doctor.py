"""`stk doctor` -- ingest health check.

Phase 1 scope: checks that migrations are current and reports on
degraded/failed job runs and unparsed corporate actions recorded so
far. Coverage gap detection (trading_calendar vs parquet dates) lands
once the ingest pipeline itself is writing data -- this command is
built to grow those checks incrementally without changing its exit
contract: exit 0 means healthy, non-zero means "look at this".
"""

from __future__ import annotations

import typer

from stk.config.settings import get_settings
from stk.store.db.engine import connect

app = typer.Typer(help="Ingest pipeline health checks.")


@app.command()
def doctor() -> None:
    """Report on ingest health. Exits non-zero if anything looks wrong."""
    settings = get_settings()
    db_path = settings.paths.sqlite

    if not db_path.exists():
        typer.secho(f"No database found at {db_path}. Run `stk db migrate` first.", fg="red")
        raise typer.Exit(code=1)

    conn = connect(db_path)
    problems: list[str] = []
    try:
        # Only the LATEST attempt per (job_name, business_date) matters --
        # an earlier failed attempt that a later retry fixed is not a
        # live problem. job_runs is observability, not a lock, so
        # multiple attempts for the same job/date are expected.
        degraded = conn.execute(
            """
            SELECT j.job_name, j.business_date, j.status FROM job_runs j
            JOIN (
                SELECT job_name, business_date, MAX(attempt) AS max_attempt
                FROM job_runs GROUP BY job_name, business_date
            ) latest
              ON j.job_name = latest.job_name
             AND j.business_date IS latest.business_date
             AND j.attempt = latest.max_attempt
            WHERE j.status IN ('degraded', 'failed')
            ORDER BY j.started_at DESC LIMIT 20
            """
        ).fetchall()
        for row in degraded:
            problems.append(
                f"job_run degraded/failed: {row['job_name']} on {row['business_date']} "
                f"(status={row['status']})"
            )

        unparsed = conn.execute(
            "SELECT COUNT(*) AS n FROM corporate_actions WHERE parse_status != 'parsed'"
        ).fetchone()
        if unparsed["n"] > 0:
            problems.append(f"{unparsed['n']} corporate action(s) not fully parsed")

        security_count = conn.execute("SELECT COUNT(*) AS n FROM securities").fetchone()
        typer.echo(f"securities: {security_count['n']}")

        calendar_count = conn.execute("SELECT COUNT(*) AS n FROM trading_calendar").fetchone()
        typer.echo(f"trading_calendar rows: {calendar_count['n']}")
    finally:
        conn.close()

    if problems:
        typer.secho(f"FOUND {len(problems)} PROBLEM(S):", fg="red", bold=True)
        for p in problems:
            typer.echo(f"  - {p}")
        raise typer.Exit(code=1)

    typer.secho("OK: no problems found.", fg="green")

"""`stk doctor` -- ingest health check.

Thin by design: every actual check lives in stk.ingest.health as a
plain function returning Problems, so the checks are unit-testable
without Typer and this module only formats and decides an exit code.

Exit contract, unchanged since phase 1: 0 means healthy, non-zero
means "look at this".
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

from stk.config.settings import get_settings
from stk.core.errors import DataNotPublished, ProviderError
from stk.core.time import today_ist
from stk.ingest.health import Problem, check_backup_age, run_all_checks
from stk.providers.registry import get_price_provider
from stk.store.backup import latest_backup_age_days
from stk.store.db.engine import connect

app = typer.Typer(help="Ingest pipeline health checks.")

#: Endpoints `--check-endpoints` probes, as (label, callable-description).
#: Kept in sync with docs/data-sources.md.
_ENDPOINT_CHECKS = (
    ("nse_sec_bhavdata", "NSE daily prices (primary)"),
    ("nse_legacy_bhavcopy", "NSE deep history"),
    ("nse_udiff", "NSE UDiFF (ISIN companion)"),
    ("bse_udiff", "BSE daily prices"),
    ("bse_legacy_bhavcopy", "BSE deep history"),
)


@app.command()
def doctor(
    check_endpoints: bool = typer.Option(
        False,
        "--check-endpoints",
        help="Also make REAL network requests to every documented endpoint "
        "to verify it is still reachable. Off by default.",
    ),
    backup_dest: Annotated[
        Path | None,
        typer.Option(
            "--backup-dest",
            envvar="STK_BACKUP_DEST",
            help="Backup directory. When given, a missing or stale backup is a problem.",
        ),
    ] = None,
) -> None:
    """Report on ingest health. Exits non-zero if anything looks wrong."""
    settings = get_settings()
    db_path = settings.paths.sqlite

    if not db_path.exists():
        typer.secho(f"No database found at {db_path}. Run `stk db migrate` first.", fg="red")
        raise typer.Exit(code=1)

    conn = connect(db_path)
    try:
        problems = run_all_checks(
            conn,
            settings.paths.parquet,
            exchanges=list(settings.ingest.exchanges),
            today=today_ist(),
        )
        if backup_dest is not None:
            problems.extend(
                check_backup_age(latest_backup_age_days(backup_dest, today=today_ist()))
            )

        securities = conn.execute("SELECT COUNT(*) AS n FROM securities").fetchone()
        calendar = conn.execute(
            "SELECT COUNT(*) AS n FROM trading_calendar WHERE is_trading_day=1"
        ).fetchone()
        typer.echo(f"securities: {securities['n']}")
        typer.echo(f"trading_calendar known trading days: {calendar['n']}")
    finally:
        conn.close()

    if check_endpoints:
        problems.extend(_check_endpoints())

    real_problems = [p for p in problems if p.is_problem]
    for info in (p for p in problems if not p.is_problem):
        typer.echo(f"  info: {info.message}")

    if real_problems:
        typer.secho(f"FOUND {len(real_problems)} PROBLEM(S):", fg="red", bold=True)
        for problem in real_problems:
            typer.echo(f"  - [{problem.code}] {problem.message}")
        raise typer.Exit(code=1)

    typer.secho("OK: no problems found.", fg="green")


def _check_endpoints() -> list[Problem]:
    """Probe each documented endpoint for reachability.

    Reports a transport or validation failure as a problem, but does
    NOT try to distinguish "NSE is briefly down" from "the URL moved" --
    that judgement needs a human, and this command's job is to put the
    fact in front of one.

    DataNotPublished is treated as success: the host answered correctly
    and simply has no file for that date. Only a broken endpoint is a
    problem.
    """
    problems: list[Problem] = []
    probe_date = _previous_weekday(today_ist() - timedelta(days=1))
    typer.echo(f"Probing documented endpoints (business date {probe_date.isoformat()})...")

    for name, label in _ENDPOINT_CHECKS:
        provider = get_price_provider(name)
        earliest = provider.capabilities.earliest_date
        exchange = "NSE" if name.startswith("nse") else "BSE"
        # Probe each provider at a date it actually claims to cover,
        # so a deep-history provider is not failed for declining a
        # date that postdates its own archive.
        target = probe_date if earliest is None or probe_date >= earliest else earliest
        target = _previous_weekday(target)
        try:
            provider.fetch_eod(target, exchange)
            typer.secho(f"  OK   {name}: {label}", fg="green")
        except DataNotPublished:
            typer.secho(
                f"  OK   {name}: {label} (nothing published for {target}, host responded)",
                fg="green",
            )
        except ProviderError as exc:
            typer.secho(f"  FAIL {name}: {label} -- {exc}", fg="red")
            problems.append(Problem("endpoint_unreachable", f"{name} ({label}): {exc}"))

    return problems


def _previous_weekday(day: date) -> date:
    """Step back to the nearest weekday. Holidays are not filtered --
    a holiday simply yields DataNotPublished, which this check already
    treats as a healthy answer."""
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day

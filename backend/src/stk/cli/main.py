"""`stk` -- the project's single CLI entry point.

Subcommands are grouped by responsibility, matching the package layout:
db (schema management), ingest (nightly pipeline), backtest/costs (phase 2),
doctor (health checks).
"""

from __future__ import annotations

import typer

from stk.cli.commands import (
    ai,
    api,
    backfill,
    backtest,
    costs,
    db,
    doctor,
    ingest,
    picks,
    playground,
    strategies,
)
from stk.config.settings import get_settings
from stk.core.logging import configure_logging

app = typer.Typer(help="stk -- Indian stock suggester + virtual playground.", no_args_is_help=True)
app.add_typer(db.app, name="db")
app.add_typer(ingest.app, name="ingest")
app.add_typer(backfill.app, name="backfill")
app.add_typer(backtest.app, name="backtest")
app.add_typer(costs.app, name="costs")
app.add_typer(strategies.app, name="strategies")
app.add_typer(picks.app, name="picks")
app.add_typer(api.app, name="api")
app.add_typer(ai.app, name="ai")
app.add_typer(playground.app, name="playground")
app.command("scan")(picks.scan_cmd)
app.add_typer(doctor.app)


@app.callback()
def _init() -> None:
    settings = get_settings()
    configure_logging(env=settings.app.env, level=settings.app.log_level)


if __name__ == "__main__":
    app()

"""`stk` -- the project's single CLI entry point.

Subcommands are grouped by responsibility, matching the package layout:
db (schema management), ingest (nightly pipeline), doctor (health checks).
"""

from __future__ import annotations

import typer

from stk.cli.commands import db, doctor, ingest
from stk.config.settings import get_settings
from stk.core.logging import configure_logging

app = typer.Typer(help="stk -- Indian stock suggester + virtual playground.", no_args_is_help=True)
app.add_typer(db.app, name="db")
app.add_typer(ingest.app, name="ingest")
app.add_typer(doctor.app)


@app.callback()
def _init() -> None:
    settings = get_settings()
    configure_logging(env=settings.app.env, level=settings.app.log_level)


if __name__ == "__main__":
    app()

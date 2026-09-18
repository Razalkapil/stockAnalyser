"""`stk db` -- database management commands."""

from __future__ import annotations

import typer

from stk.config.settings import get_settings
from stk.store.db.engine import migrate

app = typer.Typer(help="SQLite database management (migrations).")


@app.command("migrate")
def migrate_cmd() -> None:
    """Apply all pending SQLite migrations."""
    settings = get_settings()
    applied = migrate(settings.paths.sqlite)
    if applied:
        typer.echo(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        typer.echo("No pending migrations.")

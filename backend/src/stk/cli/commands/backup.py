"""`stk backup` -- back up, verify and restore the application state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from stk.config.settings import get_settings
from stk.store.backup import (
    BackupError,
    list_backups,
    restore_backup,
    run_backup,
    verify_backup,
)

app = typer.Typer(help="Backups of app.db and the parquet lake.")

DestOpt = Annotated[Path, typer.Option("--dest", help="Where backups live (NOT inside data/)")]


@app.command("run")
def run(
    dest: DestOpt,
    include_raw: Annotated[
        bool, typer.Option("--include-raw", help="Also archive data/raw")
    ] = False,
    keep_daily: Annotated[int, typer.Option("--keep-daily")] = 7,
    keep_weekly: Annotated[int, typer.Option("--keep-weekly")] = 4,
) -> None:
    """Snapshot app.db (consistent, WAL-safe) and the lake; verify; rotate.

    app.db holds the paper portfolios, journal, picks and AI outputs that exist nowhere else --
    it is backed up every run. Exits non-zero if the backup does not verify."""
    s = get_settings()
    try:
        r = run_backup(sqlite_path=s.paths.sqlite, parquet_root=s.paths.parquet, dest=dest,
                       raw_root=s.paths.raw, include_raw=include_raw, keep_daily=keep_daily,
                       keep_weekly=keep_weekly)
    except BackupError as exc:
        typer.secho(f"BACKUP FAILED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc
    typer.secho(f"OK: {r.path}", fg="green")
    for name, size in r.files.items():
        typer.echo(f"  {name:<18} {size / 1e6:>10.1f} MB")
    if r.removed:
        typer.echo(f"  rotated out: {', '.join(r.removed)}")


@app.command("list")
def list_cmd(dest: DestOpt) -> None:
    dirs = list_backups(dest)
    if not dirs:
        typer.echo("No backups.")
    for d in dirs:
        typer.echo(d.name)


@app.command("verify")
def verify(path: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """Check a backup directory: checksums, database integrity, readable archives."""
    problems = verify_backup(path)
    if problems:
        typer.secho(f"{path.name}: {len(problems)} PROBLEM(S)", fg="red", bold=True)
        for p in problems:
            typer.echo(f"  - {p}")
        raise typer.Exit(code=1)
    typer.secho(f"{path.name}: OK", fg="green")


@app.command("restore")
def restore(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    yes: Annotated[bool, typer.Option("--yes", help="Confirm you mean to restore")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Move existing data aside first (nothing is deleted)")
    ] = False,
) -> None:
    """Restore a backup into the configured data directory. STOP the API and poller first."""
    if not yes:
        typer.secho("Restoring replaces the live database. Stop stk-api and stk-poller first, "
                    "then re-run with --yes.", fg="yellow")
        raise typer.Exit(code=1)
    root = get_settings().paths.data_root
    try:
        done = restore_backup(path, data_root=root, force=force, now=datetime.now(UTC))
    except BackupError as exc:
        typer.secho(f"RESTORE REFUSED: {exc}", fg="red", bold=True)
        raise typer.Exit(code=1) from exc
    for line in done:
        typer.echo(f"  {line}")
    typer.secho("Restored. Run `stk db migrate` and `stk doctor`, then start the services.",
                fg="green")

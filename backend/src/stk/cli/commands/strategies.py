"""`stk strategies` -- validate, register, inspect and gate strategy specs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from stk.config.backtest import load_backtest_config
from stk.config.horizons import load_horizons
from stk.config.loader import find_config_dir
from stk.config.promotion import load_promotion_config
from stk.config.settings import get_settings
from stk.domain.dsl.evaluate import explain
from stk.domain.dsl.model import StrategySpec
from stk.domain.dsl.validate import validate_spec
from stk.ingest.instruments import require_instrument_classes
from stk.store.db.engine import connect
from stk.strategies.preview import preview as run_preview
from stk.strategies.promotion import promote
from stk.strategies.repo import get_strategy, list_strategies, load_spec, register_spec
from stk.strategies.runner import lake_span

app = typer.Typer(help="Strategy specs: validate, register, gate.")


def _load_spec_file(path: Path) -> StrategySpec:
    try:
        spec = StrategySpec.model_validate_json(path.read_text())
    except ValidationError as exc:
        typer.secho(f"{path.name}: schema error", fg="red", bold=True)
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    errors = validate_spec(spec, load_horizons())
    if errors:
        typer.secho(f"{path.name}: {len(errors)} problem(s)", fg="red", bold=True)
        for e in errors:
            typer.echo(f"  - {e}")
        raise typer.Exit(code=1)
    return spec


@app.command("validate")
def validate(file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Validate a strategy spec file (schema + semantic checks). Exits non-zero on any problem."""
    spec = _load_spec_file(file)
    typer.secho(f"OK: {spec.slug} ({spec.horizon.value})", fg="green")
    for line in explain(spec):
        typer.echo(f"  {line}")


@app.command("schema")
def schema(
    out: Annotated[Path | None, typer.Option("--out", help="Write here, not stdout")] = None,
) -> None:
    """Print the strategy DSL as a JSON Schema (also what the AI lab is given)."""
    body = json.dumps(StrategySpec.model_json_schema(), indent=2)
    if out:
        out.write_text(body + "\n")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(body)


@app.command("seed")
def seed() -> None:
    """Register every config/strategies/*.json as a seed strategy (idempotent)."""
    settings = get_settings()
    files = sorted((find_config_dir() / "strategies").glob("*.json"))
    conn = connect(settings.paths.sqlite)
    try:
        for f in files:
            spec = _load_spec_file(f)
            _sid, _vid, created = register_spec(conn, spec, origin="seed")
            typer.echo(f"{'registered' if created else 'unchanged '}  {spec.slug}")
    finally:
        conn.close()
    typer.secho(f"{len(files)} seed strategies. Next: `stk strategies promote --all`.", fg="green")


@app.command("list")
def list_cmd() -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = list_strategies(conn)
    finally:
        conn.close()
    if not rows:
        typer.echo("No strategies. Run `stk strategies seed`.")
        return
    for r in rows:
        typer.echo(f"{r.status:<10} {r.horizon:<11} {r.slug:<34} {r.origin}")


@app.command("explain")
def explain_cmd(slug: str) -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        row = get_strategy(conn, slug)
        if row is None:
            typer.secho(f"no strategy {slug!r}", fg="red")
            raise typer.Exit(code=1)
        spec = load_spec(conn, row.latest_version_id)
    finally:
        conn.close()
    typer.echo(f"{spec.name}  [{row.status}]")
    for line in explain(spec):
        typer.echo(f"  {line}")
    if spec.notes:
        typer.echo(f"\n{spec.notes}")


@app.command("promote")
def promote_cmd(
    slug: str | None = typer.Argument(None),
    all_: bool = typer.Option(False, "--all", help="Every registered strategy"),
    exchange: str = typer.Option("NSE", "--exchange"),
    from_date: str | None = typer.Option(None, "--from"),
    to_date: str | None = typer.Option(None, "--to"),
) -> None:
    """Walk-forward backtest, then the promotion gate. Records the run and the status change."""
    if not slug and not all_:
        typer.secho("give a SLUG or --all", fg="red")
        raise typer.Exit(code=1)
    settings = get_settings()
    span = lake_span(settings.paths.parquet, exchange)
    if span is None:
        typer.secho("The price lake is empty. Run `stk backfill prices` and "
                    "`stk ingest adjustments` first.", fg="red")
        raise typer.Exit(code=1)
    start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else span.first
    end = datetime.strptime(to_date, "%Y-%m-%d").date() if to_date else span.last
    cfg, promo = load_backtest_config(), load_promotion_config()

    conn = connect(settings.paths.sqlite)
    try:
        try:
            require_instrument_classes(conn, exchange)
        except ValueError as exc:
            typer.secho(str(exc), fg="red")
            raise typer.Exit(code=1) from exc
        slugs = [r.slug for r in list_strategies(conn)] if all_ else [str(slug)]
        for s in slugs:
            typer.echo(f"\n{s}: walk-forward {start} .. {end}")
            try:
                row, report, run_id = promote(conn, s, parquet_root=settings.paths.parquet,
                                              cfg=cfg, promo=promo, exchange=exchange,
                                              start=start, end=end)
            except (ValueError, KeyError) as exc:
                typer.secho(f"  skipped: {exc}", fg="yellow")
                continue
            colour = {"pass": "green", "fail": "red"}.get(report.verdict, "yellow")
            typer.secho(f"  {report.verdict.upper()} -> {row.status}  (run #{run_id})", fg=colour)
            for c in report.checks:
                typer.echo(f"    [{'x' if c.passed else ' '}] {c.name}: {c.detail}")
    finally:
        conn.close()



@app.command("preview")
def preview_cmd(
    slug: str | None = typer.Argument(None, help="One strategy; default: every non-promoted one"),
    date_str: str | None = typer.Option(None, "--date", help="YYYY-MM-DD; default: latest bar"),
    exchange: str = typer.Option("NSE", "--exchange"),
) -> None:
    """What NOT-promoted strategies would pick on a date. Writes previews, never picks."""
    settings = get_settings()
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    conn = connect(settings.paths.sqlite)
    try:
        require_instrument_classes(conn, exchange)
        result = run_preview(conn, parquet_root=settings.paths.parquet,
                             cfg=load_backtest_config(), exchange=exchange, scan_date=day,
                             slug=slug)
    except ValueError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    noun = "strategy" if result.strategies == 1 else "strategies"
    typer.echo(f"{result.scan_date}: {result.strategies} non-promoted {noun} previewed, "
               f"{result.rows_created} new row(s), {result.rows_existing} already recorded")
    if result.strategies == 0:
        typer.secho("Nothing to preview: every registered strategy is already live or decaying.",
                    fg="yellow")
    else:
        typer.secho("These are NOT picks -- no strategy here has passed the promotion gate.",
                    fg="yellow")

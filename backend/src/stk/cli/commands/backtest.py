"""`stk backtest` -- inspect stored backtest runs.

Running a strategy needs the strategy DSL (phase 3); this command group
gains `run` there. `show` and `list` work on whatever is stored.
"""

from __future__ import annotations

import typer

from stk.backtest.runs import load_run_summary
from stk.config.settings import get_settings
from stk.store.db.engine import connect

app = typer.Typer(help="Backtest runs.")


@app.command("list")
def list_runs(limit: int = typer.Option(20, "--limit")) -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = conn.execute(
            "SELECT run_id, strategy_ref, kind, status, data_start, data_end, is_approximate "
            "FROM backtest_runs ORDER BY run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        typer.echo("No backtest runs stored.")
        return
    for r in rows:
        approx = " approx" if r["is_approximate"] else ""
        typer.echo(
            f"#{r['run_id']:<4} {r['strategy_ref']:<28} {r['kind']:<13} {r['status']:<8} "
            f"{r['data_start']}..{r['data_end']}{approx}"
        )


@app.command("show")
def show(run_id: int) -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        try:
            summary = load_run_summary(conn, run_id)
        except KeyError as exc:
            typer.secho(str(exc), fg="red")
            raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    run = summary["run"]
    typer.echo(f"Run #{run['run_id']}  {run['strategy_ref']}  ({run['kind']}, {run['status']})")
    typer.echo(f"  span {run['data_start']}..{run['data_end']}  trades {summary['trade_count']}")
    if run["benchmark_missing"]:
        typer.secho("  benchmark did not cover this run", fg="yellow")
    if run["is_approximate"]:
        typer.secho(f"  APPROXIMATE: {run['approx_reasons_json']}", fg="yellow")
    for key, value in sorted(summary["metrics"].items()):
        if key.startswith("overall/") or key.startswith("oos/"):
            typer.echo(f"  {key:<28}{'-' if value is None else f'{value:.4f}'}")
    for w in summary["windows"]:
        typer.echo(f"  {w['label']}: {w['test_start']}..{w['test_end']}  {w['result']}")

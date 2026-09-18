"""`stk backtest` -- run a registered strategy once, and inspect stored runs."""

from __future__ import annotations

from datetime import datetime

import typer

from stk.backtest.runs import load_run_summary, save_single_run
from stk.config.backtest import load_backtest_config
from stk.config.settings import get_settings
from stk.store.db.engine import connect
from stk.strategies.repo import get_strategy, load_spec
from stk.strategies.runner import lake_span, run_single

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



@app.command("run")
def run(
    slug: str = typer.Argument(..., help="A registered strategy (see `stk strategies list`)"),
    exchange: str = typer.Option("NSE", "--exchange"),
    from_date: str | None = typer.Option(None, "--from", help="YYYY-MM-DD; default lake start"),
    to_date: str | None = typer.Option(None, "--to", help="YYYY-MM-DD; default lake end"),
) -> None:
    """One backtest over a single span (no walk-forward, no gate). Stores the run.

    Use `stk strategies promote` for the out-of-sample walk-forward and the gate;
    a single in-sample run is for looking at a strategy, not for trusting it.
    """
    settings = get_settings()
    span = lake_span(settings.paths.parquet, exchange)
    if span is None:
        typer.secho("The price lake is empty. Run `stk backfill prices` and "
                    "`stk ingest adjustments` first.", fg="red")
        raise typer.Exit(code=1)
    start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else span.first
    end = datetime.strptime(to_date, "%Y-%m-%d").date() if to_date else span.last
    cfg = load_backtest_config()

    conn = connect(settings.paths.sqlite)
    try:
        row = get_strategy(conn, slug)
        if row is None:
            typer.secho(f"no strategy {slug!r}; run `stk strategies seed`", fg="red")
            raise typer.Exit(code=1)
        spec = load_spec(conn, row.latest_version_id)
        result, reasons = run_single(spec, parquet_root=settings.paths.parquet, conn=conn,
                                     cfg=cfg, exchange=exchange, start=start, end=end)
        run_id = save_single_run(
            conn, result, strategy_ref=slug, exchange=exchange,
            benchmark_code=cfg.benchmark_index_code, params={},
            config=cfg.model_dump(mode="json"), approx_reasons=reasons,
        )
    finally:
        conn.close()
    m = result.metrics
    typer.secho(f"run #{run_id}: {slug}  {result.dates[0]} .. {result.dates[-1]}", bold=True)
    typer.echo(f"  total return {m.total_return:+.1%}   CAGR {m.cagr:+.1%}   "
               f"max drawdown {m.max_drawdown:.1%}   Sharpe {m.sharpe:.2f}")
    typer.echo(f"  trades {m.trade_count}   win rate {m.win_rate:.0%}   "
               f"profit factor {m.profit_factor:.2f}   exposure {m.exposure:.0%}")
    if m.alpha is not None:
        typer.echo(f"  vs {cfg.benchmark_index_code}: {m.benchmark_return:+.1%} "
                   f"(alpha {m.alpha:+.1%})")
    else:
        typer.secho("  no benchmark for this span (Nifty 500 archive starts 2012-02-21)",
                    fg="yellow")
    for reason in reasons:
        typer.secho(f"  approx: {reason}", fg="yellow")

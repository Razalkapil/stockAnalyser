"""`stk scan` and `stk picks` -- generate, track and list live picks."""

from __future__ import annotations

from datetime import datetime

import typer

from stk.config.backtest import load_backtest_config
from stk.config.promotion import load_promotion_config
from stk.config.settings import get_settings
from stk.ingest.instruments import require_instrument_classes
from stk.store.db.engine import connect
from stk.strategies.scan import scan as run_scan
from stk.strategies.stats import flag_decay
from stk.strategies.tracking import track_picks

app = typer.Typer(help="Live picks: scan, track, list.")


@app.command("scan")
def scan_cmd(
    date_str: str | None = typer.Option(None, "--date", help="YYYY-MM-DD; default: latest bar"),
    exchange: str = typer.Option("NSE", "--exchange"),
) -> None:
    """Run every live/decaying strategy on a date and record its picks (idempotent)."""
    settings = get_settings()
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
    conn = connect(settings.paths.sqlite)
    try:
        require_instrument_classes(conn, exchange)
        result = run_scan(conn, parquet_root=settings.paths.parquet, cfg=load_backtest_config(),
                          exchange=exchange, scan_date=day)
    except ValueError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    noun = "strategy" if result.strategies == 1 else "strategies"
    typer.echo(f"{result.scan_date}: {result.strategies} {noun} scanned, "
               f"{result.picks_created} new pick(s), {result.picks_existing} already recorded")
    if result.strategies == 0:
        typer.secho("No live strategy to scan. Run `stk strategies promote --all` first.",
                    fg="yellow")


@app.command("track")
def track_cmd(exchange: str = typer.Option("NSE", "--exchange")) -> None:
    """Mark open picks to market; close those that hit stop / target / time; flag decay."""
    settings = get_settings()
    conn = connect(settings.paths.sqlite)
    try:
        result = track_picks(conn, parquet_root=settings.paths.parquet,
                             cfg=load_backtest_config(), exchange=exchange)
        decayed = flag_decay(conn, load_promotion_config())
    except ValueError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    typer.echo(f"{result.tracked} tracked: {result.entered} entered, {result.closed} closed, "
               f"{result.voided} void")
    for slug in decayed:
        typer.secho(f"DECAYING: {slug}", fg="yellow")


@app.command("list")
def list_cmd(limit: int = typer.Option(30, "--limit")) -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = conn.execute(
            """SELECT p.signal_date, p.horizon, p.symbol, p.status, p.ref_price, p.score, s.slug
               FROM picks p JOIN strategies s ON s.strategy_id = p.strategy_id
               ORDER BY p.signal_date DESC, p.horizon, p.score DESC LIMIT ?""", (limit,)
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        typer.echo("No picks yet. Run `stk scan`.")
        return
    for r in rows:
        typer.echo(f"{r['signal_date']}  {r['horizon']:<11} {r['symbol']:<14} "
                   f"{r['ref_price']:>10,.2f}  {r['status']:<13} {r['slug']}")

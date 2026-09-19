"""`stk playground` -- the paper-trading poller and its end-of-day step."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

import typer

from stk.backtest.setup import make_rates_fn
from stk.config.backtest import load_backtest_config
from stk.config.playground import load_playground_config
from stk.config.settings import get_settings
from stk.core.errors import ConfigError
from stk.core.money import format_inr
from stk.core.time import today_ist
from stk.playground.context import PlayCtx
from stk.playground.ledger import LedgerError, create_portfolio
from stk.playground.nightly import run_eod
from stk.playground.performance import summarise
from stk.playground.poller import run_forever
from stk.providers.registry import get_intraday_provider
from stk.store.db.engine import connect

app = typer.Typer(help="Paper trading: portfolios, the delayed-feed poller, EOD fills.")


def _ctx() -> PlayCtx:
    return PlayCtx(get_settings().paths.parquet, load_backtest_config(), make_rates_fn())


@app.command("poll")
def poll(once: Annotated[bool, typer.Option("--once", help="One pass, then exit")] = False) -> None:
    """Poll delayed candles while the market is open and fill resting orders (a long-running
    service; systemd runs it). Nothing fills on a stale feed -- orders wait for the EOD bar."""
    settings = get_settings()
    try:
        provider = get_intraday_provider()
    except ConfigError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(code=1) from exc
    conn = connect(settings.paths.sqlite)
    try:
        run_forever(conn, _ctx(), provider, raw_root=settings.paths.raw,
                    cfg=load_playground_config().poller, once=once)
    finally:
        conn.close()


@app.command("eod")
def eod(date_str: Annotated[str | None, typer.Option("--date", help="YYYY-MM-DD")] = None) -> None:
    """Corporate actions, then EOD-fallback fills, then daily snapshots -- in that order.

    Run after `stk ingest daily` has stored the day's bars."""
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today_ist()
    conn = connect(get_settings().paths.sqlite)
    try:
        res = run_eod(conn, _ctx(), day)
    finally:
        conn.close()
    typer.echo(
        f"{day}: {res.corp.splits_applied} split/bonus applied ({res.corp.orders_rescaled} orders "
        f"rescaled), {res.corp.dividends_credited} dividend(s) credited "
        f"({format_inr(res.corp.dividend_total)}), {res.fills.fills} EOD fill(s), "
        f"{res.fills.rejected} rejected, {res.snapshots} snapshot(s)"
    )


portfolio = typer.Typer(help="Paper portfolios.")
app.add_typer(portfolio, name="portfolio")


@portfolio.command("create")
def portfolio_create(
    name: str, capital: Annotated[str, typer.Option("--capital")] = "1000000"
) -> None:
    try:
        amount = Decimal(capital)
    except InvalidOperation as exc:
        typer.secho(f"not a number: {capital!r}", fg="red")
        raise typer.Exit(code=1) from exc
    conn = connect(get_settings().paths.sqlite)
    try:
        pid = create_portfolio(conn, name, amount)
    except LedgerError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    typer.echo(f"created portfolio #{pid} {name!r} with {format_inr(amount)}")


@portfolio.command("list")
def portfolio_list() -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = conn.execute("SELECT portfolio_id, name FROM portfolios WHERE archived_at IS NULL "
                            "ORDER BY portfolio_id").fetchall()
        if not rows:
            typer.echo("No portfolios. Create one with `stk playground portfolio create NAME`.")
        for r in rows:
            s = summarise(conn, _ctx(), r["portfolio_id"])
            typer.echo(
                f"#{s.portfolio_id:<3} {s.name:<20} value {format_inr(s.current_value):>16}  "
                f"cash {format_inr(s.cash):>16}  return {s.return_pct:+.1%}"
            )
    finally:
        conn.close()

"""`stk ai` -- the evening review and AI spend."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

import typer

from stk.ai.client import AnthropicClient
from stk.ai.evening import run_evening_review
from stk.ai.inputs import build_input
from stk.ai.prompts import EVENING_SYSTEM
from stk.backtest.setup import make_rates_fn
from stk.config.ai import load_ai_config
from stk.config.backtest import load_backtest_config
from stk.config.settings import get_settings
from stk.core.time import today_ist
from stk.playground.context import PlayCtx
from stk.store.db.engine import connect

app = typer.Typer(help="AI features: evening review, spend.")


@app.command("evening")
def evening(
    date_str: Annotated[
        str | None, typer.Option("--date", help="YYYY-MM-DD; default today")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the prompt and call nothing")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run even if this date already succeeded")
    ] = False,
) -> None:
    """Rank and explain the day's picks, flag conflicts, and write the market brief.

    One model call. Never fails the pipeline: a problem is recorded in ai_runs and shown here,
    and this command still exits 0 so the nightly run carries on.
    """
    settings = get_settings()
    ai = load_ai_config()
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today_ist()
    ctx = PlayCtx(settings.paths.parquet, load_backtest_config(), make_rates_fn())
    conn = connect(settings.paths.sqlite)
    try:
        if dry_run:
            inp = build_input(conn, ctx, ai, day)
            typer.echo(EVENING_SYSTEM)
            typer.echo("--- user message " + "-" * 40)
            typer.echo(json.dumps(inp.payload, indent=1, sort_keys=True, default=str))
            typer.secho(f"\n{len(inp.pick_ids)} picks, {len(inp.symbols)} symbols. "
                        "Nothing was sent.", fg="yellow")
            return
        client = AnthropicClient(model=ai.model, effort=ai.effort, timeout_s=ai.timeout_s)
        result = run_evening_review(conn, ctx, ai, client, day, force=force)
    finally:
        conn.close()
    colour = {"success": "green", "skipped": "yellow"}.get(result.status, "red")
    typer.secho(f"{day}: {result.status}" + (f" -- {result.detail}" if result.detail else ""),
                fg=colour)
    if result.status == "success":
        cost = f"~${result.cost_usd:.4f}" if result.cost_usd is not None else "cost unknown"
        typer.echo(f"  {result.input_tokens:,} in / {result.output_tokens:,} out tokens, {cost}")


@app.command("usage")
def usage(days: Annotated[int, typer.Option("--days")] = 30) -> None:
    """Every AI call in the last N days: how it ended, tokens, and the estimated cost."""
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = conn.execute(
            """SELECT kind, business_date, model, status, attempts, input_tokens, output_tokens,
                      cost_usd_est, error FROM ai_runs
               WHERE started_at >= datetime('now', ?) ORDER BY run_id DESC""",
            (f"-{days} day",)).fetchall()
    finally:
        conn.close()
    if not rows:
        typer.echo(f"No AI runs in the last {days} days.")
        return
    total = 0.0
    unknown = 0
    for r in rows:
        if r["cost_usd_est"] is None:
            unknown += 1
        else:
            total += r["cost_usd_est"]
        cost = "  n/a  " if r["cost_usd_est"] is None else f"${r['cost_usd_est']:.4f}"
        typer.echo(f"{r['business_date'] or '-':<11} {r['kind']:<15} {r['status']:<15} "
                   f"{r['input_tokens']:>7,} in {r['output_tokens']:>6,} out  {cost}  "
                   f"{(r['error'] or '')[:60]}")
    typer.echo(f"\n{len(rows)} run(s), estimated ${total:.4f}"
               + (f" (+{unknown} with no configured price)" if unknown else ""))

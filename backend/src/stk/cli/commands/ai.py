"""`stk ai` -- the evening review and AI spend."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from stk.ai.client import GroqClient, LlmError, make_client, prompt_json
from stk.ai.evening import run_evening_review
from stk.ai.inputs import build_input
from stk.ai.lab import run_strategy_lab
from stk.ai.lab_inputs import build_lab_input
from stk.ai.prompts import EVENING_SYSTEM, LAB_SYSTEM
from stk.backtest.setup import make_rates_fn
from stk.config.ai import AiConfig, load_ai_config
from stk.config.backtest import load_backtest_config
from stk.config.promotion import load_promotion_config
from stk.config.settings import get_settings
from stk.core.time import today_ist
from stk.playground.context import PlayCtx
from stk.store.db.engine import connect

app = typer.Typer(help="AI features: evening review, spend.")


def _size(ai: AiConfig, system: str, user: str) -> str:
    """Prompt size, and whether the configured guard would refuse it (~4 characters a token)."""
    chars = len(system) + len(user)
    over = ai.max_input_chars is not None and chars > ai.max_input_chars
    limit = f" -- OVER max_input_chars={ai.max_input_chars:,}, the call would be refused" if over \
        else ""
    return f"Prompt: {chars:,} chars (~{chars // 4:,} tokens){limit}."


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

    One model call. A model or output problem is recorded in ai_runs and shown here, and the
    command still exits 0 so the nightly run carries on. A missing API key exits non-zero: it is
    a setup error, and the nightly banner should say so.
    """
    settings = get_settings()
    ai = load_ai_config()
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today_ist()
    ctx = PlayCtx(settings.paths.parquet, load_backtest_config(), make_rates_fn())
    conn = connect(settings.paths.sqlite)
    try:
        if dry_run:
            inp = build_input(conn, ctx, ai, day)
            user = prompt_json(inp.payload)
            typer.echo(EVENING_SYSTEM)
            typer.echo("--- user message " + "-" * 40)
            typer.echo(user)
            typer.secho(f"\n{len(inp.pick_ids)} picks, {len(inp.symbols)} symbols. "
                        f"{_size(ai, EVENING_SYSTEM, user)} Nothing was sent.", fg="yellow")
            return
        try:
            client = make_client(ai)
        except LlmError as exc:
            typer.secho(f"AI unavailable: {exc}", fg="red")
            raise typer.Exit(code=1) from exc
        result = run_evening_review(conn, ctx, ai, client, day, force=force)
    finally:
        conn.close()
    colour = {"success": "green", "skipped": "yellow"}.get(result.status, "red")
    typer.secho(f"{day}: {result.status}" + (f" -- {result.detail}" if result.detail else ""),
                fg=colour)
    if result.status == "success":
        cost = f"~${result.cost_usd:.4f}" if result.cost_usd is not None else "cost unknown"
        typer.echo(f"  {result.input_tokens:,} in / {result.output_tokens:,} out tokens, {cost}")


@app.command("lab")
def lab(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the prompt and call nothing")
    ] = False,
) -> None:
    """Weekly strategy lab: ask for new strategy ideas and demotions.

    Each idea is validated, backtested walk-forward and put through the promotion gate, then
    waits for YOUR approval in the UI. The AI supplies DSL data, never code. One model call;
    the backtests are local (and take a while). Never fails the pipeline.
    """
    settings = get_settings()
    ai = load_ai_config()
    conn = connect(settings.paths.sqlite)
    try:
        if dry_run:
            payload = build_lab_input(conn)
            user = prompt_json(payload)
            typer.echo(LAB_SYSTEM)
            typer.echo("--- user message " + "-" * 40)
            typer.echo(user)
            typer.secho(f"\n{len(payload['strategies'])} strategies. "
                        f"{_size(ai, LAB_SYSTEM, user)} Nothing was sent.", fg="yellow")
            return
        try:
            client = make_client(ai)
        except LlmError as exc:
            typer.secho(f"AI unavailable: {exc}", fg="red")
            raise typer.Exit(code=1) from exc
        result = run_strategy_lab(
            conn, ai, client, parquet_root=settings.paths.parquet,
            cfg=load_backtest_config(), promo=load_promotion_config(), day=today_ist())
    finally:
        conn.close()
    colour = {"success": "green", "skipped": "yellow"}.get(result.status, "red")
    typer.secho(f"strategy lab: {result.status}" + (f" -- {result.detail}" if result.detail
                                                    else ""), fg=colour)
    for pid, status in result.proposals:
        typer.echo(f"  proposal #{pid}: {status}")
    if result.cost_usd is not None:
        typer.echo(f"  ~${result.cost_usd:.4f} for the model call")


@app.command("models")
def models() -> None:
    """List the models the configured Groq key can use -- the quickest live check of the key."""
    ai = load_ai_config()
    if ai.provider != "groq":
        typer.secho(f"provider is {ai.provider!r}; `models` only lists Groq's.", fg="yellow")
        raise typer.Exit(code=1)
    try:
        ids = GroqClient(model=ai.model, timeout_s=ai.timeout_s).list_models()
    except LlmError as exc:
        typer.secho(f"FAILED: {exc}", fg="red")
        raise typer.Exit(code=1) from exc
    for m in ids:
        marker = "  <- configured" if m == ai.model else ""
        typer.echo(f"{m}{marker}")
    if ai.model not in ids:
        typer.secho(f"WARNING: the configured model {ai.model!r} is not available to this key.",
                    fg="red")
        raise typer.Exit(code=1)


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

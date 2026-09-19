"""`stk api` -- serve the dashboard's API and manage its tokens."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from stk.api import auth
from stk.config.settings import get_settings
from stk.store.db.engine import connect

app = typer.Typer(help="Dashboard API.")
token_app = typer.Typer(help="API tokens (single user; only a hash is stored).")
app.add_typer(token_app, name="token")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the API. Binds to localhost by default; put Caddy in front to expose it."""
    import uvicorn  # noqa: PLC0415 -- heavy import, only when serving

    from stk.api.app import create_app  # noqa: PLC0415

    settings = get_settings()
    if reload:
        typer.secho("--reload is not supported with a factory app; restart to pick up changes.",
                    fg="yellow")
    uvicorn.run(create_app(sqlite_path=settings.paths.sqlite,
                           parquet_root=settings.paths.parquet), host=host, port=port)


@app.command("openapi")
def openapi(
    out: Annotated[Path | None, typer.Option("--out", help="Write here instead of stdout")] = None,
) -> None:
    """Print the API's OpenAPI document (the source of the web app's generated types)."""
    from stk.api.app import openapi_document  # noqa: PLC0415

    body = openapi_document()
    if out:
        out.write_text(body)
        typer.echo(f"wrote {out}")
    else:
        typer.echo(body, nl=False)


@token_app.command("create")
def token_create(name: str) -> None:
    """Create a token. It is shown ONCE -- copy it now."""
    conn = connect(get_settings().paths.sqlite)
    try:
        token = auth.create_token(conn, name)
    except Exception as exc:  # sqlite3.IntegrityError on a duplicate name
        typer.secho(f"could not create token {name!r}: {exc}", fg="red")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()
    typer.echo(token)
    typer.secho("Store it now; only its hash is kept.", fg="yellow", err=True)


@token_app.command("list")
def token_list() -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        rows = auth.list_tokens(conn)
    finally:
        conn.close()
    if not rows:
        typer.echo("No tokens. Create one with `stk api token create NAME`.")
    for r in rows:
        state = "revoked" if r["revoked_at"] else "active"
        typer.echo(f"{r['name']:<20} {state:<8} created {r['created_at'][:19]}  "
                   f"last used {(r['last_used_at'] or 'never')[:19]}")


@token_app.command("revoke")
def token_revoke(name: str) -> None:
    conn = connect(get_settings().paths.sqlite)
    try:
        ok = auth.revoke_token(conn, name)
    finally:
        conn.close()
    if not ok:
        typer.secho(f"no active token named {name!r}", fg="red")
        raise typer.Exit(code=1)
    typer.echo(f"revoked {name} at {datetime.now(UTC):%Y-%m-%d %H:%M}Z")

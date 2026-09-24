"""Dependencies shared by every router: the request context, a per-request SQLite connection,
and bearer-token auth."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from stk.api import auth
from stk.config.backtest import BacktestConfig
from stk.store.db.engine import connect

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApiContext:
    sqlite_path: Path
    parquet_root: Path
    cfg: BacktestConfig
    #: The token from STK_AUTH__TOKEN, passed in by whoever built the app. None means the API
    #: accepts only tokens created with `stk api token create`.
    auth_token: str | None = None


def get_ctx(request: Request) -> ApiContext:
    ctx: ApiContext = request.app.state.ctx
    return ctx


def get_conn(ctx: Annotated[ApiContext, Depends(get_ctx)]) -> Iterator[sqlite3.Connection]:
    # FastAPI runs a sync generator dependency's setup and teardown as separate threadpool jobs,
    # which may land on different threads -- so close() raised ProgrammingError and turned a
    # successful response into a 500. The connection is still used by one request at a time
    # (setup -> endpoint -> teardown), never concurrently, so lifting the thread check is safe.
    conn = connect(ctx.sqlite_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def require_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ctx: Annotated[ApiContext, Depends(get_ctx)],
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
) -> None:
    """Accept either the configured token (STK_AUTH__TOKEN) or one stored in api_tokens.

    The configured one is checked first: it needs no query and no `last_used_at` write, so the
    common single-user case costs nothing. Neither path is a fallback for the other failing --
    both are real credentials, and revoking a database token cannot revoke the .env one.
    """
    if creds is None:
        raise HTTPException(status_code=401, detail="missing or invalid token",
                            headers={"WWW-Authenticate": "Bearer"})
    if auth.verify_configured_token(ctx.auth_token, creds.credentials):
        return
    if not auth.verify_token(conn, creds.credentials):
        raise HTTPException(status_code=401, detail="missing or invalid token",
                            headers={"WWW-Authenticate": "Bearer"})


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Ctx = Annotated[ApiContext, Depends(get_ctx)]

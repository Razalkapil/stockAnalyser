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


def get_ctx(request: Request) -> ApiContext:
    ctx: ApiContext = request.app.state.ctx
    return ctx


def get_conn(ctx: Annotated[ApiContext, Depends(get_ctx)]) -> Iterator[sqlite3.Connection]:
    conn = connect(ctx.sqlite_path)
    try:
        yield conn
    finally:
        conn.close()


def require_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    conn: Annotated[sqlite3.Connection, Depends(get_conn)],
) -> None:
    if creds is None or not auth.verify_token(conn, creds.credentials):
        raise HTTPException(status_code=401, detail="missing or invalid token",
                            headers={"WWW-Authenticate": "Bearer"})


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Ctx = Annotated[ApiContext, Depends(get_ctx)]

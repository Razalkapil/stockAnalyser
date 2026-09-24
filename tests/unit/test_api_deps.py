"""The per-request connection must survive FastAPI running setup and teardown on other threads."""

from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stk.api.deps import ApiContext, get_conn
from stk.config.backtest import load_backtest_config
from stk.store.db.engine import migrate


def test_get_conn_teardown_may_run_on_another_thread(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    migrate(db)
    ctx = ApiContext(sqlite_path=db, parquet_root=tmp_path, cfg=load_backtest_config())
    gen = get_conn(ctx)
    # FastAPI's threadpool runs each step of a sync generator dependency as its own job.
    with ThreadPoolExecutor(max_workers=1) as a, ThreadPoolExecutor(max_workers=1) as b:
        conn = a.submit(next, gen).result()
        assert b.submit(lambda: conn.execute("SELECT 1").fetchone()[0]).result() == 1
        with contextlib.suppress(StopIteration):
            b.submit(next, gen).result()

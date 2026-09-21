"""The AI request queue: how the dashboard asks for a model call it cannot make itself.

Nothing in ``stk.api`` may import ``stk.ai`` -- an import-linter contract enforces it, so a
web request can never turn into a call to a model provider, however the routes change. But a
single-user dashboard still needs a "generate it now" button, and telling the user to open a
terminal is not an answer.

So the button writes a row here and a CLI worker (``stk ai worker``) executes it out of
process. This module sits in ``stk.store``, below both, which is what lets the two sides share
one table without either importing the other.

A queue of one: the partial unique index on (kind, business_date) WHERE status IN
('queued','running') means a day can have at most ONE open request. Pressing the button twice
returns the request already in flight rather than buying a second model call.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from stk.store.db.engine import transaction

#: Requests a worker may pick up, in the order it should.
OPEN_STATUSES = ("queued", "running")

_COLUMNS = """request_id, kind, business_date, status, force, requested_by, requested_at,
              started_at, finished_at, run_id, error"""


@dataclass(frozen=True)
class AiRequest:
    request_id: int
    kind: str
    business_date: str
    status: str          # queued | running | done | error
    force: bool
    requested_by: str
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    run_id: int | None = None
    error: str | None = None


def _row(r: sqlite3.Row) -> AiRequest:
    return AiRequest(
        r["request_id"], r["kind"], r["business_date"], r["status"], bool(r["force"]),
        r["requested_by"], r["requested_at"], r["started_at"], r["finished_at"],
        r["run_id"], r["error"],
    )


def open_request(conn: sqlite3.Connection, kind: str, business_date: str) -> AiRequest | None:
    """The request already in flight for this kind and day, if there is one."""
    r = conn.execute(
        f"SELECT {_COLUMNS} FROM ai_requests "
        "WHERE kind=? AND business_date=? AND status IN ('queued','running')",
        (kind, business_date),
    ).fetchone()
    return _row(r) if r else None


def latest(conn: sqlite3.Connection, kind: str, business_date: str) -> AiRequest | None:
    """The most recent request for this kind and day, whatever became of it."""
    r = conn.execute(
        f"SELECT {_COLUMNS} FROM ai_requests WHERE kind=? AND business_date=? "
        "ORDER BY request_id DESC LIMIT 1",
        (kind, business_date),
    ).fetchone()
    return _row(r) if r else None


def enqueue(
    conn: sqlite3.Connection,
    *,
    kind: str,
    business_date: str,
    force: bool = False,
    requested_by: str = "dashboard",
) -> AiRequest:
    """Queue a request, or return the one already open. Never queues a second call for a day."""
    existing = open_request(conn, kind, business_date)
    if existing is not None:
        return existing
    now = datetime.now(UTC).isoformat()
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO ai_requests (kind, business_date, status, force, requested_by, "
                "requested_at) VALUES (?,?,'queued',?,?,?)",
                (kind, business_date, int(force), requested_by, now),
            )
        return AiRequest(int(cur.lastrowid or 0), kind, business_date, "queued", force,
                         requested_by, now)
    except sqlite3.IntegrityError:
        # Lost a race against another writer: the unique index did its job, so there IS an open
        # request now. Return it rather than reporting a failure the user cannot act on.
        raced = open_request(conn, kind, business_date)
        if raced is None:  # pragma: no cover -- the index makes this unreachable
            raise
        return raced


def claim_next(conn: sqlite3.Connection, kind: str | None = None) -> AiRequest | None:
    """Take the oldest queued request, marking it running. Returns None when the queue is empty.

    The claim is the UPDATE's own rowcount, not a read followed by a write, so two workers
    cannot both run the same request.
    """
    while True:
        sql = ("SELECT request_id FROM ai_requests WHERE status='queued'"
               + (" AND kind=?" if kind else "")
               + " ORDER BY requested_at, request_id LIMIT 1")
        row = conn.execute(sql, (kind,) if kind else ()).fetchone()
        if row is None:
            return None
        now = datetime.now(UTC).isoformat()
        with transaction(conn):
            cur = conn.execute(
                "UPDATE ai_requests SET status='running', started_at=? "
                "WHERE request_id=? AND status='queued'",
                (now, row["request_id"]),
            )
        if cur.rowcount:
            claimed = conn.execute(
                f"SELECT {_COLUMNS} FROM ai_requests WHERE request_id=?", (row["request_id"],)
            ).fetchone()
            return _row(claimed)
        # Someone else claimed it between the read and the update -- look for the next one.


def finish(
    conn: sqlite3.Connection,
    request_id: int,
    *,
    status: str,
    run_id: int | None = None,
    error: str | None = None,
) -> None:
    """Close a claimed request. ``status`` is 'done' or 'error'."""
    if status not in ("done", "error"):
        raise ValueError(f"a finished request is 'done' or 'error', not {status!r}")
    with transaction(conn):
        conn.execute(
            "UPDATE ai_requests SET status=?, finished_at=?, run_id=?, error=? WHERE request_id=?",
            (status, datetime.now(UTC).isoformat(), run_id, error, request_id),
        )

"""JobRun bookkeeping: a context manager that records start/success/
skip/failure of one ingest step into the job_runs table.

Every outcome of a job -- success, an expected skip (e.g. a
non-trading day, or the exchange hasn't published yet), or an
unexpected failure -- goes through this ONE recording path. That is a
deliberate design constraint: an earlier version of this module let
callers record a "skip" via a separate function called instead of
job_run(), and callers had to decide in advance whether a given
invocation would skip or run before opening the job_run scope. That
meant a failure occurring during the "should I skip?" check itself
(e.g. a malformed response from the exchange) was never recorded at
all -- it just propagated as a bare exception with no job_runs row,
invisible to `stk doctor`. Routing every outcome through job_run(),
including the skip case via the JobSkipped signal below, closes that
gap: nothing that happens inside a job_run() block can go unrecorded.

job_runs is observability, not a lock: re-running a job is always
allowed and does not check prior success first -- every insert here
computes the next attempt number rather than assuming attempt=1, which
is what makes repeated calls for the same (job_name, business_date)
safe instead of raising a UNIQUE constraint violation.
"""

from __future__ import annotations

import json
import sqlite3
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from stk.core.version import code_version


class JobSkipped(Exception):
    """Raise inside a job_run() block to record status='skipped_holiday'
    and exit the block WITHOUT it being treated as a failure.

    The exception is caught and swallowed by job_run() itself -- it
    never propagates to the caller. Check ``handle.skipped`` after the
    ``with`` block to see whether this happened.
    """


def _next_attempt(conn: sqlite3.Connection, job_name: str, business_date_str: str | None) -> int:
    """The next attempt number for (job_name, business_date), so that
    repeated job_run() calls for the same key never collide on the
    UNIQUE(job_name, business_date, attempt) constraint."""
    prior = conn.execute(
        "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM job_runs "
        "WHERE job_name=? AND business_date IS ?",
        (job_name, business_date_str),
    ).fetchone()
    return prior["max_attempt"] + 1


class JobRunHandle:
    """Mutable state a job body can update; flushed to the DB on exit."""

    def __init__(self) -> None:
        self.rows_in: int | None = None
        self.rows_written: int | None = None
        self.rows_rejected: int | None = None
        self.metrics: dict = {}
        self.skipped: bool = False
        #: Set True by a job body that completed but produced a
        #: knowingly-incomplete result (e.g. a corporate action it could
        #: not compute a factor for). Recorded as status='degraded' --
        #: distinct from both success and failure, because the run DID
        #: write data and that data IS missing something. Collapsing it
        #: into 'success' is how a known gap becomes invisible.
        self.degraded: bool = False


@contextmanager
def job_run(
    conn: sqlite3.Connection,
    job_name: str,
    *,
    business_date: date | None = None,
) -> Iterator[JobRunHandle]:
    """Record one job_runs row for the duration of the ``with`` block.

    Three possible outcomes, all recorded here:
      - Normal completion -> status='success', or 'degraded' if the
        body set ``handle.degraded`` (it finished and wrote data, but
        knows that data is incomplete).
      - ``raise JobSkipped(...)`` inside the block -> status='skipped_holiday',
        the exception is swallowed (does not propagate), and
        ``handle.skipped`` is set to True for the caller to check.
      - Any other exception -> status='failed' with type/message/traceback
        recorded, then RE-RAISED -- this context manager observes
        failures, it does not swallow them.
    """
    started_at = datetime.now(UTC)
    business_date_str = business_date.isoformat() if business_date else None
    next_attempt = _next_attempt(conn, job_name, business_date_str)

    cursor = conn.execute(
        """INSERT INTO job_runs
               (job_name, business_date, status, started_at, attempt, code_version)
           VALUES (?, ?, 'running', ?, ?, ?)""",
        (job_name, business_date_str, started_at.isoformat(), next_attempt, code_version()),
    )
    run_id = cursor.lastrowid
    handle = JobRunHandle()

    try:
        yield handle
    except JobSkipped:
        conn.execute(
            """UPDATE job_runs SET status='skipped_holiday', finished_at=?, metrics_json=?
               WHERE run_id=?""",
            (datetime.now(UTC).isoformat(), json.dumps(handle.metrics), run_id),
        )
        handle.skipped = True
    except Exception as exc:
        conn.execute(
            """UPDATE job_runs SET status='failed', finished_at=?, error_type=?,
               error_message=?, traceback=?, rows_in=?, rows_written=?, rows_rejected=?,
               metrics_json=?
               WHERE run_id=?""",
            (
                datetime.now(UTC).isoformat(),
                type(exc).__name__,
                str(exc),
                traceback.format_exc(),
                handle.rows_in,
                handle.rows_written,
                handle.rows_rejected,
                json.dumps(handle.metrics),
                run_id,
            ),
        )
        raise
    else:
        conn.execute(
            """UPDATE job_runs SET status=?, finished_at=?, rows_in=?,
               rows_written=?, rows_rejected=?, metrics_json=?
               WHERE run_id=?""",
            (
                "degraded" if handle.degraded else "success",
                datetime.now(UTC).isoformat(),
                handle.rows_in,
                handle.rows_written,
                handle.rows_rejected,
                json.dumps(handle.metrics),
                run_id,
            ),
        )

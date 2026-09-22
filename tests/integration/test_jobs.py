"""Tests for JobRun bookkeeping.

Includes a regression test for a real bug caught by a live ingest run:
job_runs has a UNIQUE(job_name, business_date, attempt) constraint, and
the first implementation always inserted attempt=1, so a second
invocation of the same job for the same date crashed with an
IntegrityError -- exactly the "re-running must always be safe" property
this table exists to support (see module docstring).
"""

from __future__ import annotations

from datetime import date

import pytest

from stk.ingest.jobs import JobSkipped, job_run
from stk.store.db.engine import connect, migrate


@pytest.fixture
def conn(tmp_db_path):
    migrate(tmp_db_path)
    c = connect(tmp_db_path)
    yield c
    c.close()


class TestJobRun:
    def test_successful_run_recorded(self, conn):
        with job_run(conn, "test_job", business_date=date(2026, 9, 17)) as handle:
            handle.rows_in = 10
            handle.rows_written = 10

        row = conn.execute("SELECT * FROM job_runs WHERE job_name='test_job'").fetchone()
        assert row["status"] == "success"
        assert row["attempt"] == 1
        assert row["rows_written"] == 10

    def test_failed_run_recorded_and_exception_reraised(self, conn):
        with pytest.raises(ValueError, match="boom"), job_run(
            conn, "test_job", business_date=date(2026, 9, 17)
        ):
            raise ValueError("boom")

        row = conn.execute("SELECT * FROM job_runs WHERE job_name='test_job'").fetchone()
        assert row["status"] == "failed"
        assert row["error_type"] == "ValueError"
        assert "boom" in row["error_message"]

    def test_rerunning_the_same_job_and_date_does_not_raise(self, conn):
        """The regression case: this must succeed three times in a row,
        each producing a distinct job_runs row via an incrementing
        attempt number."""
        for _ in range(3):
            with job_run(conn, "test_job", business_date=date(2026, 9, 17)) as handle:
                handle.rows_written = 5

        rows = conn.execute(
            "SELECT attempt FROM job_runs WHERE job_name='test_job' ORDER BY attempt"
        ).fetchall()
        assert [r["attempt"] for r in rows] == [1, 2, 3]

    def test_attempt_numbering_is_independent_per_date(self, conn):
        with job_run(conn, "test_job", business_date=date(2026, 9, 17)):
            pass
        with job_run(conn, "test_job", business_date=date(2026, 9, 18)):
            pass

        rows = conn.execute(
            "SELECT business_date, attempt FROM job_runs WHERE job_name='test_job' "
            "ORDER BY business_date"
        ).fetchall()
        assert all(r["attempt"] == 1 for r in rows)

    def test_range_job_with_no_business_date(self, conn):
        """Backfill-style jobs pass business_date=None (a date range, not
        a single day) -- attempt numbering must still work via SQL's
        `IS NULL` semantics, not naive equality."""
        for _ in range(2):
            with job_run(conn, "backfill_job", business_date=None):
                pass

        rows = conn.execute(
            "SELECT attempt FROM job_runs WHERE job_name='backfill_job' ORDER BY attempt"
        ).fetchall()
        assert [r["attempt"] for r in rows] == [1, 2]


class TestStaleRunningReaper:
    """A ``running`` row that never reached a terminal status means the process that owned it
    was killed (OOM, crash, power loss) before job_run() could record an outcome -- observed for
    real: an ``ingest_xbrl`` attempt stuck ``running`` from 2026-09-19, never cleaned up."""

    def _stick_running(self, conn, job_name: str, business_date: date | None = None) -> None:
        """Simulate an interrupted run: a 'running' row with no terminal status, as job_run()
        leaves behind if the process dies mid-body (a real ``with`` block can't be killed from
        inside a test, so this crafts the row job_run() itself would have inserted)."""
        conn.execute(
            """INSERT INTO job_runs (job_name, business_date, status, started_at, attempt,
                   code_version)
               VALUES (?, ?, 'running', '2026-09-19T16:54:30+00:00', 3, 'deadbeef')""",
            (job_name, business_date.isoformat() if business_date else None),
        )

    def test_a_stuck_running_row_is_closed_as_failed_when_the_job_runs_again(self, conn):
        self._stick_running(conn, "ingest_xbrl")
        with job_run(conn, "ingest_xbrl") as handle:
            handle.rows_written = 1

        rows = conn.execute(
            "SELECT attempt, status, error_type, error_message FROM job_runs "
            "WHERE job_name='ingest_xbrl' ORDER BY attempt"
        ).fetchall()
        assert [r["attempt"] for r in rows] == [3, 4]
        stuck, fresh = rows
        assert stuck["status"] == "failed"
        assert stuck["error_type"] == "Interrupted"
        assert "attempt 4" in stuck["error_message"]
        assert fresh["status"] == "success"

    def test_a_finished_run_is_never_touched_by_the_reaper(self, conn):
        with job_run(conn, "test_job", business_date=date(2026, 9, 17)):
            pass
        with job_run(conn, "test_job", business_date=date(2026, 9, 17)):
            pass

        rows = conn.execute(
            "SELECT status FROM job_runs WHERE job_name='test_job'"
        ).fetchall()
        assert [r["status"] for r in rows] == ["success", "success"]

    def test_the_reaper_is_scoped_to_the_job_name_not_other_jobs(self, conn):
        self._stick_running(conn, "ingest_xbrl")
        with job_run(conn, "ingest_fundamentals_sweep"):
            pass

        row = conn.execute(
            "SELECT status FROM job_runs WHERE job_name='ingest_xbrl'"
        ).fetchone()
        assert row["status"] == "running"  # untouched -- a different job started, not this one


class TestJobSkipped:
    def test_records_skipped_status_and_does_not_propagate(self, conn):
        with job_run(conn, "test_job", business_date=date(2026, 1, 26)) as handle:
            raise JobSkipped("not a trading day")

        assert handle.skipped is True
        row = conn.execute("SELECT * FROM job_runs WHERE job_name='test_job'").fetchone()
        assert row["status"] == "skipped_holiday"

    def test_skip_after_partial_work_still_records_skip_not_failure(self, conn):
        """A skip decided partway through a job body (e.g. after an
        initial fetch attempt) must not be misrecorded as a failure."""
        with job_run(conn, "test_job", business_date=date(2026, 1, 26)) as handle:
            handle.rows_in = 0
            raise JobSkipped("exchange has not published yet")

        row = conn.execute("SELECT * FROM job_runs WHERE job_name='test_job'").fetchone()
        assert row["status"] == "skipped_holiday"
        assert row["status"] != "failed"

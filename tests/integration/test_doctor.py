"""Integration tests for `stk doctor`'s health checks, run against the
functions directly (not the CLI wrapper) for speed and precision.
"""

from __future__ import annotations

from datetime import date

import pytest

from stk.ingest.jobs import job_run
from stk.store.db.engine import connect, migrate

LATEST_ATTEMPT_DEGRADED_SQL = """
    SELECT j.job_name, j.business_date, j.status FROM job_runs j
    JOIN (
        SELECT job_name, business_date, MAX(attempt) AS max_attempt
        FROM job_runs GROUP BY job_name, business_date
    ) latest
      ON j.job_name = latest.job_name
     AND j.business_date IS latest.business_date
     AND j.attempt = latest.max_attempt
    WHERE j.status IN ('degraded', 'failed')
"""


@pytest.fixture
def conn(tmp_db_path):
    migrate(tmp_db_path)
    c = connect(tmp_db_path)
    yield c
    c.close()


class TestLatestAttemptOnlyLogic:
    def test_a_failed_attempt_later_fixed_by_a_retry_is_not_flagged(self, conn):
        """Regression case: doctor's original query flagged ANY failed
        row, so a transient failure that a later retry fixed would keep
        showing up as a permanent problem forever."""
        with pytest.raises(ValueError), job_run(
            conn, "flaky_job", business_date=date(2026, 9, 17)
        ):
            raise ValueError("transient")

        with job_run(conn, "flaky_job", business_date=date(2026, 9, 17)):
            pass  # succeeds on retry

        problems = conn.execute(LATEST_ATTEMPT_DEGRADED_SQL).fetchall()
        assert problems == []

    def test_a_currently_failing_job_is_still_flagged(self, conn):
        with pytest.raises(ValueError), job_run(
            conn, "broken_job", business_date=date(2026, 9, 17)
        ):
            raise ValueError("still broken")

        problems = conn.execute(LATEST_ATTEMPT_DEGRADED_SQL).fetchall()
        assert len(problems) == 1
        assert problems[0]["job_name"] == "broken_job"

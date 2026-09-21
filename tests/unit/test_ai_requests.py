"""The AI request queue: how the dashboard asks for a call it is not allowed to make."""

from __future__ import annotations

import sqlite3

import pytest

from stk.store.db.engine import connect, migrate
from stk.store.db.repos import ai_requests


@pytest.fixture
def conn(tmp_db_path):
    migrate(tmp_db_path)
    c = connect(tmp_db_path)
    yield c
    c.close()


KIND, DAY = "evening_review", "2026-09-21"


def a_run(conn) -> int:
    """A real ai_runs row -- ai_requests.run_id has a foreign key to it, deliberately, so a
    request can never point at a run that does not exist."""
    cur = conn.execute(
        "INSERT INTO ai_runs (kind, business_date, model, status, started_at) "
        "VALUES (?,?,'m','success','2026-09-21T18:00:00+00:00')", (KIND, DAY))
    return int(cur.lastrowid)


class TestEnqueue:
    def test_a_request_starts_queued(self, conn):
        req = ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        assert req.status == "queued" and req.business_date == DAY
        assert ai_requests.open_request(conn, KIND, DAY) == req

    def test_pressing_the_button_twice_does_not_buy_two_model_calls(self, conn):
        """The partial unique index is the cost guard; enqueue turns it into a no-op rather
        than an error the user cannot act on."""
        first = ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        second = ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        assert second.request_id == first.request_id
        assert conn.execute("SELECT count(*) AS n FROM ai_requests").fetchone()["n"] == 1

    def test_a_finished_day_can_be_asked_for_again(self, conn):
        first = ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        claimed = ai_requests.claim_next(conn)
        ai_requests.finish(conn, claimed.request_id, status="done", run_id=a_run(conn))
        again = ai_requests.enqueue(conn, kind=KIND, business_date=DAY, force=True)
        assert again.request_id != first.request_id and again.force is True

    def test_different_days_queue_independently(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        ai_requests.enqueue(conn, kind=KIND, business_date="2026-09-22")
        assert conn.execute("SELECT count(*) AS n FROM ai_requests").fetchone()["n"] == 2


class TestClaim:
    def test_claiming_marks_it_running(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        req = ai_requests.claim_next(conn)
        assert req is not None and req.status == "running" and req.started_at is not None

    def test_a_claimed_request_is_not_handed_out_twice(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        assert ai_requests.claim_next(conn) is not None
        assert ai_requests.claim_next(conn) is None

    def test_an_empty_queue_is_none_not_an_error(self, conn):
        assert ai_requests.claim_next(conn) is None

    def test_the_oldest_request_goes_first(self, conn):
        a = ai_requests.enqueue(conn, kind=KIND, business_date="2026-09-20")
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        assert ai_requests.claim_next(conn).request_id == a.request_id

    def test_a_kind_filter_leaves_other_kinds_queued(self, conn):
        ai_requests.enqueue(conn, kind="strategy_lab", business_date=DAY)
        assert ai_requests.claim_next(conn, kind=KIND) is None
        assert ai_requests.claim_next(conn, kind="strategy_lab") is not None

    def test_force_survives_the_round_trip(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY, force=True)
        assert ai_requests.claim_next(conn).force is True


class TestFinish:
    def test_done_clears_the_way_for_a_new_request(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        req = ai_requests.claim_next(conn)
        run_id = a_run(conn)
        ai_requests.finish(conn, req.request_id, status="done", run_id=run_id)
        assert ai_requests.open_request(conn, KIND, DAY) is None
        done = ai_requests.latest(conn, KIND, DAY)
        assert done.status == "done" and done.run_id == run_id and done.finished_at is not None

    def test_a_request_cannot_point_at_a_run_that_does_not_exist(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        req = ai_requests.claim_next(conn)
        with pytest.raises(sqlite3.IntegrityError):
            ai_requests.finish(conn, req.request_id, status="done", run_id=999)

    def test_an_error_records_its_reason(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        req = ai_requests.claim_next(conn)
        ai_requests.finish(conn, req.request_id, status="error", error="boom")
        assert ai_requests.latest(conn, KIND, DAY).error == "boom"

    def test_a_request_cannot_be_finished_into_a_state_that_is_not_one(self, conn):
        ai_requests.enqueue(conn, kind=KIND, business_date=DAY)
        req = ai_requests.claim_next(conn)
        with pytest.raises(ValueError, match="'done' or 'error'"):
            ai_requests.finish(conn, req.request_id, status="queued")

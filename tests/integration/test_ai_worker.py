"""The dashboard -> queue -> worker path, end to end, against a fake model. No network."""

from __future__ import annotations

import pytest

from integration.test_ai_evening import DAY, Model, good_reply
from integration.test_ai_evening import env as evening_env
from integration.test_api import world  # noqa: F401 (fixture)
from stk.ai.client import LlmError
from stk.ai.inputs import build_input
from stk.ai.worker import drain
from stk.store.db.repos import ai_requests

#: The same (conn, ctx, ai, world) fixture the evening-review tests run against: one migrated
#: database, a synthetic lake and a live strategy with picks.
env = evening_env


def queue(conn, day=DAY, **kw):
    return ai_requests.enqueue(conn, kind="evening_review", business_date=day.isoformat(), **kw)


def state(conn, request_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM ai_requests WHERE request_id=?",
                             (request_id,)).fetchone())


class TestDrain:
    def test_a_queued_request_produces_a_brief_and_is_closed(self, env):
        conn, ctx, ai, _ = env
        req = queue(conn)
        model = Model(good_reply(build_input(conn, ctx, ai, DAY)))
        result = drain(conn, ctx, ai, model)

        assert result.handled == 1 and result.outcomes == [(req.request_id, "success")]
        assert model.calls == 1
        row = state(conn, req.request_id)
        assert row["status"] == "done" and row["run_id"] is not None
        assert conn.execute(
            "SELECT count(*) AS n FROM ai_outputs WHERE kind='brief'").fetchone()["n"] == 1

    def test_an_empty_queue_calls_no_model(self, env):
        conn, ctx, ai, _ = env
        model = Model()
        assert drain(conn, ctx, ai, model).handled == 0
        assert model.calls == 0

    def test_a_failed_call_closes_the_request_so_the_day_can_be_asked_for_again(self, env):
        """Left 'running', the partial unique index would block that day forever -- a button
        that silently stops working is worse than one that reports a failure."""
        conn, ctx, ai, _ = env
        req = queue(conn)
        drain(conn, ctx, ai, Model(LlmError("provider is down")))

        row = state(conn, req.request_id)
        assert row["status"] == "error" and row["error"]
        assert ai_requests.open_request(conn, "evening_review", DAY.isoformat()) is None
        assert queue(conn).request_id != req.request_id  # the day is askable again

    def test_a_day_with_no_picks_is_done_not_an_error(self, env):
        """"Nothing to review" is an answer, and it must not read as a broken button."""
        conn, ctx, ai, _ = env
        conn.execute("DELETE FROM picks")
        req = queue(conn)
        model = Model()
        result = drain(conn, ctx, ai, model)

        assert result.outcomes == [(req.request_id, "skipped")]
        assert model.calls == 0  # nothing at all to say, so no spend
        row = state(conn, req.request_id)
        assert row["status"] == "done" and row["error"] == "nothing to review"

    def test_a_forced_request_regenerates_an_existing_brief(self, env):
        conn, ctx, ai, _ = env
        inp = build_input(conn, ctx, ai, DAY)
        queue(conn)
        drain(conn, ctx, ai, Model(good_reply(inp)))

        queue(conn, force=True)
        second = Model(good_reply(inp))
        drain(conn, ctx, ai, second)
        assert second.calls == 1  # the idempotency guard was bypassed, as asked

        queue(conn)  # and without force it is skipped rather than paid for again
        third = Model()
        drain(conn, ctx, ai, third)
        assert third.calls == 0

    def test_the_queue_is_drained_in_order_and_left_empty(self, env):
        conn, ctx, ai, _ = env
        a = queue(conn, day=DAY)
        conn.execute("UPDATE ai_requests SET status='done' WHERE request_id=?", (a.request_id,))
        b = queue(conn, day=DAY)
        result = drain(conn, ctx, ai, Model(good_reply(build_input(conn, ctx, ai, DAY))))
        assert [r for r, _ in result.outcomes] == [b.request_id]
        assert ai_requests.claim_next(conn) is None


class TestSeparationOfPowers:
    def test_the_api_package_cannot_reach_the_ai_package(self):
        """Stated as code, not only in a config file: the button exists BECAUSE this holds."""
        import stk.api.app  # noqa: PLC0415
        import stk.api.services  # noqa: PLC0415

        for module in (stk.api.app, stk.api.services):
            names = {n for n in dir(module) if not n.startswith("_")}
            offenders = {n for n in names if getattr(getattr(module, n, None), "__module__", "")
                         .startswith("stk.ai")}
            assert not offenders, f"{module.__name__} reaches stk.ai via {offenders}"

    def test_queueing_needs_no_model_at_all(self, env):
        """`enqueue` is the API's whole contribution: no client, no key, no call."""
        conn, _ctx, _ai, _ = env
        req = queue(conn)
        assert req.status == "queued"
        assert conn.execute("SELECT count(*) AS n FROM ai_runs").fetchone()["n"] == 0


@pytest.mark.parametrize("status", ["queued", "running"])
def test_only_one_request_per_day_can_be_open(env, status):
    conn, _ctx, _ai, _ = env
    first = queue(conn)
    conn.execute("UPDATE ai_requests SET status=? WHERE request_id=?", (status, first.request_id))
    assert queue(conn).request_id == first.request_id
    assert conn.execute("SELECT count(*) AS n FROM ai_requests").fetchone()["n"] == 1

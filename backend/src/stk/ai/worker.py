"""Execute AI requests the dashboard queued.

The API may ASK for a model call but can never make one: an import-linter contract keeps
``stk.ai`` out of ``stk.api``, so a web request cannot reach a provider however the routes
change. The button therefore writes a row to ``ai_requests`` and this is what carries it out,
in a different process, where calling a model is allowed.

Two properties worth stating, because both are the difference between a queue and a bill:

  * a request is claimed by an UPDATE's own rowcount, so two workers cannot run one request;
  * a request that fails is closed with its reason, not left ``running`` forever -- otherwise
    the partial unique index would block the day from ever being asked for again.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from stk.ai.client import LlmClient
from stk.ai.evening import run_evening_review
from stk.config.ai import AiConfig
from stk.playground.context import PlayCtx
from stk.store.db.repos import ai_requests

#: A review that ran and decided there was nothing to do is a completed request, not an error:
#: "no picks today" is an answer.
DONE_STATUSES = ("success", "skipped")

REVIEW_KIND = "evening_review"


@dataclass
class DrainResult:
    handled: int = 0
    #: (request_id, the review's status) in the order they were run.
    outcomes: list[tuple[int, str]] = field(default_factory=list)


def run_one(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    ai: AiConfig,
    client: LlmClient,
    req: ai_requests.AiRequest,
) -> str:
    """Carry out one claimed request and close it. Returns the review's status."""
    try:
        result = run_evening_review(conn, ctx, ai, client, date.fromisoformat(req.business_date),
                                    force=req.force)
    except Exception as exc:  # a worker must survive one bad request and keep the queue moving
        ai_requests.finish(conn, req.request_id, status="error", error=str(exc))
        return "error"
    # The call itself is already recorded in ai_runs; the request records only that it was
    # carried out, and repeats the reason so the dashboard need not join two tables to say why.
    ai_requests.finish(
        conn, req.request_id,
        status="done" if result.status in DONE_STATUSES else "error",
        run_id=result.run_id, error=result.detail or None,
    )
    return result.status


def drain(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    ai: AiConfig,
    client: LlmClient,
    *,
    on_claim: Callable[[ai_requests.AiRequest], None] | None = None,
    on_done: Callable[[ai_requests.AiRequest, str], None] | None = None,
) -> DrainResult:
    """Run every queued evening review, then return. Never raises on a bad request."""
    out = DrainResult()
    while (req := ai_requests.claim_next(conn, kind=REVIEW_KIND)) is not None:
        if on_claim:
            on_claim(req)
        status = run_one(conn, ctx, ai, client, req)
        out.handled += 1
        out.outcomes.append((req.request_id, status))
        if on_done:
            on_done(req, status)
    return out

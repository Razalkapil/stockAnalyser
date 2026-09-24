"""Execute AI requests the dashboard queued (the evening review and the strategy lab).

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
from pathlib import Path

from stk.ai.client import LlmClient
from stk.ai.evening import run_evening_review
from stk.ai.lab import run_strategy_lab
from stk.config.ai import AiConfig
from stk.config.backtest import BacktestConfig
from stk.config.promotion import PromotionConfig
from stk.playground.context import PlayCtx
from stk.store.db.repos import ai_requests

#: A review that ran and decided there was nothing to do is a completed request, not an error:
#: "no picks today" is an answer.
DONE_STATUSES = ("success", "skipped")

REVIEW_KIND = "evening_review"
LAB_KIND = "strategy_lab"

#: The order kinds are claimed in. A review is seconds and a lab is hours of local backtests, so
#: reviews go first: a brief queued while a lab is waiting must never sit behind it.
KINDS = (REVIEW_KIND, LAB_KIND)


@dataclass(frozen=True)
class WorkerDeps:
    """Everything a queued request may need. The lab wants the promotion gate and the backtest
    config; the playground context has no business knowing about either, so they live here."""

    ctx: PlayCtx
    ai: AiConfig
    client: LlmClient
    promo: PromotionConfig
    backtest_cfg: BacktestConfig
    parquet_root: Path


@dataclass
class DrainResult:
    handled: int = 0
    #: (request_id, the review's status) in the order they were run.
    outcomes: list[tuple[int, str]] = field(default_factory=list)


def _execute(conn: sqlite3.Connection, deps: WorkerDeps, req: ai_requests.AiRequest) -> tuple[
        str, int | None, str]:
    """Run one request's job. Returns (status, run_id, detail). May raise; the caller closes."""
    day = date.fromisoformat(req.business_date)
    if req.kind == REVIEW_KIND:
        r = run_evening_review(conn, deps.ctx, deps.ai, deps.client, day, force=req.force)
        return r.status, r.run_id, r.detail
    if req.kind == LAB_KIND:
        lab = run_strategy_lab(
            conn, deps.ai, deps.client, parquet_root=deps.parquet_root, cfg=deps.backtest_cfg,
            promo=deps.promo, day=day, force=req.force)
        return lab.status, lab.run_id, lab.detail
    # Not a job this worker knows. Raise so the request is CLOSED as an error: leaving it open
    # would hold its (kind, day) slot in the partial unique index forever.
    raise ValueError(f"the worker has no handler for request kind {req.kind!r}")


def run_one(conn: sqlite3.Connection, deps: WorkerDeps, req: ai_requests.AiRequest) -> str:
    """Carry out one claimed request and close it. Returns the job's status."""
    try:
        status, run_id, detail = _execute(conn, deps, req)
    except Exception as exc:  # a worker must survive one bad request and keep the queue moving
        ai_requests.finish(conn, req.request_id, status="error", error=str(exc))
        return "error"
    # The call itself is already recorded in ai_runs; the request records only that it was
    # carried out, and repeats the reason so the dashboard need not join two tables to say why.
    ai_requests.finish(
        conn, req.request_id,
        status="done" if status in DONE_STATUSES else "error",
        run_id=run_id, error=detail or None,
    )
    return status


def _claim(conn: sqlite3.Connection) -> ai_requests.AiRequest | None:
    """The next queued request, reviews before labs, oldest first within a kind."""
    for kind in KINDS:
        req = ai_requests.claim_next(conn, kind=kind)
        if req is not None:
            return req
    # A queued row of a kind we do not list would never be claimed above and would block its
    # (kind, day) slot for good -- take it too, so run_one can close it with an explicit error.
    return ai_requests.claim_next(conn)


def drain(
    conn: sqlite3.Connection,
    deps: WorkerDeps,
    *,
    on_claim: Callable[[ai_requests.AiRequest], None] | None = None,
    on_done: Callable[[ai_requests.AiRequest, str], None] | None = None,
) -> DrainResult:
    """Run every queued request, then return. Never raises on a bad request.

    Re-claims from the top each time, so a review queued while a lab is running is served
    before the NEXT lab, not after the whole backlog.
    """
    out = DrainResult()
    while (req := _claim(conn)) is not None:
        if on_claim:
            on_claim(req)
        status = run_one(conn, deps, req)
        out.handled += 1
        out.outcomes.append((req.request_id, status))
        if on_done:
            on_done(req, status)
    return out

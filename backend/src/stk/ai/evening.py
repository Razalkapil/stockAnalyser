"""The evening review: one model call per day, validated, stored, and NEVER blocking.

  build input (DB only) -> one call (validated, one retry) -> semantic checks -> store

SEMANTIC CHECKS are what a schema cannot express and what stops a confident fabrication reaching
the dashboard: every pick_id and symbol in the reply must have been in the input, ranks within a
horizon must be a clean 1..n, and every pick must be ranked exactly once.

NEVER BLOCKS. Any failure -- no key, a network error, an invalid reply -- is recorded as an
``ai_runs`` row with its reason and returned as a result; it is never raised. The nightly pipeline
carries on and the UI shows the brief as pending, which is honest.

IDEMPOTENT PER DAY, BUT ONLY FOR A DAY THAT RANKED PICKS. A review that ranked the day's picks is
not repeated (that would be spend for nothing) unless ``force``. A pick-less brief -- written from
index moves, open positions and what the NOT-promoted strategies would have picked -- is always
re-runnable: it describes a moving target and nothing about it was settled. A failed one is
retried on the next run.

PREVIEWS ARE CONTEXT, NEVER CANDIDATES. When nothing is promoted the input carries would-be picks
from ``strategy_previews`` with NO identifiers, so there is nothing for the model to rank and
nothing ``_store`` (which writes by pick_id) can write back onto. ``semantic_problems`` closes the
loop: with ``pick_ids`` empty, any ranked entry at all fails "was not in the input".
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

from stk.ai.client import LlmClient, StructuredResult, call_structured, prompt_json
from stk.ai.inputs import ReviewInput, build_input
from stk.ai.prompts import EVENING_SYSTEM
from stk.ai.runs import record_run
from stk.ai.schemas import EveningReview
from stk.config.ai import AiConfig
from stk.playground.context import PlayCtx
from stk.store.db.engine import transaction
from stk.store.db.repos import ai_briefs


@dataclass
class ReviewResult:
    status: str  # success | invalid_output | failed | skipped
    run_id: int | None
    detail: str = ""
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def semantic_problems(review: EveningReview, inp: ReviewInput) -> list[str]:
    problems: list[str] = []
    seen: set[int] = set()
    for h in review.horizons:
        ranks = sorted(rp.rank for rp in h.ranked)
        if ranks != list(range(1, len(ranks) + 1)):
            problems.append(f"ranks for {h.horizon} must be exactly 1..{len(ranks)}, got {ranks}")
        for rp in h.ranked:
            if rp.pick_id not in inp.pick_ids:
                problems.append(f"pick_id {rp.pick_id} was not in the input")
            elif inp.pick_ids[rp.pick_id] != h.horizon:
                problems.append(f"pick_id {rp.pick_id} belongs to {inp.pick_ids[rp.pick_id]}, "
                                f"not {h.horizon}")
            if rp.pick_id in seen:
                problems.append(f"pick_id {rp.pick_id} is ranked twice")
            seen.add(rp.pick_id)
    missing = sorted(set(inp.pick_ids) - seen)
    if missing:
        problems.append(f"these pick_ids were not ranked: {missing}")
    for group in (review.notable_picks, review.position_notes):
        for n in group:
            if n.symbol not in inp.symbols:
                problems.append(f"symbol {n.symbol!r} was not in the input")
    return problems


def _record(conn: sqlite3.Connection, ai: AiConfig, day: date, res: StructuredResult,
            **kw: object) -> tuple[int, float | None]:
    return record_run(conn, ai, kind="evening_review", business_date=day.isoformat(), res=res,
                      **kw)  # type: ignore[arg-type]


def _store(conn: sqlite3.Connection, run_id: int, day: date, review: EveningReview) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO ai_outputs (run_id, kind, business_date, payload_json, created_at) "
        "VALUES (?, 'brief', ?, ?, ?)",
        (run_id, day.isoformat(), review.model_dump_json(), now))
    # The reasoning and conflicts also land on the picks, so the Today cards can show them.
    for h in review.horizons:
        for rp in h.ranked:
            conn.execute("UPDATE picks SET ai_reason=?, conflict=? WHERE pick_id=?",
                         (rp.explanation, rp.conflict, rp.pick_id))


def _already_reviewed(conn: sqlite3.Connection, day: date) -> bool:
    """Is the day DONE, or only written up? Only a brief that actually ranked picks settles it.

    Derived from the stored payload rather than a column: nothing needs writing to know this,
    and a second copy is a second thing that can be wrong.
    """
    payload = ai_briefs.latest_payload(conn, day.isoformat())
    return payload is not None and ai_briefs.ranked_pick_count(payload) > 0


def run_evening_review(conn: sqlite3.Connection, ctx: PlayCtx, ai: AiConfig, client: LlmClient,
                       day: date, *, force: bool = False) -> ReviewResult:
    started = datetime.now(UTC)
    if not ai.enabled:
        return ReviewResult("skipped", None, "AI is disabled in config/ai.yaml")

    if not force and _already_reviewed(conn, day):
        return ReviewResult("skipped", None,
                            f"a review that ranked picks already exists for {day} (use --force)")

    try:
        inp = build_input(conn, ctx, ai, day)
    except Exception as exc:  # never block the pipeline, whatever went wrong assembling input
        with transaction(conn):
            empty = StructuredResult(None, 0, 0, 0, ai.model, "", error=str(exc))
            rid, _ = _record(conn, ai, day, empty, prompt_sha="", started=started,
                             status="failed", error=f"could not assemble input: {exc}")
        return ReviewResult("failed", rid, f"could not assemble input: {exc}")

    if not inp.has_content:
        # No picks, no previews, no open positions, no index moves: a call could only produce
        # invented commentary. Record the skip so the day is accounted for.
        with transaction(conn):
            rid, _ = _record(conn, ai, day, StructuredResult(None, 0, 0, 0, ai.model, ""),
                             prompt_sha="", started=started, status="skipped",
                             error="nothing to review: no picks, no strategy previews, "
                                   "no open positions and no index moves")
        return ReviewResult("skipped", rid, "nothing to review")

    user = prompt_json(inp.payload)
    prompt_sha = hashlib.sha256((EVENING_SYSTEM + user).encode()).hexdigest()
    res = call_structured(client, system=EVENING_SYSTEM, user=user, schema=EveningReview,
                          max_tokens=ai.max_tokens, max_input_chars=ai.max_input_chars,
                          semantic_check=lambda r: semantic_problems(r, inp))

    with transaction(conn):
        if isinstance(res.value, EveningReview):
            rid, cost = _record(conn, ai, day, res, prompt_sha=prompt_sha, started=started,
                                status="success", error=None)
            _store(conn, rid, day, res.value)
            return ReviewResult("success", rid, "", cost, res.input_tokens, res.output_tokens)
        failed_call = (res.error or "").startswith(("call failed", "the model declined"))
        status = "failed" if failed_call else "invalid_output"
        rid, cost = _record(conn, ai, day, res, prompt_sha=prompt_sha, started=started,
                            status=status, error=res.error)
    return ReviewResult(status, rid, res.error or "", cost, res.input_tokens, res.output_tokens)

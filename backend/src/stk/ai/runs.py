"""Recording an AI call in ``ai_runs`` -- one place, so every kind is logged the same way."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from stk.ai.client import StructuredResult
from stk.config.ai import AiConfig
from stk.core.version import code_version


def record_run(
    conn: sqlite3.Connection,
    ai: AiConfig,
    *,
    kind: str,
    business_date: str | None,
    res: StructuredResult,
    prompt_sha: str,
    started: datetime,
    status: str,
    error: str | None,
) -> tuple[int, float | None]:
    """Insert the row; returns (run_id, estimated cost in USD or None if the model is unpriced)."""
    cost = ai.estimate_cost_usd(res.model or ai.model, res.input_tokens, res.output_tokens)
    cur = conn.execute(
        """INSERT INTO ai_runs (kind, business_date, model, status, attempts, input_tokens,
               output_tokens, cost_usd_est, prompt_sha256, response_text, error, started_at,
               finished_at, code_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (kind, business_date, res.model or ai.model, status, res.attempts, res.input_tokens,
         res.output_tokens, cost, prompt_sha, res.raw_text[:20000], error,
         started.isoformat(), datetime.now(UTC).isoformat(), code_version()),
    )
    return int(cur.lastrowid or 0), cost

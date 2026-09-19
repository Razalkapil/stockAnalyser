"""The weekly strategy lab.

  input (DB + the DSL's own catalogue and schema) -> ONE model call (validated, one retry)
     -> per idea: parse -> validate -> register -> walk-forward backtest -> promotion gate
     -> a stored proposal awaiting a person's decision

THE AI NEVER SUPPLIES CODE. It supplies DSL JSON, which our own strict models and semantic
validator either accept or reject; an accepted spec is only ever *interpreted*. Even an accepted,
backtested, gate-passing proposal changes nothing until a person approves it in the UI.

EACH IDEA IS INDEPENDENT. One invalid spec, or one backtest that errors, becomes that proposal's
recorded status; it does not lose the others and it does not fail the run. The run as a whole
never raises (it must not block anything), and a failed call is an ``ai_runs`` row.

DEMOTIONS are stored as proposals and change nothing: a strategy is retired only by an explicit,
confirmed human action.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from stk.ai.client import LlmClient, call_structured, prompt_json
from stk.ai.lab_inputs import build_lab_input
from stk.ai.lab_schemas import LabReply
from stk.ai.prompts import LAB_SYSTEM
from stk.ai.runs import record_run
from stk.config.ai import AiConfig
from stk.config.backtest import BacktestConfig
from stk.config.horizons import load_horizons
from stk.config.promotion import PromotionConfig
from stk.domain.dsl.model import StrategySpec
from stk.domain.dsl.validate import HorizonWindow, param_combinations, validate_spec
from stk.store.db.engine import transaction
from stk.strategies.promotion import promote
from stk.strategies.proposals import create_proposal
from stk.strategies.repo import get_strategy, list_strategies, register_spec
from stk.strategies.runner import lake_span

MAX_NEW_PROPOSALS = 3
#: An AI-proposed strategy is walk-forwarded, so its parameter grid is capped tighter than a
#: hand-written one: every combination is a full backtest run.
MAX_AI_GRID = 8
DEMOTABLE = ("live", "decaying")


@dataclass
class LabResult:
    status: str  # success | invalid_output | failed | skipped
    run_id: int | None = None
    detail: str = ""
    proposals: list[tuple[int, str]] = field(default_factory=list)  # (proposal_id, status)
    cost_usd: float | None = None


def spec_problems(raw: str, existing_slugs: set[str], horizons: dict[str, HorizonWindow]
                  ) -> tuple[StrategySpec | None, list[str]]:
    """Everything that can be wrong with a proposed spec, checked without running anything."""
    try:
        spec = StrategySpec.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:  # json errors are ValueErrors
        return None, [f"not a valid strategy spec: {exc}"]
    problems = list(validate_spec(spec, horizons))
    if spec.slug in existing_slugs:
        problems.append(f"slug {spec.slug!r} already exists")
    if len(param_combinations(spec)) > MAX_AI_GRID:
        problems.append(f"the parameter grid has more than {MAX_AI_GRID} combinations")
    return (spec if not problems else None), problems


def lab_problems(reply: LabReply, strategies: dict[str, str], horizons: dict[str, HorizonWindow]
                 ) -> list[str]:
    """Semantic problems in a reply. Drives the retry; per-idea failures are handled later."""
    problems: list[str] = []
    if len(reply.proposals) > MAX_NEW_PROPOSALS:
        problems.append(f"at most {MAX_NEW_PROPOSALS} proposals are allowed")
    seen: set[str] = set(strategies)
    for i, idea in enumerate(reply.proposals):
        spec, errs = spec_problems(idea.spec_json, seen, horizons)
        if spec is not None:
            seen.add(spec.slug)
        problems += [f"proposal {i} ({idea.title!r}): {e}" for e in errs]
    for d in reply.demotions:
        status = strategies.get(d.strategy)
        if status is None:
            problems.append(f"demotion names {d.strategy!r}, which is not a strategy")
        elif status not in DEMOTABLE:
            problems.append(f"{d.strategy!r} is {status}; only live or decaying strategies can be "
                            "demoted")
    return problems


def run_strategy_lab(
    conn: sqlite3.Connection,
    ai: AiConfig,
    client: LlmClient,
    *,
    parquet_root: Path,
    cfg: BacktestConfig,
    promo: PromotionConfig,
    day: date,
    exchange: str = "NSE",
) -> LabResult:
    started = datetime.now(UTC)
    if not ai.enabled:
        return LabResult("skipped", detail="AI is disabled in config/ai.yaml")

    horizons = load_horizons()
    strategies = {s.slug: s.status for s in list_strategies(conn)}
    try:
        payload = build_lab_input(conn)
    except Exception as exc:  # never block, whatever went wrong
        return LabResult("failed", detail=f"could not assemble input: {exc}")

    user = prompt_json(payload)
    sha = hashlib.sha256((LAB_SYSTEM + user).encode()).hexdigest()
    res = call_structured(client, system=LAB_SYSTEM, user=user, schema=LabReply,
                          max_tokens=ai.max_tokens, max_input_chars=ai.max_input_chars,
                          keep_on_semantic_failure=True,
                          semantic_check=lambda r: lab_problems(r, strategies, horizons))

    if not isinstance(res.value, LabReply):
        failed_call = (res.error or "").startswith(("call failed", "the model declined"))
        with transaction(conn):
            rid, cost = record_run(conn, ai, kind="strategy_lab", business_date=day.isoformat(),
                                   res=res, prompt_sha=sha, started=started,
                                   status="failed" if failed_call else "invalid_output",
                                   error=res.error)
        return LabResult("failed" if failed_call else "invalid_output", rid, res.error or "",
                         cost_usd=cost)

    with transaction(conn):
        rid, cost = record_run(conn, ai, kind="strategy_lab", business_date=day.isoformat(),
                               res=res, prompt_sha=sha, started=started, status="success",
                               error=None)
    out = LabResult("success", rid, cost_usd=cost)
    span = lake_span(parquet_root, exchange)
    day_s = day.isoformat()

    for idea in res.value.proposals[:MAX_NEW_PROPOSALS]:
        existing = {s.slug for s in list_strategies(conn)}
        spec, errs = spec_problems(idea.spec_json, existing, horizons)
        if spec is None:
            pid = create_proposal(conn, ai_run_id=rid, business_date=day_s, type_="new",
                                  title=idea.title, rationale=idea.rationale, status="invalid",
                                  spec_json=idea.spec_json, validation_errors=errs,
                                  status_note="rejected before any backtest: " + errs[0])
            out.proposals.append((pid, "invalid"))
            continue
        try:
            if span is None:
                raise ValueError("the price lake is empty")
            strategy_id, _vid, _new = register_spec(conn, spec, origin="ai")
            row, report, run_id = promote(
                conn, spec.slug, parquet_root=parquet_root, cfg=cfg, promo=promo,
                exchange=exchange, start=span.first, end=span.last)
        except Exception as exc:  # one broken backtest must not sink the rest
            registered = get_strategy(conn, spec.slug)
            pid = create_proposal(
                conn, ai_run_id=rid, business_date=day_s, type_="new", title=idea.title,
                rationale=idea.rationale, status="backtest_error", spec_json=idea.spec_json,
                strategy_id=registered.strategy_id if registered else None,
                status_note=f"the backtest could not run: {exc}")
            out.proposals.append((pid, "backtest_error"))
            continue
        status = {"pass": "awaiting_approval", "fail": "rejected_by_gate"}.get(
            report.verdict, "insufficient_evidence")
        pid = create_proposal(
            conn, ai_run_id=rid, business_date=day_s, type_="new", title=idea.title,
            rationale=idea.rationale, status=status, spec_json=idea.spec_json,
            strategy_id=strategy_id, backtest_run_id=run_id, gate_verdict=report.verdict,
            status_note=row.status_reason)
        out.proposals.append((pid, status))

    for d in res.value.demotions:
        target = get_strategy(conn, d.strategy)
        if target is None or target.status not in DEMOTABLE:
            continue  # lab_problems already told the model; do not store a nonsense proposal
        if conn.execute("SELECT 1 FROM strategy_proposals WHERE type='demote' AND target_slug=? "
                        "AND status='awaiting_approval'", (d.strategy,)).fetchone():
            continue  # one open recommendation per strategy is enough
        pid = create_proposal(conn, ai_run_id=rid, business_date=day_s, type_="demote",
                              title=f"Retire {target.name}", rationale=d.rationale,
                              status="awaiting_approval", target_slug=d.strategy)
        out.proposals.append((pid, "awaiting_approval"))

    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO ai_outputs (run_id, kind, business_date, payload_json, created_at) "
        "VALUES (?, 'proposal', ?, ?, ?)",
        (rid, day_s, json.dumps({"reply": res.value.model_dump(), "stored": out.proposals}), now))
    return out

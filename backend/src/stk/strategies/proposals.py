"""Strategy proposals: storage and the human decision on them.

Lives in ``strategies`` (not ``ai``) so the API and CLI can list and decide proposals without
importing anything that can call a model.

THE RULES A DECISION FOLLOWS
  approve a NEW proposal   only if it passed the promotion gate -- no exceptions, including for a
                           person (the brief: "the same gate applies to seed and AI-proposed
                           strategies"). Goes live.
  approve a DEMOTION       retires the target strategy; requires ``confirm=True``.
  dismiss                  never changes a live strategy. For a NEW proposal it retires the
                           candidate the backtest created, so it stops appearing as a candidate.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from stk.store.db.engine import transaction
from stk.strategies.repo import get_strategy, set_status

DECIDABLE = ("awaiting_approval",)


class ProposalError(ValueError):
    pass


@dataclass
class ProposalRow:
    proposal_id: int
    type: str
    title: str
    rationale: str
    status: str
    status_note: str | None
    business_date: str
    target_slug: str | None
    strategy_slug: str | None
    spec: dict[str, Any] | None
    validation_errors: list[str]
    gate_verdict: str | None
    backtest_run_id: int | None


def create_proposal(
    conn: sqlite3.Connection,
    *,
    ai_run_id: int | None,
    business_date: str,
    type_: str,
    title: str,
    rationale: str,
    status: str,
    target_slug: str | None = None,
    spec_json: str | None = None,
    strategy_id: int | None = None,
    validation_errors: list[str] | None = None,
    backtest_run_id: int | None = None,
    gate_verdict: str | None = None,
    status_note: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO strategy_proposals (ai_run_id, business_date, type, title, rationale,
               target_slug, spec_json, strategy_id, validation_errors_json, backtest_run_id,
               gate_verdict, status, status_note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ai_run_id, business_date, type_, title, rationale, target_slug, spec_json, strategy_id,
         json.dumps(validation_errors or []), backtest_run_id, gate_verdict, status, status_note,
         datetime.now(UTC).isoformat()),
    )
    return int(cur.lastrowid or 0)


def _row(r: sqlite3.Row, slug: str | None) -> ProposalRow:
    return ProposalRow(
        r["proposal_id"], r["type"], r["title"], r["rationale"], r["status"], r["status_note"],
        r["business_date"], r["target_slug"], slug,
        json.loads(r["spec_json"]) if r["spec_json"] else None,
        json.loads(r["validation_errors_json"] or "[]"), r["gate_verdict"], r["backtest_run_id"])


def list_proposals(conn: sqlite3.Connection, *, limit: int = 30) -> list[ProposalRow]:
    rows = conn.execute(
        """SELECT p.*, s.slug AS strategy_slug FROM strategy_proposals p
           LEFT JOIN strategies s ON s.strategy_id = p.strategy_id
           ORDER BY CASE p.status WHEN 'awaiting_approval' THEN 0 ELSE 1 END, p.proposal_id DESC
           LIMIT ?""", (limit,)).fetchall()
    return [_row(r, r["strategy_slug"]) for r in rows]


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM strategy_proposals WHERE proposal_id=?",
                       (proposal_id,)).fetchone()
    if row is None:
        raise ProposalError(f"no proposal {proposal_id}")
    return row


def recent_titles(conn: sqlite3.Connection, weeks: int = 8) -> list[str]:
    """What the lab already proposed lately, so it is not asked for the same idea twice."""
    return [r[0] for r in conn.execute(
        "SELECT title FROM strategy_proposals WHERE created_at >= datetime('now', ?) "
        "ORDER BY proposal_id DESC", (f"-{weeks * 7} day",))]


def _decide(conn: sqlite3.Connection, proposal_id: int, status: str, note: str) -> None:
    conn.execute("UPDATE strategy_proposals SET status=?, status_note=?, decided_at=? "
                 "WHERE proposal_id=?", (status, note, datetime.now(UTC).isoformat(), proposal_id))


def approve(conn: sqlite3.Connection, proposal_id: int, *, confirm: bool = False) -> None:
    p = get_proposal(conn, proposal_id)
    if p["status"] not in DECIDABLE:
        raise ProposalError(f"proposal {proposal_id} is {p['status']}, not awaiting approval")
    with transaction(conn):
        if p["type"] == "new":
            if p["gate_verdict"] != "pass" or p["strategy_id"] is None:
                raise ProposalError("only a proposal that passed the promotion gate can go live "
                                    "-- no exceptions, including for a person")
            set_status(conn, p["strategy_id"], "live", actor="user",
                       reason=f"approved AI proposal #{proposal_id}: {p['title']}",
                       backtest_run_id=p["backtest_run_id"])
        else:
            if not confirm:
                raise ProposalError("retiring a strategy needs explicit confirmation")
            target = get_strategy(conn, p["target_slug"] or "")
            if target is None:
                raise ProposalError(f"the target strategy {p['target_slug']!r} no longer exists")
            set_status(conn, target.strategy_id, "retired", actor="user",
                       reason=f"approved AI demotion #{proposal_id}: {p['rationale'][:200]}")
        _decide(conn, proposal_id, "approved", "approved in the UI")


def dismiss(conn: sqlite3.Connection, proposal_id: int) -> None:
    p = get_proposal(conn, proposal_id)
    if p["status"] in ("approved", "dismissed"):
        raise ProposalError(f"proposal {proposal_id} is already {p['status']}")
    with transaction(conn):
        if p["type"] == "new" and p["strategy_id"] is not None:
            set_status(conn, p["strategy_id"], "retired", actor="user",
                       reason=f"dismissed AI proposal #{proposal_id}")
        _decide(conn, proposal_id, "dismissed", "dismissed in the UI")

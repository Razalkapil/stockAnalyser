"""Strategy registry: strategies, immutable versions, and status history.

A spec is registered by its content hash. Registering the same rules twice is
a no-op that returns the existing version; changing a single rule makes a new
version. Versions are never edited, so any backtest run stays attributable to
exactly the rules it ran.

Every status change is recorded in ``strategy_status_events`` with who did it
(system / gate / user) and why. A status is never changed silently.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import transaction

STATUSES = ("candidate", "live", "decaying", "retired", "rejected")


@dataclass(frozen=True)
class StrategyRow:
    strategy_id: int
    slug: str
    name: str
    horizon: str
    origin: str
    status: str
    status_reason: str | None
    latest_version_id: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(spec: StrategySpec) -> str:
    """Stable serialisation so equal rules always hash equal."""
    return json.dumps(spec.model_dump(mode="json", by_alias=True), sort_keys=True,
                      separators=(",", ":"))


def register_spec(
    conn: sqlite3.Connection, spec: StrategySpec, *, origin: str
) -> tuple[int, int, bool]:
    """Insert the strategy (if new) and this spec as a version (if new).

    Returns (strategy_id, version_id, created_new_version).
    """
    body = canonical_json(spec)
    sha = hashlib.sha256(body.encode()).hexdigest()
    with transaction(conn):
        row = conn.execute(
            "SELECT strategy_id FROM strategies WHERE slug=?", (spec.slug,)
        ).fetchone()
        if row is None:
            now = _now()
            cur = conn.execute(
                """INSERT INTO strategies (slug, name, horizon, origin, status, status_reason,
                       status_changed_at, created_at)
                   VALUES (?,?,?,?, 'candidate', 'registered, not yet gated', ?, ?)""",
                (spec.slug, spec.name, spec.horizon.value, origin, now, now),
            )
            strategy_id = int(cur.lastrowid or 0)
            conn.execute(
                """INSERT INTO strategy_status_events (strategy_id, from_status, to_status,
                       actor, reason, created_at) VALUES (?, NULL, 'candidate', 'system',
                       'registered', ?)""",
                (strategy_id, now),
            )
        else:
            strategy_id = int(row["strategy_id"])

        existing = conn.execute(
            "SELECT version_id FROM strategy_versions WHERE strategy_id=? AND spec_sha256=?",
            (strategy_id, sha),
        ).fetchone()
        if existing is not None:
            return strategy_id, int(existing["version_id"]), False
        nxt = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM strategy_versions WHERE strategy_id=?",
            (strategy_id,),
        ).fetchone()["v"]
        cur = conn.execute(
            """INSERT INTO strategy_versions (strategy_id, version, spec_json, spec_sha256,
                   created_at) VALUES (?,?,?,?,?)""",
            (strategy_id, nxt, body, sha, _now()),
        )
        return strategy_id, int(cur.lastrowid or 0), True


def get_strategy(conn: sqlite3.Connection, slug: str) -> StrategyRow | None:
    row = conn.execute(
        """SELECT s.*, (SELECT version_id FROM strategy_versions v WHERE v.strategy_id=s.strategy_id
                        ORDER BY version DESC LIMIT 1) AS latest_version_id
           FROM strategies s WHERE s.slug=?""",
        (slug,),
    ).fetchone()
    return _to_row(row) if row else None


def list_strategies(conn: sqlite3.Connection) -> list[StrategyRow]:
    rows = conn.execute(
        """SELECT s.*, (SELECT version_id FROM strategy_versions v WHERE v.strategy_id=s.strategy_id
                        ORDER BY version DESC LIMIT 1) AS latest_version_id
           FROM strategies s ORDER BY s.horizon, s.slug"""
    ).fetchall()
    return [_to_row(r) for r in rows]


def _to_row(r: sqlite3.Row) -> StrategyRow:
    return StrategyRow(r["strategy_id"], r["slug"], r["name"], r["horizon"], r["origin"],
                       r["status"], r["status_reason"], r["latest_version_id"])


def load_spec(conn: sqlite3.Connection, version_id: int) -> StrategySpec:
    row = conn.execute("SELECT spec_json FROM strategy_versions WHERE version_id=?",
                       (version_id,)).fetchone()
    if row is None:
        raise KeyError(f"no strategy version {version_id}")
    return StrategySpec.model_validate_json(row["spec_json"])


def set_status(
    conn: sqlite3.Connection,
    strategy_id: int,
    new_status: str,
    *,
    actor: str,
    reason: str,
    backtest_run_id: int | None = None,
) -> bool:
    """Change a strategy's status and record the event. Returns False if the status is unchanged
    (the reason text is still refreshed, without an event)."""
    if new_status not in STATUSES:
        raise ValueError(f"unknown status {new_status!r}")
    row = conn.execute(
        "SELECT status FROM strategies WHERE strategy_id=?", (strategy_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no strategy {strategy_id}")
    if row["status"] == new_status:
        # Same status, but the REASON may have changed (a candidate that a later gate run still
        # could not decide must say why, not keep its stale "registered, not yet gated").
        # Only the text is updated -- no status event, because the status did not change.
        conn.execute("UPDATE strategies SET status_reason=? WHERE strategy_id=?",
                     (reason, strategy_id))
        return False
    now = _now()
    with transaction(conn):
        conn.execute(
            "UPDATE strategies SET status=?, status_reason=?, status_changed_at=? "
            "WHERE strategy_id=?",
            (new_status, reason, now, strategy_id),
        )
        conn.execute(
            """INSERT INTO strategy_status_events (strategy_id, from_status, to_status, actor,
                   reason, backtest_run_id, created_at) VALUES (?,?,?,?,?,?,?)""",
            (strategy_id, row["status"], new_status, actor, reason, backtest_run_id, now),
        )
    return True

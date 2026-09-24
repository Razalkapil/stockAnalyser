"""Stored evening-review briefs, and the one fact both sides of the wall derive from them.

``stk.ai`` writes a brief and ``stk.api`` serves it, and they are peers in the layering contract
(``stk.api | stk.ai``), so neither may import the other. This module sits in ``stk.store``, below
both -- the same arrangement ``ai_requests`` uses for the request queue.

The fact they must agree on is COVERAGE: did this brief actually rank picks, or is it the
pick-less market brief written from previews, positions and index moves? Nothing is stored to say
so, and nothing needs to be: the answer is in the payload the model already returned. Storing a
second copy would be a second thing that can be wrong (cf. cash, which is always the last
``cash_ledger.balance_after``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any, Literal

Coverage = Literal["picks", "preview"]

BRIEF_KIND = "brief"


def ranked_pick_count(payload: Mapping[str, Any]) -> int:
    """How many picks a brief actually ranked.

    NOT ``len(payload["horizons"])``: a reply of ``[{"horizon": "swing", "ranked": []}]`` passes
    every semantic check (an empty rank list is trivially a clean 1..0 sequence), so a non-empty
    ``horizons`` does not prove a single pick was ranked.
    """
    return sum(len(h.get("ranked") or []) for h in (payload.get("horizons") or []))


def coverage_of(payload: Mapping[str, Any]) -> Coverage:
    return "picks" if ranked_pick_count(payload) else "preview"


def _parse(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:  # a brief we cannot read is a brief we do not have
        return None
    return parsed if isinstance(parsed, dict) else None


def latest_payload(conn: sqlite3.Connection, business_date: str) -> dict[str, Any] | None:
    """The newest stored brief for a day, or None. Newest wins everywhere: a day reviewed again
    after a strategy was promoted must read as the picks brief, not the preview one."""
    row = conn.execute(
        "SELECT payload_json FROM ai_outputs WHERE kind=? AND business_date=? "
        "ORDER BY output_id DESC LIMIT 1", (BRIEF_KIND, business_date)).fetchone()
    return None if row is None else _parse(row["payload_json"])


def coverage_since(conn: sqlite3.Connection, since: str) -> dict[str, Coverage]:
    """business_date -> coverage for every day with a readable brief at or after ``since``.
    Sorted ascending so the newest row for a day overwrites older ones."""
    out: dict[str, Coverage] = {}
    for r in conn.execute(
        "SELECT business_date, payload_json FROM ai_outputs WHERE kind=? AND business_date >= ? "
        "ORDER BY output_id", (BRIEF_KIND, since)):
        parsed = _parse(r["payload_json"])
        if parsed is not None:
            out[r["business_date"]] = coverage_of(parsed)
    return out

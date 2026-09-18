"""Fetch, persist, parse and store the XBRL behind each filing-metadata snapshot.

Flow for every ``fundamentals_snapshots`` row (statement_type='meta') that has
an XBRL link and no ``fundamentals_parse_status`` yet:

    fetch (provider) -> persist raw bytes (content-addressed) -> parse
        -> write line items + a parse-status row

Rules, in the order they matter:
  * RAW BYTES FIRST. The document is on disk and in ``raw_artifacts`` before
    the parser sees it, so a parser fix means re-parsing, never re-fetching.
  * BANKS ARE SKIPPED WITHOUT A FETCH. NSE marks them ``bank: Y``; their
    taxonomy differs. Recorded as ``unsupported_format`` (reason: bank) so
    they are counted, not lost.
  * A TRANSIENT FAILURE IS NOT RECORDED. A network error leaves the row
    unparsed so the next run retries it, and marks the job ``degraded``. A
    DEFINITIVE outcome (unsupported / malformed / partial) IS recorded, so it
    is not refetched forever.
  * Line items are stored only for ``parsed`` and ``partial`` results, and a
    value that was not reported is never stored as zero.

Re-running is always safe (``job_runs`` is observability, not a lock).
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog

from stk.core.errors import ProviderError
from stk.ingest.jobs import job_run
from stk.ingest.raw_store import persist_document
from stk.ingest.xbrl import PARSER_VERSION, XbrlError, XbrlFacts, parse_xbrl
from stk.providers.registry import get_fundamentals_provider
from stk.store.db.engine import connect

log = structlog.get_logger(__name__)


class XbrlIngestResult:
    def __init__(self) -> None:
        self.attempted = 0
        self.parsed = 0
        self.partial = 0
        self.unsupported = 0
        self.malformed = 0
        self.transient_failures = 0
        self.line_items = 0


def _pending(conn: sqlite3.Connection, limit: int | None, symbols: set[str] | None) -> list[Any]:
    rows = conn.execute(
        """SELECT s.snapshot_id, s.security_id, s.period_end, s.source_url, s.data_json
           FROM fundamentals_snapshots s
           LEFT JOIN fundamentals_parse_status p ON p.snapshot_id = s.snapshot_id
           WHERE s.statement_type = 'meta' AND s.source_url IS NOT NULL AND p.snapshot_id IS NULL
           ORDER BY s.broadcast_at DESC"""
    ).fetchall()
    if symbols:
        rows = [r for r in rows if json.loads(r["data_json"]).get("symbol") in symbols]
    return rows[:limit] if limit else rows


def _record(
    conn: sqlite3.Connection, snapshot_id: int, status: str, detail: dict[str, Any], sha: str | None
) -> None:
    conn.execute(
        """INSERT INTO fundamentals_parse_status
               (snapshot_id, status, detail_json, raw_sha256, parser_version, parsed_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (snapshot_id) DO UPDATE SET status=excluded.status,
               detail_json=excluded.detail_json, raw_sha256=excluded.raw_sha256,
               parser_version=excluded.parser_version, parsed_at=excluded.parsed_at""",
        (snapshot_id, status, json.dumps(detail, default=str), sha, PARSER_VERSION,
         datetime.now(UTC).isoformat()),
    )


def store_facts(conn: sqlite3.Connection, snapshot_id: int, security_id: int,
                facts: XbrlFacts) -> int:
    """Write a parsed filing's line items (replacing any earlier parse of the same snapshot)."""
    conn.execute("DELETE FROM fundamentals_line_items WHERE snapshot_id=?", (snapshot_id,))
    conn.executemany(
        """INSERT INTO fundamentals_line_items
               (snapshot_id, security_id, period_kind, item, value, unit, source_tag,
                parser_version)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            (snapshot_id, security_id, kind, item, value, unit, tag, PARSER_VERSION)
            for (kind, item), (value, tag, unit) in facts.facts.items()
        ],
    )
    return len(facts.facts)


def ingest_xbrl_documents(
    *,
    sqlite_path: Path,
    raw_root: Path,
    tag_map: dict[str, dict[str, list[str]]],
    limit: int | None = None,
    symbols: set[str] | None = None,
    provider_name: str = "nse_filings",
    throttle_s: float = 1.0,
) -> XbrlIngestResult:
    conn = connect(sqlite_path)
    result = XbrlIngestResult()
    try:
        with job_run(conn, "ingest_xbrl", business_date=None) as handle:
            provider = get_fundamentals_provider(provider_name)
            pending = _pending(conn, limit, symbols)
            handle.rows_in = len(pending)
            for row in pending:
                result.attempted += 1
                meta = json.loads(row["data_json"])
                if (meta.get("bank") or "").strip().upper() == "Y":
                    _record(conn, row["snapshot_id"], "unsupported_format",
                            {"reason": "bank (different XBRL taxonomy)"}, None)
                    result.unsupported += 1
                    continue
                try:
                    artifact = provider.fetch_document(row["source_url"])
                except ProviderError as exc:
                    log.warning("xbrl_fetch_failed", url=row["source_url"], error=str(exc))
                    result.transient_failures += 1
                    handle.degraded = True
                    continue
                path = persist_document(raw_root, conn, artifact)  # bytes on disk BEFORE parsing
                sha = path.stem
                _process(conn, row, artifact.content, sha=sha, tag_map=tag_map, result=result)
                time.sleep(throttle_s)
            handle.rows_written = result.line_items
            handle.metrics = {
                "parsed": result.parsed, "partial": result.partial,
                "unsupported": result.unsupported, "malformed": result.malformed,
                "transient_failures": result.transient_failures,
            }
        return result
    finally:
        conn.close()


def _process(
    conn: sqlite3.Connection,
    row: Any,
    content: bytes,
    *,
    sha: str,
    tag_map: dict[str, dict[str, list[str]]],
    result: XbrlIngestResult,
) -> None:
    period_end = date.fromisoformat(row["period_end"])
    try:
        facts = parse_xbrl(content, tag_map, expected_period_end=period_end)
    except XbrlError as exc:
        _record(conn, row["snapshot_id"], "malformed", {"error": str(exc)}, sha)
        result.malformed += 1
        return
    if facts.status in ("parsed", "partial"):
        result.line_items += store_facts(conn, row["snapshot_id"], row["security_id"], facts)
    _record(conn, row["snapshot_id"], facts.status, facts.detail, sha)
    if facts.status == "parsed":
        result.parsed += 1
    elif facts.status == "partial":
        result.partial += 1
    else:
        result.unsupported += 1

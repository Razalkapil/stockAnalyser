"""Persistence of raw fetched bytes, content-addressed for idempotency.

Every artifact is written to data/raw/<source>/<year>/<month>/<filename>
and recorded in the raw_artifacts SQLite table keyed on
(source, business_date, sha256). Re-fetching the same date is a no-op
insert; a DIFFERENT sha256 for an already-recorded date is a loud
signal (NSE does occasionally republish a corrected bhavcopy).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

from stk.providers.base import RawArtifact


def _raw_path(raw_root: Path, source: str, business_date: date | None, suffix: str) -> Path:
    if business_date is not None:
        return raw_root / source / f"{business_date.year:04d}" / f"{business_date.month:02d}" / (
            f"{business_date.isoformat()}{suffix}"
        )
    return raw_root / source / f"fetched{suffix}"


def _guess_suffix(content_type: str | None) -> str:
    if content_type and "zip" in content_type:
        return ".zip"
    if content_type and "json" in content_type:
        return ".json"
    return ".csv"


def persist_artifact(raw_root: Path, conn: sqlite3.Connection, artifact: RawArtifact) -> str:
    """Write the artifact's bytes to disk and record it in raw_artifacts.

    Returns the validation status recorded ("ok" -- content validation
    is assumed to have already happened in the provider before this is
    called; this function's job is storage and the idempotency ledger,
    not re-validating).
    """
    sha256 = hashlib.sha256(artifact.content).hexdigest()
    suffix = _guess_suffix(artifact.content_type)
    path = _raw_path(raw_root, artifact.source, artifact.business_date, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(artifact.content)

    business_date_str = artifact.business_date.isoformat() if artifact.business_date else None

    existing = conn.execute(
        "SELECT sha256 FROM raw_artifacts WHERE source=? AND business_date IS ?",
        (artifact.source, business_date_str),
    ).fetchall()
    for row in existing:
        if row["sha256"] != sha256:
            # Loud, not silent: NSE/BSE occasionally republish a
            # corrected file for an already-ingested date.
            import structlog  # noqa: PLC0415 -- rare cold path, avoid the import cost otherwise

            structlog.get_logger(__name__).warning(
                "raw_artifact_content_changed",
                source=artifact.source,
                business_date=business_date_str,
                old_sha256=row["sha256"],
                new_sha256=sha256,
            )

    conn.execute(
        """INSERT INTO raw_artifacts
           (source, business_date, url, path, sha256, bytes, content_type,
            http_status, fetched_at, validation)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source, business_date, sha256) DO NOTHING""",
        (
            artifact.source,
            business_date_str,
            artifact.url,
            str(path.relative_to(raw_root.parent) if raw_root.parent in path.parents else path),
            sha256,
            len(artifact.content),
            artifact.content_type,
            artifact.http_status,
            artifact.fetched_at.isoformat(),
            "ok",
        ),
    )
    return "ok"


def persist_document(
    raw_root: Path, conn: sqlite3.Connection, artifact: RawArtifact, *, suffix: str | None = None
) -> Path:
    """Persist one of MANY documents that share a business date, content-addressed.

    ``persist_artifact`` names files by (source, business_date) -- right for a
    daily bhavcopy, wrong for filings, where dozens arrive on the same date
    and would overwrite one another. Here the path is derived from the bytes
    (``raw/<source>/by-sha/ab/ab12....<ext>``), so identical bytes are one file
    (re-ingest is a no-op) and different bytes can never clobber each other. The extension is
    ``suffix`` if given, else ``.json`` for JSON content and ``.xml`` otherwise.
    """
    sha256 = hashlib.sha256(artifact.content).hexdigest()
    if suffix is None:
        suffix = ".json" if artifact.content_type and "json" in artifact.content_type else ".xml"
    path = raw_root / artifact.source / "by-sha" / sha256[:2] / f"{sha256}{suffix}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.content)

    business_date_str = artifact.business_date.isoformat() if artifact.business_date else None
    conn.execute(
        """INSERT INTO raw_artifacts
           (source, business_date, url, path, sha256, bytes, content_type,
            http_status, fetched_at, validation)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (source, business_date, sha256) DO NOTHING""",
        (
            artifact.source,
            business_date_str,
            artifact.url,
            str(path.relative_to(raw_root.parent) if raw_root.parent in path.parents else path),
            sha256,
            len(artifact.content),
            artifact.content_type,
            artifact.http_status,
            artifact.fetched_at.isoformat(),
            "ok",
        ),
    )
    return path

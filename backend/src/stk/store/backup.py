"""Backups: a consistent SQLite snapshot, the parquet lake, and a checksummed manifest.

WHY PYTHON AND NOT A SHELL SCRIPT: a backup nobody has tested is a hope, not a backup. Being
Python means every rule below has a test, and ``verify`` and ``restore`` are the same code the
tests exercise.

LAYOUT
    <dest>/2026-09-19/app.db            consistent snapshot (sqlite online-backup API: safe while
                                        the API and poller are writing, unlike copying the file)
    <dest>/2026-09-19/parquet.tar.gz    the lake (bars, adjusted bars, features, manifests)
    <dest>/2026-09-19/raw.tar.gz        optional: raw fetched bytes (large; weekly by default)
    <dest>/2026-09-19/MANIFEST.json     sha256 + size of every file above, and when/why

WHAT IS AND IS NOT BACKED UP. The parquet lake and raw bytes are REBUILDABLE from the exchanges
(slowly); app.db is NOT -- it holds the paper portfolios, orders, journal, picks, backtest history
and AI outputs that exist nowhere else. So app.db is backed up every time, and it is the file the
rest of this module is most careful about.

SAFETY RULES
  * the destination may not be inside the data directory (a backup that lives beside the data it
    protects dies with it);
  * rotation only ever deletes directories that it recognises as its own (a date-named directory
    containing a MANIFEST.json) -- never anything else in ``dest``;
  * restore never deletes: whatever it replaces is moved aside to ``*.pre-restore-<timestamp>``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from stk.core.version import code_version

MANIFEST = "MANIFEST.json"
SQLITE_NAME = "app.db"
PARQUET_ARCHIVE = "parquet.tar.gz"
RAW_ARCHIVE = "raw.tar.gz"


class BackupError(RuntimeError):
    pass


@dataclass
class BackupResult:
    path: Path
    files: dict[str, int] = field(default_factory=dict)  # name -> size in bytes
    removed: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_sqlite(src: Path, dst: Path) -> None:
    """Copy a live database consistently. ``Connection.backup`` holds the necessary locks and
    copes with WAL -- a plain file copy taken mid-write can be silently corrupt."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _tar_directory(src: Path, dst: Path) -> None:
    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # A half-written temp file from an interrupted write is not data.
        return None if info.name.endswith(".tmp") else info

    with tarfile.open(dst, "w:gz") as tar:
        tar.add(src, arcname=src.name, filter=keep)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def run_backup(
    *,
    sqlite_path: Path,
    parquet_root: Path,
    dest: Path,
    raw_root: Path | None = None,
    include_raw: bool = False,
    now: datetime | None = None,
    keep_daily: int = 7,
    keep_weekly: int = 4,
) -> BackupResult:
    now = now or datetime.now(UTC)
    if not sqlite_path.exists():
        raise BackupError(f"no database at {sqlite_path} -- nothing to back up")
    for protected in (sqlite_path.parent, parquet_root):
        if _is_within(dest, protected):
            raise BackupError(
                f"the backup destination {dest} is inside {protected}: a backup stored beside "
                "the data it protects is lost with it. Choose a different location."
            )

    day = now.date().isoformat()
    target = dest / day
    staging = dest / f".{day}.partial"
    if staging.exists():
        shutil.rmtree(staging)  # our own leftover from an interrupted run
    staging.mkdir(parents=True)

    try:
        _snapshot_sqlite(sqlite_path, staging / SQLITE_NAME)
        if parquet_root.exists():
            _tar_directory(parquet_root, staging / PARQUET_ARCHIVE)
        if include_raw and raw_root is not None and raw_root.exists():
            _tar_directory(raw_root, staging / RAW_ARCHIVE)

        files = {p.name: p.stat().st_size for p in sorted(staging.iterdir())}
        manifest = {
            "created_at": now.isoformat(),
            "code_version": code_version(),
            "sqlite_source": str(sqlite_path),
            "files": {name: {"bytes": size, "sha256": sha256_of(staging / name)}
                      for name, size in files.items()},
        }
        (staging / MANIFEST).write_text(json.dumps(manifest, indent=2))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Only a COMPLETE backup ever gets its final name. An existing backup for the same day is
    # replaced by the newer one (still atomic: the old one is moved aside first).
    if target.exists():
        aside = dest / f".{day}.replaced"
        if aside.exists():
            shutil.rmtree(aside)
        target.rename(aside)
        staging.rename(target)
        shutil.rmtree(aside)
    else:
        staging.rename(target)

    problems = verify_backup(target)
    if problems:
        raise BackupError("the backup was written but failed verification: " + "; ".join(problems))
    result = BackupResult(path=target, files=files)
    result.removed = rotate(dest, keep_daily=keep_daily, keep_weekly=keep_weekly)
    return result


def _backup_dirs(dest: Path) -> list[Path]:
    """Directories this module created: date-named AND holding a manifest. Nothing else."""
    out: list[tuple[date, Path]] = []
    if not dest.exists():
        return []
    for p in dest.iterdir():
        if not p.is_dir() or not (p / MANIFEST).exists():
            continue
        try:
            out.append((date.fromisoformat(p.name), p))
        except ValueError:
            continue
    return [p for _, p in sorted(out, reverse=True)]  # newest first


def list_backups(dest: Path) -> list[Path]:
    return _backup_dirs(dest)


def rotate(dest: Path, *, keep_daily: int, keep_weekly: int) -> list[str]:
    """Keep the newest ``keep_daily`` backups, plus the newest ``keep_weekly`` SUNDAY backups
    beyond those. Deletes only directories ``_backup_dirs`` recognises as its own."""
    dirs = _backup_dirs(dest)
    keep = set(dirs[:keep_daily])
    sundays = [d for d in dirs[keep_daily:] if date.fromisoformat(d.name).weekday() == 6]
    keep.update(sundays[:keep_weekly])
    removed: list[str] = []
    for d in dirs:
        if d not in keep:
            shutil.rmtree(d)
            removed.append(d.name)
    return removed


def _check_files(path: Path, files: dict[str, dict[str, object]]) -> list[str]:
    problems: list[str] = []
    if SQLITE_NAME not in files:
        problems.append(f"{path.name}: the manifest lists no {SQLITE_NAME}")
    for name, meta in files.items():
        f = path / name
        if not f.exists():
            problems.append(f"{name}: missing")
        elif f.stat().st_size != meta["bytes"]:
            problems.append(f"{name}: size {f.stat().st_size} != recorded {meta['bytes']}")
        elif sha256_of(f) != meta["sha256"]:
            problems.append(f"{name}: checksum mismatch (the file changed after it was written)")
    return problems


def _check_database(db: Path) -> list[str]:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return [f"{SQLITE_NAME}: not a readable database: {exc}"]
    return [] if result == "ok" else [f"{SQLITE_NAME}: integrity_check said {result!r}"]


def _check_archive(archive: Path) -> list[str]:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.getmembers()
    except (tarfile.TarError, OSError, EOFError) as exc:
        return [f"{archive.name}: not a readable archive: {exc}"]
    return []


def verify_backup(path: Path) -> list[str]:
    """Everything that can be checked without restoring: manifest, checksums, the database's own
    integrity, and that each archive is a readable tarball. Empty list means sound."""
    manifest_path = path / MANIFEST
    if not manifest_path.exists():
        return [f"{path.name}: no {MANIFEST}"]
    try:
        manifest = json.loads(manifest_path.read_text())
    except ValueError as exc:
        return [f"{path.name}: unreadable {MANIFEST}: {exc}"]

    files = manifest.get("files", {})
    problems = _check_files(path, files)
    if problems:
        return problems  # a file that changed on disk is not worth opening
    problems += _check_database(path / SQLITE_NAME)
    for name in (PARQUET_ARCHIVE, RAW_ARCHIVE):
        if name in files:
            problems += _check_archive(path / name)
    return problems


def latest_backup_age_days(dest: Path, *, today: date) -> int | None:
    """Days since the newest backup, or None if there is none."""
    dirs = _backup_dirs(dest)
    if not dirs:
        return None
    return (today - date.fromisoformat(dirs[0].name)).days


def restore_backup(backup: Path, *, data_root: Path, force: bool = False,
                   now: datetime | None = None) -> list[str]:
    """Restore ``backup`` into ``data_root`` (app.db and parquet/). Returns what was done.

    Verifies first and refuses a bad backup. Refuses to overwrite existing data unless ``force``;
    even then NOTHING IS DELETED -- what was there is moved aside to ``*.pre-restore-<ts>``.
    """
    problems = verify_backup(backup)
    if problems:
        raise BackupError("refusing to restore an unverified backup: " + "; ".join(problems))
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    done: list[str] = []
    data_root.mkdir(parents=True, exist_ok=True)

    live_db = data_root / SQLITE_NAME
    live_parquet = data_root / "parquet"
    if (live_db.exists() or live_parquet.exists()) and not force:
        raise BackupError(f"{data_root} already holds data; pass force=True to move it aside "
                          "and restore over it (nothing is deleted)")

    for live in (live_db, Path(f"{live_db}-wal"), Path(f"{live_db}-shm"), live_parquet):
        if live.exists():
            aside = live.with_name(f"{live.name}.pre-restore-{stamp}")
            live.rename(aside)
            done.append(f"moved {live.name} aside to {aside.name}")

    shutil.copy2(backup / SQLITE_NAME, live_db)
    done.append(f"restored {SQLITE_NAME}")
    if (backup / PARQUET_ARCHIVE).exists():
        with tarfile.open(backup / PARQUET_ARCHIVE, "r:gz") as tar:
            tar.extractall(data_root, filter="data")
        done.append("restored parquet/")
    if (backup / RAW_ARCHIVE).exists():
        with tarfile.open(backup / RAW_ARCHIVE, "r:gz") as tar:
            tar.extractall(data_root, filter="data")
        done.append("restored raw/")
    return done

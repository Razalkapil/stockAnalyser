"""The running code's version, for attributing written data to a commit.

Both ``job_runs.code_version`` and every parquet ``_manifests`` entry
record this, so a partition whose contents look wrong can be traced to
the exact code that produced it -- the point of the build plan's "a
reparse is attributable" note. Lives in core/ (not ingest/) because
store/ needs it too and store/ must not import ingest/.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_CACHE: str | None = None


def code_version() -> str:
    """Short git SHA of HEAD, or "unknown" outside a git checkout.

    Never raises: an unavailable git is a degraded label, not a reason
    to fail a write that has already succeeded.
    """
    global _CACHE  # noqa: PLW0603 -- cheap process-wide memoisation
    if _CACHE is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            _CACHE = result.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            _CACHE = "unknown"
    return _CACHE


def source_fingerprint() -> int:
    """Max mtime_ns across the installed ``stk`` package's .py files.

    Deliberately NOT cached, and deliberately not ``code_version()``: the point is to notice a
    change from INSIDE a long-running process, and a git SHA cannot do that. A worker that had
    been up for two days once served pre-fix code for a full day because the fix was edited in
    the working tree and only committed later -- a SHA check would have missed it too.

    Never raises: a file that vanishes mid-walk, or an unreadable tree, is a degraded signal
    (no reload) rather than a reason to kill a worker that is otherwise doing its job.
    """
    newest = 0
    try:
        for path in Path(__file__).resolve().parent.parent.rglob("*.py"):
            try:
                newest = max(newest, path.stat().st_mtime_ns)
            except OSError:  # removed between the walk and the stat
                continue
    except OSError:
        return 0
    return newest

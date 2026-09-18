"""The running code's version, for attributing written data to a commit.

Both ``job_runs.code_version`` and every parquet ``_manifests`` entry
record this, so a partition whose contents look wrong can be traced to
the exact code that produced it -- the point of the build plan's "a
reparse is attributable" note. Lives in core/ (not ingest/) because
store/ needs it too and store/ must not import ingest/.
"""

from __future__ import annotations

import subprocess

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

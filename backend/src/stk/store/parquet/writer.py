"""Atomic, idempotent parquet partition writes.

This is the load-bearing idempotency mechanism for the whole ingest
pipeline: overwrite-by-partition, never append. Re-running the nightly
job or the backfill for any date, any number of times, converges to the
same file rather than accumulating duplicate rows.

Algorithm for ``upsert_partition``:
  1. Read the existing partition file, if any.
  2. Drop every row matching the (exchange, date) keys being replaced.
  3. Concatenate the new rows.
  4. Sort by (symbol, date) -- this is what makes single-symbol queries
     fast via Parquet row-group statistics (see schema.py).
  5. Write to a .tmp file, then os.replace() it over the target.

os.replace() is atomic on POSIX for same-filesystem renames, so a crash
mid-write leaves either the old file or the new one, never a corrupt
partial file.

Every write also emits a ``_manifests`` sidecar recording the resulting
file's row count and sha256 (see write_manifest). That sidecar is what
lets ``stk doctor`` detect a partition that was truncated, hand-edited
or corrupted out-of-band: without it, a silently short partition looks
exactly like a partition for a quiet trading day.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stk.core.version import code_version
from stk.store.parquet.layout import manifest_path
from stk.store.parquet.schema import ROW_GROUP_SIZE

_SHA_CHUNK_BYTES = 1024 * 1024


def sha256_of_file(path: Path) -> str:
    """Streaming sha256 of a file on disk."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_SHA_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    manifest_root: Path,
    partition_path: Path,
    *,
    dataset: str,
    exchange: str | None,
    year: int,
    row_count: int,
    schema: pa.Schema,
) -> Path:
    """Write the row-count + sha256 sidecar for a just-written partition.

    The sha256 is taken from the FINAL file, after os.replace() -- not
    from the .tmp file -- so the manifest describes exactly the bytes a
    reader will see. The manifest itself is written tmp-then-replace for
    the same reason the partition is: a half-written manifest would make
    doctor report a corruption that does not exist.
    """
    path = manifest_path(manifest_root, dataset, exchange, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": dataset,
        "exchange": exchange,
        "year": year,
        "row_count": row_count,
        "sha256": sha256_of_file(partition_path),
        "bytes": partition_path.stat().st_size,
        "written_at": datetime.now(UTC).isoformat(),
        "schema_fingerprint": hashlib.sha256(str(schema).encode()).hexdigest()[:16],
        "code_version": code_version(),
    }
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)
    return path


def read_manifest(
    manifest_root: Path, *, dataset: str, exchange: str | None, year: int
) -> dict | None:
    """The manifest for one partition, or None if none was written."""
    path = manifest_path(manifest_root, dataset, exchange, year)
    if not path.exists():
        return None
    loaded: dict = json.loads(path.read_text())
    return loaded


def upsert_partition(
    partition_path: Path,
    new_rows: pa.Table,
    *,
    schema: pa.Schema,
    replace_dates: set,
    date_column: str = "date",
    sort_keys: list[tuple[str, str]] | None = None,
    manifest_root: Path | None = None,
    dataset: str | None = None,
    exchange: str | None = None,
    year: int | None = None,
) -> int:
    """Overwrite-by-partition write. Returns the row count of the resulting file.

    ``replace_dates`` is the set of dates being (re-)written in this
    call; any existing row whose ``date_column`` value is in that set is
    dropped before the new rows are concatenated in. Rows for OTHER
    dates already in the partition (e.g. earlier days of the same year)
    are preserved untouched.

    ``sort_keys`` defaults to (symbol, date) -- the ordering that makes
    single-symbol queries fast (see schema.py). Datasets with no
    ``symbol`` column (indices_daily) must pass their own; a fake
    symbol column would be a lie in the schema.

    Passing ``manifest_root`` plus ``dataset``/``exchange``/``year``
    also writes the partition's manifest sidecar. These are explicit
    rather than reverse-engineered from ``partition_path`` because the
    path shape differs per dataset (indices_daily has no exchange
    level) and guessing would break silently on the next new dataset.
    """
    partition_path.parent.mkdir(parents=True, exist_ok=True)

    if partition_path.exists():
        existing = pq.read_table(partition_path, schema=schema)
        mask = pa.compute.is_in(existing[date_column], value_set=pa.array(sorted(replace_dates)))
        keep_mask = pa.compute.invert(mask)
        existing = existing.filter(keep_mask)
        combined = pa.concat_tables([existing, new_rows], promote_options="none")
    else:
        combined = new_rows

    effective_sort_keys = (
        sort_keys
        if sort_keys is not None
        else [("symbol", "ascending"), (date_column, "ascending")]
    )
    combined = combined.sort_by(effective_sort_keys)

    tmp_path = partition_path.with_suffix(".parquet.tmp")
    pq.write_table(combined, tmp_path, row_group_size=ROW_GROUP_SIZE)
    os.replace(tmp_path, partition_path)

    if manifest_root is not None:
        if dataset is None or year is None:
            raise ValueError(
                "manifest_root requires dataset and year -- a manifest that cannot name "
                "its own partition is unusable to stk doctor"
            )
        write_manifest(
            manifest_root,
            partition_path,
            dataset=dataset,
            exchange=exchange,
            year=year,
            row_count=combined.num_rows,
            schema=schema,
        )

    return combined.num_rows


def read_partition(partition_path: Path, *, schema: pa.Schema) -> pa.Table:
    """Read a partition file, or return an empty table matching ``schema`` if absent."""
    if not partition_path.exists():
        return schema.empty_table()
    return pq.read_table(partition_path, schema=schema)

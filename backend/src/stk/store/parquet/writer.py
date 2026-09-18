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
"""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stk.store.parquet.schema import ROW_GROUP_SIZE


def upsert_partition(
    partition_path: Path,
    new_rows: pa.Table,
    *,
    schema: pa.Schema,
    replace_dates: set,
    date_column: str = "date",
) -> int:
    """Overwrite-by-partition write. Returns the row count of the resulting file.

    ``replace_dates`` is the set of dates being (re-)written in this
    call; any existing row whose ``date_column`` value is in that set is
    dropped before the new rows are concatenated in. Rows for OTHER
    dates already in the partition (e.g. earlier days of the same year)
    are preserved untouched.
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

    sort_keys = [("symbol", "ascending"), (date_column, "ascending")]
    combined = combined.sort_by(sort_keys)

    tmp_path = partition_path.with_suffix(".parquet.tmp")
    pq.write_table(combined, tmp_path, row_group_size=ROW_GROUP_SIZE)
    os.replace(tmp_path, partition_path)

    return combined.num_rows


def read_partition(partition_path: Path, *, schema: pa.Schema) -> pa.Table:
    """Read a partition file, or return an empty table matching ``schema`` if absent."""
    if not partition_path.exists():
        return schema.empty_table()
    return pq.read_table(partition_path, schema=schema)

"""Integration tests for the atomic, overwrite-by-partition parquet writer.

This is the load-bearing idempotency mechanism for the whole ingest
pipeline (see writer.py's module docstring): re-running the same date
any number of times must converge to the same row set, never
accumulate duplicates.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stk.store.parquet.layout import bars_daily_partition, manifest_path
from stk.store.parquet.schema import BARS_DAILY_SCHEMA
from stk.store.parquet.writer import read_manifest, read_partition, upsert_partition


def _make_bars(d: date, symbols: list[str]) -> pa.Table:
    n = len(symbols)
    return pa.table(
        {
            "date": pa.array([d] * n, type=pa.date32()),
            "exchange": pa.array(["NSE"] * n).dictionary_encode(),
            "symbol": symbols,
            "security_id": pa.array([None] * n, type=pa.int32()),
            "isin": pa.array([None] * n, type=pa.string()),
            "series": pa.array(["EQ"] * n).dictionary_encode(),
            "instrument_type": pa.array(["EQ"] * n).dictionary_encode(),
            "open": [100.0] * n,
            "high": [105.0] * n,
            "low": [99.0] * n,
            "close": [102.0] * n,
            "prev_close": [100.0] * n,
            "last": [102.0] * n,
            "vwap": [101.0] * n,
            "volume": [1000] * n,
            "turnover": [102_000.0] * n,
            "trades": [50] * n,
            "delivery_qty": pa.array([None] * n, type=pa.int64()),
            "delivery_pct": pa.array([None] * n, type=pa.float64()),
            "settle_price": pa.array([None] * n, type=pa.float64()),
            "source": pa.array(["nse_sec_bhavdata"] * n).dictionary_encode(),
            "ingested_at": pa.array(
                [datetime.now(UTC)] * n, type=pa.timestamp("us", tz="UTC")
            ),
        },
        schema=BARS_DAILY_SCHEMA,
    )


def _upsert(path, table, replace_date):
    return upsert_partition(
        path, table, schema=BARS_DAILY_SCHEMA, replace_dates={replace_date}
    )


@pytest.fixture
def partition_path(tmp_parquet_root):
    return bars_daily_partition(tmp_parquet_root, "NSE", 2026)


DAY1 = date(2026, 9, 17)
DAY2 = date(2026, 9, 18)


class TestUpsertPartition:
    def test_first_write_creates_file(self, partition_path):
        day1 = _make_bars(DAY1, ["TCS", "INFY"])
        n = _upsert(partition_path, day1, DAY1)
        assert n == 2
        assert partition_path.exists()

    def test_second_day_is_additive(self, partition_path):
        day1 = _make_bars(DAY1, ["TCS", "INFY"])
        _upsert(partition_path, day1, DAY1)

        day2 = _make_bars(DAY2, ["TCS", "INFY", "RELIANCE"])
        n = _upsert(partition_path, day2, DAY2)
        assert n == 5

    def test_rerunning_same_date_is_idempotent(self, partition_path):
        """The core property: re-running ingest for an already-ingested
        date must not duplicate rows."""
        day1 = _make_bars(DAY1, ["TCS", "INFY"])
        _upsert(partition_path, day1, DAY1)

        day2 = _make_bars(DAY2, ["TCS", "INFY", "RELIANCE"])
        _upsert(partition_path, day2, DAY2)

        for _ in range(3):
            n = _upsert(partition_path, day1, DAY1)
            assert n == 5  # never grows past the true row count

        result = read_partition(partition_path, schema=BARS_DAILY_SCHEMA)
        assert result.num_rows == 5

    def test_rerun_produces_byte_identical_file(self, partition_path):
        """A stronger idempotency check: not just the same row count, but
        the same file content across re-runs (proves sort order and
        content are stable, not just accidentally-matching counts)."""
        day1 = _make_bars(DAY1, ["TCS", "INFY", "RELIANCE"])
        _upsert(partition_path, day1, DAY1)
        first_hash = hashlib.sha256(partition_path.read_bytes()).hexdigest()

        _upsert(partition_path, day1, DAY1)
        second_hash = hashlib.sha256(partition_path.read_bytes()).hexdigest()

        assert first_hash == second_hash

    def test_rows_sorted_by_symbol_then_date(self, partition_path):
        day1 = _make_bars(DAY1, ["TCS", "INFY", "RELIANCE"])
        _upsert(partition_path, day1, DAY1)

        table = pq.read_table(partition_path)
        symbols = table.column("symbol").to_pylist()
        assert symbols == sorted(symbols)

    def test_other_dates_in_partition_are_preserved(self, partition_path):
        """Re-writing one date must not disturb other dates already in
        the same year partition."""
        jan5 = date(2026, 1, 5)
        day_jan = _make_bars(jan5, ["TCS"])
        _upsert(partition_path, day_jan, jan5)

        day_sep = _make_bars(DAY2, ["INFY"])
        _upsert(partition_path, day_sep, DAY2)

        result = read_partition(partition_path, schema=BARS_DAILY_SCHEMA)
        dates_present = set(result.column("date").to_pylist())
        assert dates_present == {jan5, DAY2}

    def test_read_missing_partition_returns_empty_table(self, partition_path):
        result = read_partition(partition_path, schema=BARS_DAILY_SCHEMA)
        assert result.num_rows == 0
        assert result.schema.equals(BARS_DAILY_SCHEMA)


class TestPartitionManifests:
    """The _manifests sidecar is what makes a truncated or hand-edited
    partition detectable by `stk doctor`. Without it, a partition
    missing half its rows is indistinguishable from a quiet day."""

    def test_manifest_written_on_first_write(self, tmp_parquet_root, partition_path):
        upsert_partition(
            partition_path,
            _make_bars(DAY1, ["AAA", "BBB"]),
            schema=BARS_DAILY_SCHEMA,
            replace_dates={DAY1},
            manifest_root=tmp_parquet_root,
            dataset="bars_daily",
            exchange="NSE",
            year=2026,
        )

        manifest = read_manifest(
            tmp_parquet_root, dataset="bars_daily", exchange="NSE", year=2026
        )
        assert manifest is not None
        assert manifest["row_count"] == 2
        assert manifest["dataset"] == "bars_daily"
        assert manifest["exchange"] == "NSE"
        assert manifest["year"] == 2026
        assert manifest["bytes"] == partition_path.stat().st_size

    def test_manifest_sha256_matches_the_file_on_disk(self, tmp_parquet_root, partition_path):
        upsert_partition(
            partition_path,
            _make_bars(DAY1, ["AAA"]),
            schema=BARS_DAILY_SCHEMA,
            replace_dates={DAY1},
            manifest_root=tmp_parquet_root,
            dataset="bars_daily",
            exchange="NSE",
            year=2026,
        )

        manifest = read_manifest(
            tmp_parquet_root, dataset="bars_daily", exchange="NSE", year=2026
        )
        assert manifest is not None
        # Hashed independently of the writer's own helper -- this is the
        # assertion doctor's corruption check ultimately rests on.
        expected = hashlib.sha256(partition_path.read_bytes()).hexdigest()
        assert manifest["sha256"] == expected

    def test_manifest_tracks_a_growing_partition(self, tmp_parquet_root, partition_path):
        """Adding a second date to the same year partition must update
        both row_count and sha256 -- a stale manifest would make doctor
        cry corruption on every normal ingest."""
        def write(day, symbols):
            upsert_partition(
                partition_path,
                _make_bars(day, symbols),
                schema=BARS_DAILY_SCHEMA,
                replace_dates={day},
                manifest_root=tmp_parquet_root,
                dataset="bars_daily",
                exchange="NSE",
                year=2026,
            )
            return read_manifest(
                tmp_parquet_root, dataset="bars_daily", exchange="NSE", year=2026
            )

        first = write(DAY1, ["AAA", "BBB"])
        second = write(DAY2, ["AAA", "BBB", "CCC"])

        assert first is not None and second is not None
        assert first["row_count"] == 2
        assert second["row_count"] == 5
        assert second["sha256"] != first["sha256"]
        assert second["sha256"] == hashlib.sha256(partition_path.read_bytes()).hexdigest()

    def test_rewriting_the_same_date_keeps_manifest_consistent(
        self, tmp_parquet_root, partition_path
    ):
        """Re-ingesting a date with FEWER rows must shrink the recorded
        count, not leave the old high-water mark behind."""
        for symbols in (["AAA", "BBB", "CCC"], ["AAA"]):
            upsert_partition(
                partition_path,
                _make_bars(DAY1, symbols),
                schema=BARS_DAILY_SCHEMA,
                replace_dates={DAY1},
                manifest_root=tmp_parquet_root,
                dataset="bars_daily",
                exchange="NSE",
                year=2026,
            )

        manifest = read_manifest(
            tmp_parquet_root, dataset="bars_daily", exchange="NSE", year=2026
        )
        assert manifest is not None
        assert manifest["row_count"] == 1
        assert manifest["sha256"] == hashlib.sha256(partition_path.read_bytes()).hexdigest()

    def test_no_manifest_written_when_not_requested(self, tmp_parquet_root, partition_path):
        _upsert(partition_path, _make_bars(DAY1, ["AAA"]), DAY1)

        assert read_manifest(
            tmp_parquet_root, dataset="bars_daily", exchange="NSE", year=2026
        ) is None

    def test_manifest_root_without_dataset_raises(self, tmp_parquet_root, partition_path):
        """A manifest that cannot name its own partition is unusable --
        fail loudly rather than writing an anonymous sidecar."""
        with pytest.raises(ValueError, match="requires dataset and year"):
            upsert_partition(
                partition_path,
                _make_bars(DAY1, ["AAA"]),
                schema=BARS_DAILY_SCHEMA,
                replace_dates={DAY1},
                manifest_root=tmp_parquet_root,
                year=2026,
            )


class TestManifestPath:
    def test_exchange_partitioned_dataset(self, tmp_parquet_root):
        path = manifest_path(tmp_parquet_root, "bars_daily", "NSE", 2026)
        expected = (
            tmp_parquet_root / "_manifests" / "bars_daily" / "exchange=NSE" / "year=2026.json"
        )
        assert path == expected

    def test_dataset_without_an_exchange_dimension(self, tmp_parquet_root):
        """indices_daily is year-partitioned only -- the exchange= level
        is absent rather than filled with a placeholder."""
        path = manifest_path(tmp_parquet_root, "indices_daily", None, 2026)
        assert path == tmp_parquet_root / "_manifests" / "indices_daily" / "year=2026.json"


class TestManyDistinctSeries:
    """Regression for a bug found by a real 5-year backfill.

    `series` was dictionary-encoded with an int8 INDEX, which can hold 127 distinct values. NSE's
    historical bhavcopy carries well over 100 series codes (bond and SME series, T+0, ...), and
    the 2023 partition reached 126. The next new code made every further write raise
    `ArrowInvalid: These dictionaries cannot be combined`, halting the backfill mid-2023.
    """

    def with_series(self, d: date, codes: list[str]) -> pa.Table:
        t = _make_bars(d, [f"SYM{i}" for i in range(len(codes))])
        idx = t.schema.get_field_index("series")
        return t.set_column(idx, t.schema.field("series"),
                            pa.array(codes).dictionary_encode().cast(t.schema.field("series").type))

    def test_a_partition_can_hold_far_more_than_127_distinct_series(self, tmp_path):
        path = bars_daily_partition(tmp_path, "NSE", 2023)
        _upsert(path, self.with_series(date(2023, 1, 2), [f"A{i}" for i in range(200)]),
                date(2023, 1, 2))
        # a second day introduces 200 MORE distinct codes -- 400 in total, past any int8 index
        _upsert(path, self.with_series(date(2023, 1, 3), [f"B{i}" for i in range(200)]),
                date(2023, 1, 3))
        got = read_partition(path, schema=BARS_DAILY_SCHEMA)
        assert got.num_rows == 400
        assert len(set(got.column("series").to_pylist())) == 400

    def test_a_partition_written_with_the_old_int8_index_can_still_be_extended(self, tmp_path):
        """Every partition already on disk was written before the fix."""
        path = bars_daily_partition(tmp_path, "NSE", 2023)
        path.parent.mkdir(parents=True, exist_ok=True)
        old_schema = pa.schema(
            [pa.field(f.name, pa.dictionary(pa.int8(), pa.string())) if f.name == "series" else f
             for f in BARS_DAILY_SCHEMA])
        old = _make_bars(date(2023, 1, 2), ["AAA", "BBB"]).cast(old_schema)
        pq.write_table(old, path)
        _upsert(path, self.with_series(date(2023, 1, 3), [f"N{i}" for i in range(300)]),
                date(2023, 1, 3))
        got = read_partition(path, schema=BARS_DAILY_SCHEMA)
        assert got.num_rows == 302 and got.schema.equals(BARS_DAILY_SCHEMA)

    def test_the_schema_index_can_actually_hold_them(self):
        idx = BARS_DAILY_SCHEMA.field("series").type.index_type
        assert idx.bit_width >= 16, "int8 holds only 127 distinct series; NSE has more"

"""Parquet path conventions.

Partitioned by exchange then year: data/parquet/bars_daily/exchange=NSE/year=2024/data.parquet.
See schema.py's module docstring for why year (not month) and why this
particular directory shape.
"""

from __future__ import annotations

from pathlib import Path


def bars_daily_partition(parquet_root: Path, exchange: str, year: int) -> Path:
    return parquet_root / "bars_daily" / f"exchange={exchange}" / f"year={year}" / "data.parquet"


def bars_daily_adjusted_partition(parquet_root: Path, exchange: str, year: int) -> Path:
    return (
        parquet_root / "bars_daily_adjusted" / f"exchange={exchange}"
        / f"year={year}" / "data.parquet"
    )


def adjustment_factors_path(parquet_root: Path, exchange: str) -> Path:
    return parquet_root / "adjustment_factors" / f"exchange={exchange}" / "data.parquet"


def liquidity_daily_partition(parquet_root: Path, exchange: str, year: int) -> Path:
    return (
        parquet_root / "features" / "liquidity_daily" / f"exchange={exchange}"
        / f"year={year}" / "data.parquet"
    )


def indices_daily_partition(parquet_root: Path, year: int) -> Path:
    return parquet_root / "indices_daily" / f"year={year}" / "data.parquet"


def manifest_path(
    parquet_root: Path, dataset: str, exchange: str | None, year: int
) -> Path:
    """Where the row-count + sha256 sidecar for one partition lives.

    ``exchange`` is None for datasets that have no exchange dimension
    (indices_daily is year-partitioned only), in which case the
    exchange= level is simply absent -- mirroring the partition layout
    itself rather than inventing a placeholder value.
    """
    base = parquet_root / "_manifests" / dataset
    if exchange is not None:
        base = base / f"exchange={exchange}"
    return base / f"year={year}.json"

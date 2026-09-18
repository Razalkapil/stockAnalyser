"""Liquidity/tradeable-universe eligibility rules.

Pure functions: no I/O, no config loading. Callers pass in the already-
loaded thresholds (from config/universe.yaml) and the computed metrics
(from features/liquidity_daily parquet). Kept pure specifically so the
rule boundaries can be unit-tested without touching a database or file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiquidityMetrics:
    median_turnover_20d: float | None
    median_volume_20d: float | None
    median_trades_20d: float | None
    avg_price_20d: float | None
    listed_days: int


@dataclass(frozen=True)
class LiquidityThresholds:
    min_median_turnover_inr: float
    min_median_trades: float
    min_price_inr: float
    min_listed_days: int


def is_liquid(metrics: LiquidityMetrics, thresholds: LiquidityThresholds) -> tuple[bool, str]:
    """Whether a security passes the liquidity filter.

    Returns (passed, reason) -- reason is a human-readable explanation
    always populated, so a rejected symbol's exclusion is auditable
    rather than a bare boolean.
    """
    if metrics.listed_days < thresholds.min_listed_days:
        return False, f"listed_days={metrics.listed_days} < min={thresholds.min_listed_days}"

    min_turnover = thresholds.min_median_turnover_inr
    if metrics.median_turnover_20d is None or metrics.median_turnover_20d < min_turnover:
        return False, (
            f"median_turnover_20d={metrics.median_turnover_20d} < min={min_turnover}"
        )

    min_trades = thresholds.min_median_trades
    if metrics.median_trades_20d is None or metrics.median_trades_20d < min_trades:
        return False, f"median_trades_20d={metrics.median_trades_20d} < min={min_trades}"

    if metrics.avg_price_20d is None or metrics.avg_price_20d < thresholds.min_price_inr:
        return False, f"avg_price_20d={metrics.avg_price_20d} < min={thresholds.min_price_inr}"

    return True, "passes all liquidity thresholds"


def is_tradeable_intraday(series_or_group: str, flag_only: frozenset[str]) -> bool:
    """T2T (NSE BE/BZ, BSE T/TS/XT/MT) securities cannot be day-traded:
    no intraday, no netting. They remain in the universe for delivery-
    only strategies."""
    return series_or_group not in flag_only

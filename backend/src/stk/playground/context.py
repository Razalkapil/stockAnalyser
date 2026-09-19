"""What every playground operation needs besides a database connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stk.backtest.engine import RatesFn
from stk.config.backtest import BacktestConfig

EXCHANGE = "NSE"  # the playground trades the NSE universe, like the backtests


@dataclass(frozen=True)
class PlayCtx:
    parquet_root: Path
    cfg: BacktestConfig
    rates_for: RatesFn

"""Loader for config/universe.yaml -- liquidity thresholds and the
excluded/flagged series and group lists.

Phase 1 scope: load and validate into typed config, same division of
labour as config/costs.py -- the actual filtering RULE is a pure
function in domain.universe.is_liquid, kept separate so it can be unit-
tested without touching this loader or any config file at all.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml
from stk.domain.universe import LiquidityThresholds


class LiquidityConfig(BaseModel):
    lookback_days: int
    min_median_turnover_inr: float
    min_median_trades: float
    min_price_inr: float
    min_listed_days: int

    def to_thresholds(self) -> LiquidityThresholds:
        return LiquidityThresholds(
            min_median_turnover_inr=self.min_median_turnover_inr,
            min_median_trades=self.min_median_trades,
            min_price_inr=self.min_price_inr,
            min_listed_days=self.min_listed_days,
        )


class UniverseConfig(BaseModel):
    liquidity: LiquidityConfig
    excluded_nse_series: list[str] = Field(default_factory=list)
    excluded_bse_groups: list[str] = Field(default_factory=list)
    flag_only_nse_series: list[str] = Field(default_factory=list)
    flag_only_bse_groups: list[str] = Field(default_factory=list)

    def excluded_for(self, exchange: str) -> frozenset[str]:
        raw = self.excluded_nse_series if exchange == "NSE" else self.excluded_bse_groups
        return frozenset(raw)

    def flag_only_for(self, exchange: str) -> frozenset[str]:
        return frozenset(
            self.flag_only_nse_series if exchange == "NSE" else self.flag_only_bse_groups
        )


def load_universe_config(config_dir: Path | None = None) -> UniverseConfig:
    return UniverseConfig(**load_named_yaml("universe", config_dir=config_dir))

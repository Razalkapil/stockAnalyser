"""Typed loader for config/backtest.yaml."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml
from stk.domain.slippage import SlippageTier


class SlippageTierConfig(BaseModel):
    min_adv_turnover_inr: Decimal
    bps: Decimal


class WalkForwardConfig(BaseModel):
    train_months: int = 24
    test_months: int = 6
    step_months: int = 6


class BacktestConfig(BaseModel):
    initial_capital_inr: Decimal = Decimal(1_000_000)
    default_max_positions: int = 10
    risk_free_annual: float = 0.0
    benchmark_index_code: str = "NIFTY_500"
    product: str = "delivery"
    tradeable_series: list[str] = Field(default_factory=lambda: ["EQ", "BE", "BZ"])
    slippage_tiers: list[SlippageTierConfig] = Field(default_factory=list)
    participation_cap: Decimal = Decimal("0.05")
    circuit_band_pcts: list[Decimal] = Field(
        default_factory=lambda: [Decimal(b) for b in (2, 5, 10, 20)]
    )
    circuit_tolerance_pct: Decimal = Decimal("0.35")
    adv_lookback_days: int = 20
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
    fundamentals_lag_days: int = 60

    def tiers(self) -> tuple[SlippageTier, ...]:
        return tuple(SlippageTier(t.min_adv_turnover_inr, t.bps) for t in self.slippage_tiers)


def load_backtest_config(config_dir: Path | None = None) -> BacktestConfig:
    return BacktestConfig(**load_named_yaml("backtest", config_dir=config_dir))

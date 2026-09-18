"""Typed loader for config/promotion.yaml."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml
from stk.domain.gate import GateThresholds


class _Thresholds(BaseModel):
    min_scored_windows: int = 6
    min_pass_ratio: float = 0.6
    max_drawdown: float = -0.25
    min_total_trades: int = 30


class DecayConfig(BaseModel):
    min_closed_picks: int = 15
    hit_rate_drop_pts: float = 15.0


class PromotionConfig(BaseModel):
    default: _Thresholds = Field(default_factory=_Thresholds)
    overrides: dict[str, _Thresholds] = Field(default_factory=dict)
    auto_live_origins: list[str] = Field(default_factory=list)
    decay: DecayConfig = Field(default_factory=DecayConfig)

    def thresholds_for(self, horizon: str) -> GateThresholds:
        t = self.overrides.get(horizon, self.default)
        return GateThresholds(t.min_scored_windows, t.min_pass_ratio, t.max_drawdown,
                              t.min_total_trades)


def load_promotion_config(config_dir: Path | None = None) -> PromotionConfig:
    return PromotionConfig(**load_named_yaml("promotion", config_dir=config_dir))

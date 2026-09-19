"""Typed loader for config/ai.yaml."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml


class Price(BaseModel):
    input: float
    output: float


class EveningReviewConfig(BaseModel):
    max_picks_per_horizon: int = 10
    max_positions: int = 25


class AiConfig(BaseModel):
    enabled: bool = True
    model: str = "claude-sonnet-5"
    max_tokens: int = 16000
    timeout_s: float = 180.0
    effort: str = "medium"
    pricing_usd_per_mtok: dict[str, Price] = Field(default_factory=dict)
    evening_review: EveningReviewConfig = Field(default_factory=EveningReviewConfig)

    def estimate_cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """None when the model has no price configured: an unknown cost is not a zero cost."""
        p = self.pricing_usd_per_mtok.get(model)
        if p is None:
            return None
        return (input_tokens * p.input + output_tokens * p.output) / 1_000_000


def load_ai_config(config_dir: Path | None = None) -> AiConfig:
    return AiConfig(**load_named_yaml("ai", config_dir=config_dir))

"""Typed loader for config/ai.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from stk.config.loader import load_named_yaml


class Price(BaseModel):
    input: float
    output: float


class EveningReviewConfig(BaseModel):
    max_picks_per_horizon: int = 10
    max_positions: int = 25
    #: With nothing promoted there are no picks, and the brief falls back to what the non-promoted
    #: rules WOULD have picked. Read-only context, so only the prompt budget bounds them.
    max_previews_per_strategy: int = 3
    max_previews_total: int = 30


class ProviderSettings(BaseModel):
    """What differs per LLM provider. Anything the other provider ignores is left at its default."""

    model: str
    max_tokens: int = 16000
    #: Guard against a prompt the provider would refuse outright (e.g. Groq's low per-minute token
    #: limits): over this, the run is recorded as failed WITHOUT making the call. ~4 chars/token.
    max_input_chars: int | None = None
    #: Anthropic only (adaptive thinking); Groq has no equivalent.
    effort: str = "medium"


class AiConfig(BaseModel):
    """``model``/``max_tokens``/``effort``/``max_input_chars`` are the ACTIVE provider's values:
    they are resolved from ``providers[provider]`` unless given explicitly, so callers never
    branch on the provider."""

    enabled: bool = True
    provider: Literal["groq", "anthropic"] = "groq"
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)
    model: str = "claude-sonnet-5"
    max_tokens: int = 16000
    max_input_chars: int | None = None
    timeout_s: float = 180.0
    effort: str = "medium"
    pricing_usd_per_mtok: dict[str, Price] = Field(default_factory=dict)
    evening_review: EveningReviewConfig = Field(default_factory=EveningReviewConfig)

    @model_validator(mode="before")
    @classmethod
    def _resolve_active_provider(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        chosen = data.get("provider", "groq")
        block = (data.get("providers") or {}).get(chosen)
        if "model" not in data:
            if block is None:
                raise ValueError(f"config/ai.yaml has no providers.{chosen} block")
            settings = block if isinstance(block, ProviderSettings) else ProviderSettings(**block)
            data = {**data, "model": settings.model, "max_tokens": settings.max_tokens,
                    "max_input_chars": settings.max_input_chars, "effort": settings.effort}
        return data

    def estimate_cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """None when the model has no price configured: an unknown cost is not a zero cost."""
        p = self.pricing_usd_per_mtok.get(model)
        if p is None:
            return None
        return (input_tokens * p.input + output_tokens * p.output) / 1_000_000


def load_ai_config(config_dir: Path | None = None) -> AiConfig:
    return AiConfig(**load_named_yaml("ai", config_dir=config_dir))

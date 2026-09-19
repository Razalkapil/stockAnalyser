"""What the weekly lab is asked to emit. The strategy itself travels as a JSON STRING
(`spec_json`): a recursive DSL does not fit reliably in a reply schema, and our own validator --
not the model -- is the authority on whether a spec is acceptable."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewStrategyIdea(_Strict):
    title: str = Field(min_length=3, max_length=120)
    rationale: str = Field(min_length=10, max_length=1200)
    spec_json: str = Field(min_length=2)


class Demotion(_Strict):
    strategy: str  # a slug
    rationale: str = Field(min_length=10, max_length=1200)


class LabReply(_Strict):
    proposals: list[NewStrategyIdea] = Field(default_factory=list, max_length=5)
    demotions: list[Demotion] = Field(default_factory=list, max_length=5)

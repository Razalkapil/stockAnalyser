"""The shape of an evening review. Kept flat and simple: it is what the model is asked to emit,
and the dashboard's Brief contract is derived from it (overview, notable picks, conflicts,
position notes)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RankedPick(_Strict):
    pick_id: int
    rank: int = Field(ge=1)
    explanation: str = Field(min_length=1, max_length=600)
    conflict: str | None = Field(default=None, max_length=400)


class HorizonReview(_Strict):
    horizon: str
    ranked: list[RankedPick]


class SymbolNote(_Strict):
    symbol: str
    note: str = Field(min_length=1, max_length=500)


class EveningReview(_Strict):
    overview: str = Field(min_length=1, max_length=2000)
    horizons: list[HorizonReview]
    notable_picks: list[SymbolNote] = Field(default_factory=list, max_length=8)
    conflicts: list[str] = Field(default_factory=list, max_length=8)
    position_notes: list[SymbolNote] = Field(default_factory=list)

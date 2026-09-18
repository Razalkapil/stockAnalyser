"""Pydantic models for the strategy DSL. ``extra="forbid"`` everywhere: an
unknown key is an error, never silently ignored.

JSON shape (see config/strategies/*.json for real examples):

  entry:  {"all": [cond, ...]} | {"any": [...]} | {"not": node} | cond
  cond:   {"left": operand, "op": ">", "right": operand}
          {"left": operand, "op": "between", "right": [lo, hi]}
  operand: number | {"ind": "ema", "period": 20} | {"param": "x"}
           | {"mul": [a, b]} | {"add": [a, b]} | {"sub": [a, b]} | {"div": [a, b]}
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Horizon(StrEnum):
    SHORT_TERM = "short_term"
    SWING = "swing"
    MOMENTUM = "momentum"
    LONG_TERM = "long_term"


class Ind(_Strict):
    ind: str
    period: int | None = None


class Param(_Strict):
    param: str


class Mul(_Strict):
    mul: tuple[Operand, Operand]


class Add(_Strict):
    add: tuple[Operand, Operand]


class Sub(_Strict):
    sub: tuple[Operand, Operand]


class Div(_Strict):
    div: tuple[Operand, Operand]


Operand = float | Ind | Param | Mul | Add | Sub | Div

Op = Literal[">", ">=", "<", "<=", "between", "crosses_above", "crosses_below"]


class Cond(_Strict):
    left: Operand
    op: Op
    right: Operand | tuple[Operand, Operand]


class All(_Strict):
    all: list[Node] = Field(min_length=1)


class Any(_Strict):
    any: list[Node] = Field(min_length=1)


class Not(_Strict):
    not_: Node = Field(alias="not")


Node = All | Any | Not | Cond

for _m in (Mul, Add, Sub, Div, Cond, All, Any, Not):
    _m.model_rebuild()


class Universe(_Strict):
    exchange: Literal["NSE"] = "NSE"
    min_price_raw: float = 0.0
    min_median_turnover_inr: float = 0.0
    min_listed_days: int = 0
    exclude_series: list[str] = Field(default_factory=list)


class StopRule(_Strict):
    """Distance from the entry fill: ``atr`` = mult x ATR14 %, ``pct`` = a fixed fraction."""

    type: Literal["atr", "pct"]
    mult: float | None = None
    value: float | None = None


class ExitRules(_Strict):
    stop: StopRule | None = None
    target: StopRule | None = None
    max_hold_days: int = Field(gt=0)


class RankKey(_Strict):
    ind: str
    period: int | None = None
    dir: Literal["asc", "desc"] = "desc"
    weight: float = 1.0


class Rank(_Strict):
    by: list[RankKey] = Field(min_length=1)
    max_new_per_day: int = Field(default=3, gt=0)


class ParamDef(_Strict):
    default: float
    grid: list[float] = Field(default_factory=list)


class Sizing(_Strict):
    max_positions: int = Field(default=10, gt=0)


class StrategySpec(_Strict):
    dsl_version: Literal[1] = 1
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=3, max_length=120)
    horizon: Horizon
    universe: Universe = Field(default_factory=Universe)
    params: dict[str, ParamDef] = Field(default_factory=dict)
    entry: Node
    exit: ExitRules
    rank: Rank | None = None
    sizing: Sizing = Field(default_factory=Sizing)
    notes: str = ""

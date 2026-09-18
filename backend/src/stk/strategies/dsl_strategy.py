"""Run a validated DSL spec inside the backtest engine.

``DslStrategy`` satisfies the engine's ``Strategy`` protocol. It reads ONLY
``view.today()`` -- the rows the point-in-time view exposes for the decision
date -- so the no-look-ahead guarantee of the engine carries straight
through. The feature columns on those rows are past-only by construction
(``stk.domain.indicators``, proven by its truncation-invariance test).

``prepare_frame`` builds the feature-bearing panel a run needs; it is the one
place indicators, previous-day columns and fundamentals are attached.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from stk.backtest.data import prepare_bars
from stk.backtest.engine import Signal
from stk.backtest.view import PointInTimeView
from stk.domain.dsl.evaluate import (
    add_prev_columns,
    entry_mask,
    prev_columns_needed,
    resolve_params,
    scores,
)
from stk.domain.dsl.model import StopRule, StrategySpec
from stk.domain.fundamentals import attach_fundamentals
from stk.domain.indicators import compute_indicators


def prepare_frame(
    spec: StrategySpec,
    bars: pd.DataFrame,
    *,
    adv_lookback_days: int,
    index_close: pd.Series | None = None,
    fundamentals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Raw adjusted bars -> the frame a ``DslStrategy`` and the engine both read."""
    frame = prepare_bars(bars, adv_lookback_days)  # prev_close + adv_turnover (engine needs them)
    frame = compute_indicators(frame, index_close)
    if fundamentals is not None:
        frame = attach_fundamentals(frame, fundamentals)
    return add_prev_columns(frame, prev_columns_needed(spec))


def _fraction(rule: StopRule | None, atr_pct: float | None) -> Decimal | None:
    """A stop/target distance as a fraction of the entry price, or None if not computable."""
    if rule is None:
        return None
    if rule.type == "pct":
        return Decimal(str(rule.value))
    if atr_pct is None or pd.isna(atr_pct) or atr_pct <= 0:
        return None
    return Decimal(str(float(rule.mult or 0.0) * float(atr_pct)))


class DslStrategy:
    def __init__(self, spec: StrategySpec, params: dict[str, float] | None = None) -> None:
        self.spec = spec
        self.params = resolve_params(spec, params)
        self.name = spec.slug
        self.max_positions: int | None = spec.sizing.max_positions

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]:
        today = view.today()
        if today.empty:
            return []
        mask = entry_mask(self.spec, today, self.params) & ~today["symbol"].isin(held)
        candidates = today[mask]
        if candidates.empty:
            return []
        ranked = scores(self.spec, candidates).sort_values(ascending=False)
        limit = self.spec.rank.max_new_per_day if self.spec.rank else self.max_positions or 1
        out: list[Signal] = []
        for idx in ranked.index[:limit]:
            row = candidates.loc[idx]
            atr_pct = row.get("atr_pct14")
            stop = _fraction(self.spec.exit.stop, atr_pct)
            target = _fraction(self.spec.exit.target, atr_pct)
            # A spec that DEMANDS a stop must never trade without one: an ATR stop we
            # cannot compute (no history yet) means no signal, not an unprotected entry.
            if self.spec.exit.stop is not None and stop is None:
                continue
            if self.spec.exit.target is not None and target is None:
                continue
            out.append(
                Signal(
                    symbol=str(row["symbol"]),
                    score=float(ranked[idx]),
                    stop_pct=stop,
                    target_pct=target,
                    max_hold_days=self.spec.exit.max_hold_days,
                    reason=self.spec.name,
                )
            )
        return out

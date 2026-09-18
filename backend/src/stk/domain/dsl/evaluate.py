"""The DSL interpreter: a validated ``StrategySpec`` + a feature frame -> masks and scores.

Pure pandas over a frame that already carries every indicator column
(``stk.domain.indicators``). Operands evaluate to column arithmetic; nothing
is ever compiled or executed from the spec.

Null semantics (important, and deliberate): ANY comparison involving a
missing value is False. That is how "no delivery data before 2019", "no
benchmark before 2012" and "a bank has no ROCE" behave -- as a condition
that does not fire, never as a silently-true one.

``crosses_above/below`` need yesterday's values; the caller supplies them as
``<column>__prev`` columns (see ``prev_columns_needed`` / ``add_prev_columns``),
which are built with a strictly PAST shift.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stk.domain.dsl.catalogue import column_for
from stk.domain.dsl.model import (
    All,
    Any,
    Cond,
    Ind,
    Node,
    Not,
    Operand,
    Param,
    StopRule,
    StrategySpec,
    Universe,
)

PREV_SUFFIX = "__prev"


def _column(op: Ind) -> str:
    return column_for(op.ind, op.period)


def eval_operand(op: Operand, frame: pd.DataFrame, params: dict[str, float],
                 *, prev: bool = False) -> pd.Series | float:
    if isinstance(op, float | int):
        return float(op)
    if isinstance(op, Param):
        return float(params[op.param])
    if isinstance(op, Ind):
        col = _column(op) + (PREV_SUFFIX if prev else "")
        return frame[col] if col in frame.columns else pd.Series(np.nan, index=frame.index)
    name = type(op).__name__.lower()
    a, b = (eval_operand(x, frame, params, prev=prev) for x in getattr(op, name))
    return _arith(name, a, b)


def _arith(name: str, a: pd.Series | float, b: pd.Series | float) -> pd.Series | float:
    if name == "mul":
        return a * b
    if name == "add":
        return a + b
    if name == "sub":
        return a - b
    # Division by zero is missing data, not infinity.
    return a / b.replace(0.0, np.nan) if isinstance(b, pd.Series) else a / b


def _as_series(v: pd.Series | float, frame: pd.DataFrame) -> pd.Series:
    return v if isinstance(v, pd.Series) else pd.Series(v, index=frame.index)


def _eval_cond(c: Cond, frame: pd.DataFrame, params: dict[str, float]) -> pd.Series:
    left = _as_series(eval_operand(c.left, frame, params), frame)
    if c.op == "between":
        assert isinstance(c.right, tuple)
        lo = _as_series(eval_operand(c.right[0], frame, params), frame)
        hi = _as_series(eval_operand(c.right[1], frame, params), frame)
        return ((left >= lo) & (left <= hi)).fillna(False)
    assert not isinstance(c.right, tuple)
    right = _as_series(eval_operand(c.right, frame, params), frame)
    if c.op in ("crosses_above", "crosses_below"):
        left_prev = _as_series(eval_operand(c.left, frame, params, prev=True), frame)
        right_prev = _as_series(eval_operand(c.right, frame, params, prev=True), frame)
        if c.op == "crosses_above":
            return ((left > right) & (left_prev <= right_prev)).fillna(False)
        return ((left < right) & (left_prev >= right_prev)).fillna(False)
    ops = {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}
    return ops[c.op].fillna(False)


def eval_node(node: Node, frame: pd.DataFrame, params: dict[str, float]) -> pd.Series:
    if isinstance(node, All):
        out = pd.Series(True, index=frame.index)
        for child in node.all:
            out &= eval_node(child, frame, params)
        return out
    if isinstance(node, Any):
        out = pd.Series(False, index=frame.index)
        for child in node.any:
            out |= eval_node(child, frame, params)
        return out
    if isinstance(node, Not):
        return ~eval_node(node.not_, frame, params)
    return _eval_cond(node, frame, params)


def universe_mask(u: Universe, frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if u.min_price_raw > 0:
        mask &= (frame["close_raw"] >= u.min_price_raw).fillna(False)
    if u.min_median_turnover_inr > 0:
        mask &= (frame["turnover_med20"] >= u.min_median_turnover_inr).fillna(False)
    if u.min_listed_days > 0:
        mask &= (frame["bar_count"] >= u.min_listed_days).fillna(False)
    if u.exclude_series and "series" in frame.columns:
        mask &= ~frame["series"].isin(u.exclude_series)
    return mask


def entry_mask(spec: StrategySpec, frame: pd.DataFrame,
               params: dict[str, float] | None = None) -> pd.Series:
    resolved = resolve_params(spec, params)
    return universe_mask(spec.universe, frame) & eval_node(spec.entry, frame, resolved)


def resolve_params(spec: StrategySpec, overrides: dict[str, float] | None) -> dict[str, float]:
    resolved = {name: p.default for name, p in spec.params.items()}
    for name, value in (overrides or {}).items():
        if name not in spec.params:
            raise KeyError(f"unknown parameter {name!r}")
        resolved[name] = float(value)
    return resolved


def scores(spec: StrategySpec, candidates: pd.DataFrame) -> pd.Series:
    """Weighted sum of cross-sectional percentile ranks among ``candidates``.

    Percentile ranks (not raw values) so indicators on different scales can
    be combined; a lone candidate scores the weight total (rank 1.0). Rows
    with a missing ranking value rank last for that key.
    """
    if spec.rank is None or candidates.empty:
        return pd.Series(0.0, index=candidates.index)
    total = pd.Series(0.0, index=candidates.index)
    for key in spec.rank.by:
        values = candidates[column_for(key.ind, key.period)]
        pct = values.rank(pct=True, ascending=(key.dir == "asc")).fillna(0.0)
        if key.dir == "asc":
            pct = 1.0 - pct + (1.0 / max(len(values), 1))
        total += key.weight * pct
    return total


def prev_columns_needed(spec: StrategySpec) -> set[str]:
    """Columns whose previous-day value the spec's crosses_* conditions read."""
    needed: set[str] = set()

    def visit(node: Node) -> None:
        if isinstance(node, All):
            for c in node.all:
                visit(c)
        elif isinstance(node, Any):
            for c in node.any:
                visit(c)
        elif isinstance(node, Not):
            visit(node.not_)
        elif node.op in ("crosses_above", "crosses_below"):
            for side in (node.left, node.right):
                if isinstance(side, Ind):
                    needed.add(_column(side))

    visit(spec.entry)
    return needed


def add_prev_columns(frame: pd.DataFrame, columns: set[str]) -> pd.DataFrame:
    """Add ``<col>__prev`` = the same symbol's previous row's value (a strictly PAST shift)."""
    out = frame.sort_values(["symbol", "date"], kind="stable")
    for col in columns & set(out.columns):
        out[col + PREV_SUFFIX] = out.groupby("symbol", sort=False)[col].shift(1)
    return out


def explain(spec: StrategySpec) -> list[str]:
    """Human-readable rule lines (what the Strategy lab's `rules[]` shows)."""
    lines: list[str] = []

    def operand(op: Operand) -> str:
        if isinstance(op, float | int):
            return f"{op:g}"
        if isinstance(op, Param):
            return f"{{{op.param}}}"
        if isinstance(op, Ind):
            return _column(op)
        name = type(op).__name__.lower()
        a, b = getattr(op, name)
        sym = {"mul": "*", "add": "+", "sub": "-", "div": "/"}[name]
        return f"({operand(a)} {sym} {operand(b)})"

    def visit(node: Node, indent: int = 0) -> None:
        pad = "  " * indent
        if isinstance(node, All | Any):
            kids = node.all if isinstance(node, All) else node.any
            lines.append(f"{pad}{'ALL' if isinstance(node, All) else 'ANY'} of:")
            for kid in kids:
                visit(kid, indent + 1)
        elif isinstance(node, Not):
            lines.append(f"{pad}NOT:")
            visit(node.not_, indent + 1)
        else:
            right = (f"[{operand(node.right[0])}, {operand(node.right[1])}]"
                     if isinstance(node.right, tuple) else operand(node.right))
            lines.append(f"{pad}{operand(node.left)} {node.op} {right}")

    visit(spec.entry)

    def stop_text(label: str, rule: StopRule | None) -> str | None:
        if rule is None:
            return None
        if rule.type == "atr":
            return f"{label}: {rule.mult:g} x ATR%"
        return f"{label}: {rule.value:.1%} from entry"

    lines += [t for t in (stop_text("Stop", spec.exit.stop),
                          stop_text("Target", spec.exit.target)) if t]
    lines.append(f"Time exit: {spec.exit.max_hold_days} trading days")
    return lines

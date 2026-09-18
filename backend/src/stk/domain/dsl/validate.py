"""Semantic validation of a parsed ``StrategySpec``.

Pydantic has already rejected unknown keys and wrong types; this catches
what a schema cannot: unknown indicators, illegal periods, undefined
parameters, the PRICE-vs-literal rule (see catalogue.py), runaway size, and
a holding window that contradicts the declared horizon.

Returns ALL problems, not just the first: an AI proposing strategies (and a
human editing JSON) both fix things faster when shown every error at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from stk.domain.dsl.catalogue import CATALOGUE, Kind
from stk.domain.dsl.model import (
    Add,
    All,
    Any,
    Cond,
    Div,
    Ind,
    Mul,
    Node,
    Not,
    Operand,
    Param,
    StrategySpec,
    Sub,
)

MAX_DEPTH = 3
MAX_LEAVES = 12
MAX_OPERAND_DEPTH = 2
MAX_PARAM_COMBINATIONS = 16


@dataclass(frozen=True)
class HorizonWindow:
    hold_days_min: int
    hold_days_max: int


def _ind_error(ind: str, period: int | None, where: str) -> str | None:
    entry = CATALOGUE.get(ind)
    if entry is None:
        return f"{where}: unknown indicator {ind!r}"
    if entry.periods and period not in entry.periods:
        return f"{where}: {ind} needs period in {list(entry.periods)}, got {period}"
    if not entry.periods and period is not None:
        return f"{where}: {ind} takes no period, got {period}"
    return None


def _arith_kind(
    op: Mul | Add | Sub | Div, errors: list[str], where: str, depth: int
) -> Kind | None:
    name = type(op).__name__.lower()
    a, b = getattr(op, name)
    ka = operand_kind(a, errors, where, depth + 1)
    kb = operand_kind(b, errors, where, depth + 1)
    if ka is None and kb is None:
        return None
    if ka is not None and kb is not None:
        return ka if ka == kb and name in ("add", "sub") else Kind.RATIO
    return ka or kb  # kind x literal keeps the kind (scaling a price is still a price)


def operand_kind(op: Operand, errors: list[str], where: str, depth: int = 0) -> Kind | None:
    """The Kind an operand evaluates to; None for a bare number / parameter."""
    kind: Kind | None = None
    if isinstance(op, Ind):
        err = _ind_error(op.ind, op.period, where)
        if err:
            errors.append(err)
        else:
            kind = CATALOGUE[op.ind].kind
    elif isinstance(op, Mul | Add | Sub | Div):
        if depth >= MAX_OPERAND_DEPTH:
            errors.append(f"{where}: arithmetic nested deeper than {MAX_OPERAND_DEPTH}")
        else:
            kind = _arith_kind(op, errors, where, depth)
    return kind


def _check_cond(c: Cond, errors: list[str], where: str, params: set[str]) -> None:
    lk = operand_kind(c.left, errors, where)
    rights = c.right if isinstance(c.right, tuple) else (c.right,)
    if c.op == "between" and not isinstance(c.right, tuple):
        errors.append(f"{where}: 'between' needs a [lo, hi] pair")
    if c.op != "between" and isinstance(c.right, tuple):
        errors.append(f"{where}: only 'between' takes a pair")
    for side in (c.left, *rights):
        _check_params(side, errors, where, params)
    for r in rights:
        rk = operand_kind(r, errors, where)
        priced = {lk, rk} & {Kind.PRICE}
        literal_side = (lk is None) != (rk is None)
        bare = isinstance(r, float | int) or isinstance(c.left, float | int)
        if priced and literal_side and bare:
            errors.append(
                f"{where}: a back-adjusted price is compared with a bare number -- absolute "
                "price levels change when later corporate actions arrive; use close_raw "
                "for rupee floors, or compare against another price"
            )
    if c.op in ("crosses_above", "crosses_below"):
        for side in (c.left, c.right):
            if not isinstance(side, Ind | float | int):
                errors.append(f"{where}: {c.op} operands must be a plain indicator or number")


def _check_params(op: Operand, errors: list[str], where: str, params: set[str]) -> None:
    if isinstance(op, Param):
        if op.param not in params:
            errors.append(f"{where}: parameter {op.param!r} is not defined in params")
    elif isinstance(op, Mul | Add | Sub | Div):
        for child in getattr(op, type(op).__name__.lower()):
            _check_params(child, errors, where, params)


@dataclass
class _Ctx:
    errors: list[str]
    params: set[str]
    leaves: int = 0


def _walk(node: Node, ctx: _Ctx, depth: int, path: str) -> None:
    if depth > MAX_DEPTH:
        ctx.errors.append(f"{path}: conditions nested deeper than {MAX_DEPTH}")
        return
    if isinstance(node, All | Any):
        children = node.all if isinstance(node, All) else node.any
        label = "all" if isinstance(node, All) else "any"
        for i, child in enumerate(children):
            _walk(child, ctx, depth + 1, f"{path}.{label}[{i}]")
    elif isinstance(node, Not):
        _walk(node.not_, ctx, depth + 1, f"{path}.not")
    else:
        ctx.leaves += 1
        _check_cond(node, ctx.errors, path, ctx.params)


def validate_spec(spec: StrategySpec, horizons: dict[str, HorizonWindow]) -> list[str]:
    errors: list[str] = []
    ctx = _Ctx(errors, set(spec.params))
    _walk(spec.entry, ctx, 1, "entry")
    if ctx.leaves > MAX_LEAVES:
        errors.append(f"entry: {ctx.leaves} conditions exceeds the limit of {MAX_LEAVES}")

    for label, rule in (("exit.stop", spec.exit.stop), ("exit.target", spec.exit.target)):
        if rule is None:
            continue
        need = rule.mult if rule.type == "atr" else rule.value
        field = "mult" if rule.type == "atr" else "value"
        if need is None or need <= 0:
            errors.append(f"{label}: type {rule.type!r} needs a positive {field}")

    window = horizons.get(spec.horizon.value)
    if window is None:
        errors.append(f"horizon {spec.horizon.value!r} is not defined in config/horizons.yaml")
    elif not window.hold_days_min <= spec.exit.max_hold_days <= window.hold_days_max:
        errors.append(
            f"exit.max_hold_days={spec.exit.max_hold_days} is outside the "
            f"{spec.horizon.value} window [{window.hold_days_min}, {window.hold_days_max}]"
        )

    if spec.rank:
        for i, key in enumerate(spec.rank.by):
            err = _ind_error(key.ind, key.period, f"rank.by[{i}]")
            if err:
                errors.append(err)

    combos = 1
    for name, p in spec.params.items():
        if p.grid and p.default not in p.grid:
            errors.append(f"params.{name}: default {p.default} is not in its grid {p.grid}")
        combos *= max(1, len(p.grid))
    if combos > MAX_PARAM_COMBINATIONS:
        errors.append(f"params: {combos} grid combinations exceeds {MAX_PARAM_COMBINATIONS}")
    return errors


def param_combinations(spec: StrategySpec) -> list[dict[str, float]]:
    """Every grid combination (or just the defaults when nothing has a grid)."""
    names = list(spec.params)
    grids = [spec.params[n].grid or [spec.params[n].default] for n in names]
    return [dict(zip(names, values, strict=True)) for values in product(*grids)] or [{}]

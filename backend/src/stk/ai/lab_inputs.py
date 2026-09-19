"""Assemble the strategy lab's input: what exists, how it is doing, and what the DSL allows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from stk.config.horizons import load_horizons
from stk.config.loader import find_config_dir
from stk.domain.dsl.catalogue import CATALOGUE
from stk.strategies.proposals import recent_titles
from stk.strategies.repo import list_strategies, load_spec
from stk.strategies.stats import backtest_stats, live_stats


def _r(v: float | None, n: int = 4) -> float | None:
    return None if v is None else round(float(v), n)


def catalogue_doc() -> list[dict[str, Any]]:
    return [
        {"name": e.name, "kind": e.kind.value, "periods": list(e.periods),
         "available_from": e.available_from.isoformat() if e.available_from else None,
         "note": e.note}
        for e in CATALOGUE.values()
    ]


def _strip_titles(node: Any) -> Any:
    """Drop schema noise that costs tokens and tells the model nothing: pydantic's auto ``title``
    on every node, ``additionalProperties: false`` (the system prompt already says "no extra keys"
    and the validator enforces it on the reply) and ``default`` values. Only scalar values of
    those keys go: a PROPERTY named ``default`` or ``title`` maps to a dict and survives."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items()
                if not (k in ("title", "additionalProperties", "default")
                        and not isinstance(v, dict))}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def dsl_schema(config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or find_config_dir()) / "strategy.schema.json"
    schema: dict[str, Any] = _strip_titles(json.loads(path.read_text()))
    return schema


#: Statuses whose strategies no longer trade.
DEAD_STATUSES = ("rejected", "retired")

#: Spec keys the lab does not need to SEE: the slug/name are at the strategy's top level, and
#: notes are prose for humans. (The validator still enforces everything on what comes BACK.)
_SPEC_OMIT = ("slug", "name", "notes")


def _slim_spec(spec: dict[str, Any], standard_universe: dict[str, Any] | None) -> dict[str, Any]:
    """The spec as the lab needs to see it, without repeated boilerplate: a universe identical
    to the ``standard_universe`` (shown once, top level) is omitted, so only a DIFFERENT one
    appears."""
    slim = {k: v for k, v in spec.items() if k not in _SPEC_OMIT}
    if standard_universe is not None and slim.get("universe") == standard_universe:
        del slim["universe"]
    return slim


def _standard_universe(specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The universe most strategies share (None if fewer than two do)."""
    counts: dict[str, int] = {}
    for sp in specs:
        u = sp.get("universe")
        if u is not None:
            key = json.dumps(u, sort_keys=True)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    key, n = max(counts.items(), key=lambda kv: kv[1])
    result: dict[str, Any] | None = json.loads(key) if n >= 2 else None
    return result


def build_lab_input(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = list_strategies(conn)
    specs = {r.slug: load_spec(conn, r.latest_version_id).model_dump(
        mode="json", by_alias=True, exclude_defaults=True) for r in rows}
    standard = _standard_universe(list(specs.values()))
    strategies: list[dict[str, Any]] = []
    for row in rows:
        bt, live = backtest_stats(conn, row.slug), live_stats(conn, row.strategy_id)
        spec = _slim_spec(specs[row.slug], standard)
        if row.status in DEAD_STATUSES:
            # It will not trade again: the lab only needs to know WHAT was tried, to not repeat it.
            spec = {k: spec[k] for k in ("horizon", "entry") if k in spec}
        entry: dict[str, Any] = {
            "slug": row.slug, "horizon": row.horizon, "status": row.status,
            "spec": spec,
            "backtest_out_of_sample": {
                "cagr": _r(bt.cagr), "win_rate": _r(bt.win_rate),
                "max_drawdown": _r(bt.max_drawdown), "sharpe": _r(bt.sharpe, 2),
                "trades": bt.trades,
                "approximate": bt.is_approximate or bt.run_id is None, "gate": bt.gate_verdict},
        }
        if row.status not in DEAD_STATUSES:
            entry["status_reason"] = row.status_reason
        if live.closed or live.open:  # absent = no live picks yet (the prompt says so)
            entry["live"] = {"closed_picks": live.closed, "open_picks": live.open,
                             "hit_rate": _r(live.hit_rate), "mean_net_return": _r(live.live_return)}
        strategies.append(entry)
    return {
        "standard_universe": standard,
        "strategies": strategies,
        "recently_proposed": recent_titles(conn),
        "horizons": {k: {"min_hold_days": v.hold_days_min, "max_hold_days": v.hold_days_max}
                     for k, v in load_horizons().items()},
        "catalogue": catalogue_doc(),
        "dsl_schema": dsl_schema(),
    }

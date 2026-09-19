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


def dsl_schema(config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or find_config_dir()) / "strategy.schema.json"
    schema: dict[str, Any] = json.loads(path.read_text())
    return schema


def build_lab_input(conn: sqlite3.Connection) -> dict[str, Any]:
    strategies: list[dict[str, Any]] = []
    for row in list_strategies(conn):
        bt, live = backtest_stats(conn, row.slug), live_stats(conn, row.strategy_id)
        strategies.append({
            "slug": row.slug, "name": row.name, "horizon": row.horizon, "status": row.status,
            "status_reason": row.status_reason, "origin": row.origin,
            "spec": load_spec(conn, row.latest_version_id).model_dump(mode="json", by_alias=True,
                                                                       exclude_defaults=True),
            "backtest_out_of_sample": {
                "cagr": _r(bt.cagr), "win_rate": _r(bt.win_rate),
                "max_drawdown": _r(bt.max_drawdown), "sharpe": _r(bt.sharpe, 2),
                "trades": bt.trades,
                "approximate": bt.is_approximate or bt.run_id is None, "gate": bt.gate_verdict,
                "caveats": bt.approx_reasons[:3]},
            "live": {"closed_picks": live.closed, "open_picks": live.open,
                     "hit_rate": _r(live.hit_rate), "mean_net_return": _r(live.live_return)},
        })
    return {
        "strategies": strategies,
        "recently_proposed": recent_titles(conn),
        "horizons": {k: {"min_hold_days": v.hold_days_min, "max_hold_days": v.hold_days_max}
                     for k, v in load_horizons().items()},
        "catalogue": catalogue_doc(),
        "dsl_schema": dsl_schema(),
    }

"""Playground reads from the price lake (all via store.duck; all UNADJUSTED)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from stk.config.backtest import BacktestConfig
from stk.playground.context import EXCHANGE
from stk.store import duck


def _d(v: object) -> Decimal:
    return Decimal(str(v))


def adv_turnover(parquet_root: Path, cfg: BacktestConfig, symbols: list[str],
                 as_of: date) -> dict[str, Decimal]:
    if not symbols:
        return {}
    with duck.connect(parquet_root) as s:
        rows = s.sql("adv_for_symbols",
                     [cfg.tradeable_series, symbols, EXCHANGE, as_of.isoformat(),
                      cfg.adv_lookback_days]).fetchall()
    return {r[0]: _d(r[1]) for r in rows if r[1] is not None}


def bars_on_day(parquet_root: Path, cfg: BacktestConfig, symbols: list[str], day: date
                ) -> dict[str, dict[str, Decimal | None]]:
    if not symbols:
        return {}
    with duck.connect(parquet_root) as s:
        rows = s.sql("bars_on_day",
                     [cfg.tradeable_series, symbols, EXCHANGE, day.isoformat()]).fetchall()
    return {
        r[0]: {"open": _d(r[1]), "high": _d(r[2]), "low": _d(r[3]), "close": _d(r[4]),
               "prev_close": _d(r[5]) if r[5] is not None else None}
        for r in rows
    }


def last_closes(parquet_root: Path, cfg: BacktestConfig, symbols: list[str], as_of: date
                ) -> dict[str, tuple[date, Decimal]]:
    if not symbols:
        return {}
    with duck.connect(parquet_root) as s:
        rows = s.sql("last_close_on_or_before",
                     [cfg.tradeable_series, symbols, EXCHANGE, as_of.isoformat()]).fetchall()
    return {r[0]: (r[1], _d(r[2])) for r in rows}

"""Turn config files into the engine's inputs."""

from __future__ import annotations

from datetime import date
from functools import cache

from stk.backtest.engine import EngineConfig, RatesFn
from stk.config.backtest import BacktestConfig
from stk.config.costs import get_rate_schedule
from stk.domain.costs import CostRates, Product


def build_engine_config(cfg: BacktestConfig, exchange: str) -> EngineConfig:
    return EngineConfig(
        initial_capital=cfg.initial_capital_inr,
        exchange=exchange,
        product=Product(cfg.product),
        tiers=cfg.tiers(),
        participation_cap=cfg.participation_cap,
        circuit_band_pcts=tuple(cfg.circuit_band_pcts),
        circuit_tolerance_pct=cfg.circuit_tolerance_pct,
        default_max_positions=cfg.default_max_positions,
        risk_free_annual=cfg.risk_free_annual,
    )


def make_rates_fn() -> RatesFn:
    """Rates in force on each fill's own date, memoised per (exchange, date)."""
    schedule = get_rate_schedule()

    @cache
    def rates_for(exchange: str, d: date) -> CostRates:
        return schedule.rates_for(exchange, d)

    return rates_for

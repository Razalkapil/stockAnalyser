"""A DSL strategy running through the real engine, end to end.

The headline test is the whole-stack no-look-ahead proof: poison every bar
after a cutoff BEFORE indicators are computed, run a DSL strategy, and
require that every decision made on or before the cutoff is identical.
That exercises indicators + interpreter + engine + point-in-time view together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from stk.backtest.engine import EngineConfig, Signal, run_backtest
from stk.backtest.view import MarketData, PointInTimeView
from stk.config.horizons import load_horizons
from stk.domain.costs import BrokerageRule, CostRates, Product, ProductRates
from stk.domain.dsl.model import StrategySpec
from stk.domain.dsl.validate import validate_spec
from stk.domain.slippage import SlippageTier
from stk.strategies.dsl_strategy import DslStrategy, prepare_frame

ZERO = Decimal(0)


def zero_rates() -> CostRates:
    pr = ProductRates(BrokerageRule("flat_per_order"), ZERO, ZERO, ZERO, ZERO)
    return CostRates(ZERO, frozenset(), pr, pr, ZERO, ZERO, ZERO, ZERO, False)


def engine_config() -> EngineConfig:
    return EngineConfig(
        initial_capital=Decimal(1_000_000), exchange="NSE", product=Product.DELIVERY,
        tiers=(SlippageTier(ZERO, Decimal(5)),), participation_cap=Decimal("0.5"),
        circuit_band_pcts=(Decimal(2), Decimal(5), Decimal(10), Decimal(20)),
        circuit_tolerance_pct=Decimal("0.35"), default_max_positions=5,
    )


def make_bars(seed: int = 21, n: int = 420, symbols=("AAA", "BBB", "CCC", "DDD")) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for sym in symbols:
        close = 100 * np.cumprod(1 + rng.normal(0.0002, 0.02, n))
        for d, c in zip(pd.bdate_range("2022-01-03", periods=n), close, strict=True):
            o = c * (1 + rng.normal(0, 0.005))
            rows.append(dict(date=d, symbol=sym, series="EQ", open=o, high=max(o, c) * 1.008,
                             low=min(o, c) * 0.992, close=c, volume=800_000,
                             turnover=c * 800_000, delivery_pct=45.0))
    return pd.DataFrame(rows)


def oversold_spec(**exit_over) -> StrategySpec:
    exit_rules = {"stop": {"type": "atr", "mult": 2.0}, "target": {"type": "atr", "mult": 3.0},
                  "max_hold_days": 12, **exit_over}
    spec = StrategySpec.model_validate({
        "slug": "unit_oversold", "name": "Unit oversold", "horizon": "swing",
        "universe": {"min_price_raw": 10, "min_listed_days": 60},
        "entry": {"all": [{"left": {"ind": "rsi", "period": 2}, "op": "<", "right": 15},
                          {"left": {"ind": "close"}, "op": ">",
                           "right": {"ind": "sma", "period": 50}}]},
        "exit": exit_rules,
        "rank": {"by": [{"ind": "rsi", "period": 2, "dir": "asc"}], "max_new_per_day": 2},
        "sizing": {"max_positions": 4},
    })
    assert validate_spec(spec, load_horizons()) == []
    return spec


@dataclass
class Recorder:
    inner: DslStrategy
    decisions: dict[date, list[tuple[str, float, Decimal | None]]] = field(default_factory=dict)
    max_positions: int | None = 4
    name: str = "recorder"

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]:
        out = self.inner.signals(view, held)
        self.decisions[view.decision_date] = [(s.symbol, s.score, s.stop_pct) for s in out]
        return out


def run(spec: StrategySpec, bars: pd.DataFrame):
    frame = prepare_frame(spec, bars, adv_lookback_days=20)
    data = MarketData(frame)
    rec = Recorder(DslStrategy(spec))
    days = data.trading_dates(date(2000, 1, 1), date(2100, 1, 1))
    res = run_backtest(data, rec, days[0], days[-1], engine_config(), lambda _e, _d: zero_rates())
    return res, rec, days


class TestDslInEngine:
    def test_the_strategy_actually_trades(self):
        res, rec, _ = run(oversold_spec(), make_bars())
        assert res.trades, "scenario must exercise the strategy"
        assert any(rec.decisions.values())

    def test_atr_stop_is_a_positive_fraction_of_the_entry_price(self):
        _, rec, _ = run(oversold_spec(), make_bars())
        stops = [s[2] for sigs in rec.decisions.values() for s in sigs]
        assert stops and all(s is not None and Decimal(0) < s < Decimal("0.5") for s in stops)

    def test_a_missing_atr_never_produces_an_unprotected_entry(self):
        """Before 14 bars of history ATR is NaN. A spec demanding an ATR stop must skip
        the signal rather than enter with no stop."""
        spec = oversold_spec()
        bars = make_bars(n=70)
        frame = prepare_frame(spec, bars, adv_lookback_days=20)
        frame["atr_pct14"] = np.nan  # simulate "no ATR available"
        data = MarketData(frame)
        strat = DslStrategy(spec)
        days = data.trading_dates(date(2000, 1, 1), date(2100, 1, 1))
        for d in days[60:]:
            assert strat.signals(PointInTimeView(data, d), frozenset()) == []


class TestWholeStackNoLookAhead:
    @pytest.mark.parametrize("cutoff", [150, 250, 330])
    def test_poisoned_future_bars_change_no_earlier_decision(self, cutoff):
        clean = make_bars()
        days = sorted(clean["date"].unique())
        cut_date = pd.Timestamp(days[cutoff])

        poisoned = clean.copy()
        future = poisoned["date"] > cut_date
        rng = np.random.default_rng(5)
        junk = rng.uniform(1, 9000, future.sum())
        for col in ("open", "high", "low", "close"):
            poisoned.loc[future, col] = junk
        poisoned.loc[future, "volume"] = 1

        _, rec_a, _ = run(oversold_spec(), clean)
        _, rec_b, _ = run(oversold_spec(), poisoned)

        def upto(rec):
            return {d: s for d, s in rec.decisions.items() if pd.Timestamp(d) <= cut_date}

        assert any(upto(rec_a).values()), "scenario must emit decisions before the cutoff"
        assert upto(rec_a) == upto(rec_b)

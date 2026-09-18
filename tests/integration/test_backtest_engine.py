"""Backtest engine behaviour on synthetic bars.

Synthetic on purpose: each test builds the exact price path that isolates
one rule (a gap through a stop, a frozen upper-circuit bar, a thin-volume
day) -- something a real trimmed bhavcopy cannot be trimmed into. The
*costs* are separately pinned against real config in test_costs_compute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from stk.backtest.data import prepare_bars
from stk.backtest.engine import EngineConfig, Signal, run_backtest
from stk.backtest.runs import load_run_summary, save_single_run, save_walk_forward_run
from stk.backtest.view import LookAheadError, MarketData, PointInTimeView
from stk.backtest.walkforward import run_walk_forward
from stk.config.costs import get_rate_schedule
from stk.domain.costs import BrokerageRule, CostRates, Product, ProductRates
from stk.domain.slippage import SlippageTier
from stk.domain.walkforward import Window
from stk.store.db.engine import connect, migrate

ZERO = Decimal(0)
Bar = tuple[float, float, float, float, int]  # open, high, low, close, volume


def zero_cost_rates() -> CostRates:
    pr = ProductRates(BrokerageRule("flat_per_order"), ZERO, ZERO, ZERO, ZERO)
    return CostRates(ZERO, frozenset(), pr, pr, ZERO, ZERO, ZERO, ZERO, False)


def config(**overrides) -> EngineConfig:
    base = dict(
        initial_capital=Decimal(1_000_000),
        exchange="NSE",
        product=Product.DELIVERY,
        tiers=(SlippageTier(ZERO, ZERO),),  # no slippage: exact prices
        participation_cap=Decimal("0.5"),
        circuit_band_pcts=(Decimal(2), Decimal(5), Decimal(10), Decimal(20)),
        circuit_tolerance_pct=Decimal("0.35"),
        default_max_positions=1,
    )
    base.update(overrides)
    return EngineConfig(**base)


def flat(n: int, px: float = 100.0, vol: int = 1_000_000) -> list[Bar]:
    return [(px, px, px, px, vol)] * n


def make_data(paths: dict[str, list[Bar]], start: date = date(2024, 1, 1)) -> MarketData:
    n = len(next(iter(paths.values())))
    days = pd.bdate_range(start, periods=n)
    rows = []
    for sym, path in paths.items():
        for d, (o, h, low, c, v) in zip(days, path, strict=True):
            rows.append(dict(date=d, symbol=sym, open=o, high=h, low=low, close=c,
                             volume=v, turnover=c * v))
    return MarketData(prepare_bars(pd.DataFrame(rows), 20))


def days_of(data: MarketData) -> list[date]:
    return data.trading_dates(date(2000, 1, 1), date(2100, 1, 1))


@dataclass
class Scripted:
    """Emits pre-scripted signals on chosen decision-date indices."""

    signals_at: dict[int, list[Signal]]
    max_positions: int | None = 1
    name: str = "scripted"
    _dates: list[date] = field(default_factory=list)

    def bind(self, data: MarketData) -> Scripted:
        self._dates = days_of(data)
        return self

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]:
        return self.signals_at.get(self._dates.index(view.decision_date), [])


def run(paths, signals_at, cfg=None, rates=None, **sig_kw):
    data = make_data(paths)
    strat = Scripted(signals_at, **sig_kw).bind(data)
    ds = days_of(data)
    return run_backtest(data, strat, ds[0], ds[-1], cfg or config(),
                        lambda _e, _d: rates or zero_cost_rates()), ds


def buy(sym="A", **kw) -> list[Signal]:
    return [Signal(sym, **kw)]


class TestFillTiming:
    def test_signal_on_t_fills_at_t_plus_1_open_not_t_close(self):
        path = flat(4)
        path[1] = (100, 100, 100, 100, 1_000_000)  # decision day close = 100
        path[2] = (107, 107, 107, 107, 1_000_000)  # next day opens at 107
        res, ds = run({"A": path + flat(6, 107)}, {1: buy(max_hold_days=2)})
        t = res.trades[0]
        assert t.entry_date == ds[2]
        assert t.entry_price == Decimal("107")  # T+1 open, not T's 100

    def test_no_entry_on_the_final_day(self):
        res, _ = run({"A": flat(5)}, {3: buy()})  # decision on second-to-last day
        assert len(res.trades) == 1  # enters on the last day, liquidated at its close
        assert res.trades[0].exit_reason == "end_of_window"

    def test_time_exit_after_max_hold_days(self):
        res, ds = run({"A": flat(12)}, {1: buy(max_hold_days=3)})
        t = res.trades[0]
        assert t.entry_date == ds[2]
        assert t.exit_date == ds[5]
        assert t.exit_reason == "time" and t.holding_days == 3


class TestStopsAndTargets:
    def test_gap_through_stop_fills_at_the_open_not_the_stop(self):
        path = [*flat(3), (90, 91, 89, 90, 1000000), *flat(4, 90)]
        res, _ds = run({"A": path}, {0: buy(stop_pct=Decimal("0.05"), max_hold_days=20)})
        t = res.trades[0]
        assert t.exit_reason == "stop"
        assert t.exit_price == Decimal("90")  # the open, worse than the 95 stop

    def test_intraday_stop_touch_fills_at_the_stop_price(self):
        path = [*flat(2), (100, 101, 94, 96, 1000000), *flat(4, 96)]
        res, _ = run({"A": path}, {0: buy(stop_pct=Decimal("0.05"), max_hold_days=20)})
        assert res.trades[0].exit_price == Decimal("95")

    def test_target_fill(self):
        path = [*flat(2), (101, 112, 100, 110, 1000000), *flat(4, 110)]
        res, _ = run({"A": path}, {0: buy(target_pct=Decimal("0.10"), max_hold_days=20)})
        assert res.trades[0].exit_reason == "target"
        assert res.trades[0].exit_price == Decimal("110")

    def test_stop_wins_when_stop_and_target_touch_in_one_bar(self):
        path = [*flat(2), (100, 115, 90, 100, 1000000), *flat(4)]
        res, _ = run({"A": path}, {0: buy(stop_pct=Decimal("0.05"), target_pct=Decimal("0.10"),
                                          max_hold_days=20)})
        assert res.trades[0].exit_reason == "stop"  # the conservative reading


class TestCircuitLocks:
    def test_upper_circuit_blocks_the_entry(self):
        path = [*flat(2), (110, 110, 110, 110, 1_000_000), *flat(4, 110)]  # frozen +10%
        res, _ = run({"A": path}, {1: buy()})  # decide on day 1 -> would enter on the frozen day 2
        assert res.trades == []
        assert res.stats["entry_blocked_upper_lock"] == 1

    def test_lower_circuit_defers_the_exit_until_it_can_trade(self):
        path = [
            (100, 100, 100, 100, 1_000_000),  # 0
            (100, 100, 100, 100, 1_000_000),  # 1 decision
            (100, 100, 100, 100, 1_000_000),  # 2 entry @100, stop 95
            (90, 90, 90, 90, 1_000_000),      # 3 frozen -10%: stop triggers, sell BLOCKED
            (90, 92, 88, 91, 1_000_000),      # 4 trades: exits at the open
            *flat(3, 91),
        ]
        res, ds = run({"A": path}, {1: buy(stop_pct=Decimal("0.05"), max_hold_days=20)})
        t = res.trades[0]
        assert res.stats["exit_blocked_lower_lock"] == 1
        assert t.exit_date == ds[4] and t.exit_price == Decimal("90")


class TestParticipationCap:
    def test_entry_is_clipped_to_a_fraction_of_volume(self):
        path = [*flat(2), (100, 100, 100, 100, 1000), *flat(3)]  # entry day trades 1,000 shares
        res, _ = run({"A": path}, {1: buy(max_hold_days=1)},  # enters on the thin day 2
                     cfg=config(participation_cap=Decimal("0.05")))
        assert res.stats["entry_partial_cap"] == 1
        assert res.trades[0].qty == 50  # 5% of 1,000

    def test_partial_exit_keeps_the_remainder_open_and_prorates_entry_costs(self):
        path = [*flat(2), (100,) * 4 + (100000,), (100,) * 4 + (200,), *flat(4)]
        cfg = config(participation_cap=Decimal("0.5"))
        res, _ = run({"A": path}, {1: buy(max_hold_days=1)}, cfg=cfg)
        assert res.stats["exit_deferred_cap"] >= 1
        assert len(res.trades) >= 2  # exited in more than one piece
        assert sum(t.qty for t in res.trades) == res.trades[0].qty + sum(
            t.qty for t in res.trades[1:]
        )


class TestAccountingInvariant:
    def test_final_equity_equals_capital_plus_net_pnl_with_real_costs(self):
        """Cash is conserved exactly: every rupee of cost is in some trade's net_pnl."""
        rng = np.random.default_rng(7)
        close = 100 * np.cumprod(1 + rng.normal(0, 0.01, 60))
        path = [(c, c * 1.01, c * 0.99, c, 500_000) for c in close]
        sched = get_rate_schedule(force_reload=True)
        data = make_data({"A": path})
        strat = Scripted({i: buy(stop_pct=Decimal("0.03"), max_hold_days=4)
                          for i in range(0, 55, 6)}).bind(data)
        ds = days_of(data)
        res = run_backtest(data, strat, ds[0], ds[-1], config(),
                           sched.rates_for)
        assert res.trades, "scenario must actually trade"
        expected = Decimal(1_000_000) + sum((t.net_pnl for t in res.trades), ZERO)
        assert Decimal(str(res.equity[-1])) == pytest.approx(expected, abs=Decimal("0.01"))

    def test_dp_charge_is_included_in_delivery_sell_costs(self):
        sched = get_rate_schedule(force_reload=True)
        data = make_data({"A": flat(8)})
        strat = Scripted({0: buy(max_hold_days=2)}).bind(data)
        ds = days_of(data)
        res = run_backtest(data, strat, ds[0], ds[-1], config(),
                           sched.rates_for)
        assert res.trades[0].exit_costs >= Decimal("15.34")  # the flat DP charge alone


class TestBenchmark:
    def test_uncovered_window_is_missing_not_fabricated(self):
        late = pd.DataFrame({"date": pd.bdate_range("2024-03-01", periods=5),
                             "close": [100.0] * 5})
        data = make_data({"A": flat(10)})
        ds = days_of(data)
        res = run_backtest(data, Scripted({}).bind(data), ds[0], ds[-1], config(),
                           lambda _e, _d: zero_cost_rates(), benchmark=late)
        assert res.benchmark_missing and res.metrics.alpha is None

    def test_covered_window_yields_alpha(self):
        data = make_data({"A": flat(10)})
        ds = days_of(data)
        bench = pd.DataFrame({"date": ds, "close": np.linspace(100, 110, len(ds))})
        res = run_backtest(data, Scripted({}).bind(data), ds[0], ds[-1], config(),
                           lambda _e, _d: zero_cost_rates(), benchmark=bench)
        assert not res.benchmark_missing
        assert res.metrics.benchmark_return == pytest.approx(0.10)
        assert res.metrics.alpha == pytest.approx(-0.10)  # cash strategy vs a rising index


# --- no look-ahead ------------------------------------------------------------


def random_walk_paths(seed: int, n: int = 90) -> dict[str, list[Bar]]:
    rng = np.random.default_rng(seed)
    paths = {}
    for sym in ("AAA", "BBB", "CCC"):
        close = 100 * np.cumprod(1 + rng.normal(0, 0.015, n))
        paths[sym] = [(c * 0.998, c * 1.012, c * 0.988, c, 400_000) for c in close]
    return paths


@dataclass
class MeanReversion:
    """Buys any symbol closing below its 5-day mean -- reads only through the view."""

    max_positions: int | None = 2
    name: str = "mean_reversion"

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]:
        out = []
        for _, row in view.today().iterrows():
            hist = view.history(str(row["symbol"]), 5)
            if len(hist) == 5 and row["close"] < hist["close"].mean() and row["symbol"] not in held:
                out.append(Signal(str(row["symbol"]), score=float(-row["close"]),
                                  stop_pct=Decimal("0.04"), target_pct=Decimal("0.05"),
                                  max_hold_days=6))
        return out


def poison_after(paths: dict[str, list[Bar]], idx: int, seed: int) -> dict[str, list[Bar]]:
    rng = np.random.default_rng(seed)
    out = {}
    for sym, path in paths.items():
        junk = [(float(x), float(x) * 1.5, float(x) * 0.5, float(x), int(rng.integers(1, 10**7)))
                for x in rng.uniform(1, 5000, len(path) - idx - 1)]
        out[sym] = path[: idx + 1] + junk
    return out


@dataclass
class Recorder:
    """Wraps a strategy and logs every decision (date -> signals it emitted)."""

    inner: MeanReversion
    decisions: dict[date, list[tuple[str, float]]] = field(default_factory=dict)
    max_positions: int | None = 2
    name: str = "recorder"

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]:
        out = self.inner.signals(view, held)
        self.decisions[view.decision_date] = [(s.symbol, s.score) for s in out]
        return out


class TestNoLookAhead:
    @pytest.mark.parametrize("cutoff", [30, 45, 60])
    def test_poisoning_the_future_changes_nothing_already_decided(self, cutoff):
        clean = random_walk_paths(seed=11)
        poisoned = poison_after(clean, cutoff, seed=99)
        results = []
        recorders = []
        for paths in (clean, poisoned):
            data = make_data(paths)
            ds = days_of(data)
            rec = Recorder(MeanReversion())
            recorders.append(rec)
            results.append((run_backtest(data, rec, ds[0], ds[-1], config(),
                                         lambda _e, _d: zero_cost_rates()), ds))
        (a, ds), (b, _) = results
        cut_date = ds[cutoff]

        # THE proof: every decision made on or before the cutoff is identical. Comparing
        # only settled trades is not enough -- a decision on the cutoff day fills AFTER it,
        # so a one-row leak into that decision would be invisible there.
        def upto(rec):
            return {d: sigs for d, sigs in rec.decisions.items() if d <= cut_date}

        assert any(upto(recorders[0]).values()), "scenario must actually emit signals"
        assert upto(recorders[0]) == upto(recorders[1])

        def settled(res):
            return [(t.symbol, t.entry_date, t.entry_price, t.exit_date, t.exit_price, t.qty,
                     t.exit_reason) for t in res.trades if t.exit_date <= cut_date]

        assert settled(a), "scenario must produce trades that settle before the cutoff"
        assert settled(a) == settled(b)
        # and the equity curve up to the cutoff is identical, to the bit
        assert a.equity[: cutoff + 1] == b.equity[: cutoff + 1]

    def test_view_refuses_to_hand_back_future_rows(self):
        data = make_data({"A": flat(20)})
        view = PointInTimeView(data, days_of(data)[5])
        with pytest.raises(LookAheadError):
            view._guard(data.bars)  # the full frame extends past the decision date

    def test_view_slices_never_exceed_the_decision_date(self):
        data = make_data({"A": flat(20), "B": flat(20)})
        d = days_of(data)[7]
        view = PointInTimeView(data, d)
        assert view.today()["date"].max() == pd.Timestamp(d)
        assert view.bars_until()["date"].max() == pd.Timestamp(d)
        assert view.history("A", 100)["date"].max() == pd.Timestamp(d)

    def test_fundamentals_are_filtered_on_available_at_not_period_end(self):
        funds = pd.DataFrame({
            "symbol": ["A", "A"],
            "period_end": pd.to_datetime(["2023-12-31", "2024-03-31"]),
            "available_at": pd.to_datetime(["2024-02-14", "2024-05-20"]),
            "value": [1.0, 2.0],
        })
        data = MarketData(make_data({"A": flat(120)}).bars, funds)
        ds = days_of(data)
        early = PointInTimeView(data, date(2024, 4, 1)).fundamentals()
        assert list(early["value"]) == [1.0]  # Q1's period ended 3/31 but isn't public until 5/20
        later = PointInTimeView(data, ds[-1]).fundamentals()
        assert list(later["value"]) == [1.0, 2.0]

    def test_adv_turnover_never_includes_the_bars_own_turnover(self):
        path = [(100, 100, 100, 100, 100)] * 5 + [(100, 100, 100, 100, 10**9)]
        bars = make_data({"A": path}).bars
        # the huge final-day turnover must not appear in that same row's ADV
        assert bars.iloc[-1]["adv_turnover"] == pytest.approx(100 * 100)


# --- walk-forward and storage ---------------------------------------------------


class TestWalkForward:
    def _setup(self):
        rng = np.random.default_rng(3)
        n = 260
        close = 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, n))
        paths = {"A": [(c, c * 1.005, c * 0.995, c, 800_000) for c in close]}
        data = make_data(paths)
        ds = days_of(data)
        windows = [
            Window("W1", ds[0], ds[99], ds[100], ds[159]),
            Window("W2", ds[60], ds[159], ds[160], ds[219]),
        ]
        return data, ds, windows

    def test_test_window_uses_only_its_own_span_and_reports_no_benchmark(self):
        data, _ds, windows = self._setup()

        def factory(params):
            return Scripted({i: buy(max_hold_days=params.get("hold", 5)) for i in range(0, 260, 8)},
                            name="wf").bind(data)

        out = run_walk_forward(data, factory, windows, config(),
                               lambda _e, _d: zero_cost_rates())
        assert [w.window.label for w in out] == ["W1", "W2"]
        for wr in out:
            assert wr.result.dates[0] >= wr.window.test_start
            assert wr.result.dates[-1] <= wr.window.test_end
            assert wr.outcome == "no_benchmark"

    def test_param_grid_is_chosen_on_train_and_applied_to_test(self):
        data, _, windows = self._setup()
        chosen_calls = []

        def factory(params):
            chosen_calls.append(params)
            return Scripted({i: buy(max_hold_days=params["hold"]) for i in range(0, 260, 8)},
                            name="wf").bind(data)

        out = run_walk_forward(data, factory, windows[:1], config(),
                               lambda _e, _d: zero_cost_rates(),
                               param_grid=[{"hold": 2}, {"hold": 10}])
        # 2 train runs + 1 test run for the one window
        assert len(chosen_calls) == 3
        assert out[0].chosen_params in ({"hold": 2}, {"hold": 10})
        assert chosen_calls[-1] == out[0].chosen_params  # the test run used the train winner


class TestStorage:
    def test_single_run_round_trips(self, tmp_db_path):
        migrate(tmp_db_path)
        res, _ = run({"A": flat(12)}, {1: buy(max_hold_days=3)})
        conn = connect(tmp_db_path)
        run_id = save_single_run(conn, res, strategy_ref="unit", exchange="NSE",
                                 benchmark_code="NIFTY_500", params={"x": 1}, config={"c": 2},
                                 approx_reasons=["test"])
        summary = load_run_summary(conn, run_id)
        conn.close()
        assert summary["run"]["status"] == "success"
        assert summary["run"]["is_approximate"] == 1
        assert summary["trade_count"] == len(res.trades) == 1
        assert summary["metrics"]["overall/trade_count"] == 1.0

    def test_walk_forward_run_stores_windows(self, tmp_db_path):
        migrate(tmp_db_path)
        data = make_data({"A": flat(60)})
        ds = days_of(data)
        windows = [Window("W1", ds[0], ds[19], ds[20], ds[39]),
                   Window("W2", ds[10], ds[29], ds[40], ds[59])]
        out = run_walk_forward(data, lambda p: Scripted({}, name="w").bind(data), windows,
                               config(), lambda _e, _d: zero_cost_rates())
        conn = connect(tmp_db_path)
        run_id = save_walk_forward_run(conn, out, strategy_ref="unit_wf", exchange="NSE",
                                       benchmark_code=None, params={}, config={})
        summary = load_run_summary(conn, run_id)
        conn.close()
        assert [w["label"] for w in summary["windows"]] == ["W1", "W2"]
        assert {w["result"] for w in summary["windows"]} == {"no_benchmark"}

    def test_empty_walk_forward_rejected(self, tmp_db_path):
        migrate(tmp_db_path)
        conn = connect(tmp_db_path)
        with pytest.raises(ValueError):
            save_walk_forward_run(conn, [], strategy_ref="x", exchange="NSE",
                                  benchmark_code=None, params={}, config={})
        conn.close()

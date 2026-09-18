"""Walk-forward harness: tune on the training window, judge on the unseen test window.

For each window from ``domain.walkforward.generate_windows``:
  1. every candidate parameter set is run over the TRAIN span;
  2. the best by the objective (net total return, by default) is chosen
     -- with no candidates beyond the default there is nothing to tune
     and training is skipped;
  3. the chosen set is run once over the TEST span, on fresh capital.

A test window PASSES when the strategy's total return beats the
benchmark's over the same dates, after costs. When the benchmark does not
cover the window the result is ``no_benchmark`` -- neither pass nor fail.
The promotion gate counts only pass/fail windows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from stk.backtest.engine import BacktestResult, EngineConfig, RatesFn, Strategy, run_backtest
from stk.backtest.view import MarketData
from stk.domain.walkforward import Window

Params = dict[str, Any]
StrategyFactory = Callable[[Params], Strategy]


@dataclass(frozen=True)
class WindowResult:
    window: Window
    chosen_params: Params
    result: BacktestResult
    outcome: str  # pass | fail | no_benchmark


def _outcome(result: BacktestResult) -> str:
    if result.metrics.alpha is None:
        return "no_benchmark"
    return "pass" if result.metrics.alpha > 0 else "fail"


def run_walk_forward(
    data: MarketData,
    factory: StrategyFactory,
    windows: Sequence[Window],
    config: EngineConfig,
    rates_for: RatesFn,
    *,
    benchmark: pd.DataFrame | None = None,
    param_grid: Sequence[Params] | None = None,
) -> list[WindowResult]:
    grid: list[Params] = list(param_grid) if param_grid else [{}]
    out: list[WindowResult] = []
    for w in windows:
        chosen = grid[0]
        if len(grid) > 1:
            best: float | None = None
            for params in grid:
                train = run_backtest(
                    data, factory(params), w.train_start, w.train_end, config, rates_for
                )
                score = train.metrics.total_return
                if best is None or score > best:
                    best, chosen = score, params
        test = run_backtest(
            data, factory(chosen), w.test_start, w.test_end, config, rates_for,
            benchmark=benchmark,
        )
        out.append(WindowResult(w, chosen, test, _outcome(test)))
    return out

"""Backtest performance metrics -- pure.

Statistics, not money: inputs are converted to floats here. Rupee
*ledgers* stay Decimal elsewhere (costs, fills, P&L); a Sharpe ratio has
no use for paise precision and numpy has no use for Decimal.

Conventions, stated because each is a place metrics silently disagree:
- CAGR uses calendar days / 365.25 between first and last equity point.
- Sharpe is annualised from *daily* returns with sqrt(252) and a
  configurable annual risk-free rate (default 0 -- an explicit choice,
  see config/backtest.yaml).
- Max drawdown is peak-to-trough on the equity curve, as a negative
  fraction.
- Exposure is the mean fraction of equity held in positions.
- Win rate / profit factor are over *closed* trades, net of costs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class TradeResult:
    """One closed round trip, net of all costs."""

    net_pnl: float
    return_pct: float  # net_pnl / capital committed at entry
    holding_days: int


@dataclass(frozen=True)
class Metrics:
    total_return: float
    cagr: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    sharpe: float
    exposure: float
    trade_count: int
    benchmark_return: float | None = None
    alpha: float | None = None  # total_return - benchmark_return


def max_drawdown(equity: list[float]) -> float:
    """Worst peak-to-trough decline as a NEGATIVE fraction (0.0 if never below a peak)."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def cagr(start_value: float, end_value: float, start: date, end: date) -> float:
    days = (end - start).days
    if days <= 0 or start_value <= 0 or end_value <= 0:
        return 0.0
    return (end_value / start_value) ** (365.25 / days) - 1.0


def sharpe(equity: list[float], risk_free_annual: float = 0.0) -> float:
    """Annualised Sharpe from daily equity. 0.0 when there is no variance to divide by."""
    if len(equity) < 3:
        return 0.0
    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    rf_daily = (1.0 + risk_free_annual) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0
    excess = [r - rf_daily for r in rets]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)


def compute_metrics(
    dates: list[date],
    equity: list[float],
    exposure_series: list[float],
    trades: list[TradeResult],
    *,
    benchmark_close: list[float] | None = None,
    risk_free_annual: float = 0.0,
) -> Metrics:
    """All headline metrics for one run/window.

    ``benchmark_close`` (optional) is the benchmark's closes on the same
    ``dates``; when supplied, ``benchmark_return`` and ``alpha`` are set.
    Pass None -- never a fabricated series -- when the benchmark does
    not cover the period.
    """
    if len(dates) != len(equity):
        raise ValueError("dates and equity must be the same length")
    if not equity:
        raise ValueError("equity curve is empty")

    total_return = equity[-1] / equity[0] - 1.0
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    gross_loss = -sum(losses)
    no_loss_pf = math.inf if wins else 0.0
    profit_factor = sum(wins) / gross_loss if gross_loss > 0 else no_loss_pf

    bench_ret: float | None = None
    alpha: float | None = None
    if benchmark_close is not None:
        if len(benchmark_close) != len(dates):
            raise ValueError("benchmark_close must align with dates")
        if benchmark_close and benchmark_close[0] > 0:
            bench_ret = benchmark_close[-1] / benchmark_close[0] - 1.0
            alpha = total_return - bench_ret

    return Metrics(
        total_return=total_return,
        cagr=cagr(equity[0], equity[-1], dates[0], dates[-1]),
        win_rate=(len(wins) / len(trades)) if trades else 0.0,
        avg_win=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe(equity, risk_free_annual),
        exposure=(sum(exposure_series) / len(exposure_series)) if exposure_series else 0.0,
        trade_count=len(trades),
        benchmark_return=bench_ret,
        alpha=alpha,
    )

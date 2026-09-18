"""Daily event-loop backtester.

Sequence for each trading date d (the order is the whole point):

  1. EXITS   open positions are checked against d's bar: stop, target,
             time. A gap through the stop fills at the *open*, not the
             stop price. If stop and target are both touched in one bar
             the stop wins (the conservative reading). A lower-circuit
             lock blocks the sell; it retries next bar.
  2. ENTRIES signals generated at d-1's close fill at d's OPEN with
             adverse slippage, capped by a fraction of d's volume. An
             upper-circuit lock blocks the buy -- the signal is lost.
  3. MARK    equity is valued at d's close.
  4. SIGNAL  the strategy sees a ``PointInTimeView`` as of d's close and
             emits signals to be filled at d+1's open.

Costs come from ``domain.costs`` with the rates in force on each fill's
own date. The DP charge is levied once per (scrip, day) on sells.

Any position still open on the last date is closed at that day's close
(reason ``end_of_window``) so every window's metrics are over *closed*
trades. This liquidation ignores circuit locks and the participation cap
-- a stated simplification of the reporting boundary, not of the run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

import pandas as pd

from stk.backtest.view import MarketData, PointInTimeView
from stk.domain.costs import CostRates, Product, Side, compute_costs, dp_charge
from stk.domain.fills import BarPrices, can_buy, can_sell, circuit_lock
from stk.domain.metrics import Metrics, TradeResult, compute_metrics
from stk.domain.slippage import SlippageTier, apply_slippage, cap_quantity, slippage_bps

ZERO = Decimal(0)
COST_BUFFER = Decimal("0.004")  # sizing headroom so costs rarely exceed available cash

Row = dict[str, Any]
RatesFn = Callable[[str, date], CostRates]


@dataclass(frozen=True)
class Signal:
    """An intent to buy at the next open."""

    symbol: str
    score: float = 0.0
    stop_pct: Decimal | None = None  # e.g. Decimal("0.08") = stop 8% below entry
    target_pct: Decimal | None = None
    max_hold_days: int = 10
    reason: str = ""


class Strategy(Protocol):
    name: str
    max_positions: int | None

    def signals(self, view: PointInTimeView, held: frozenset[str]) -> list[Signal]: ...


@dataclass(frozen=True)
class EngineConfig:
    initial_capital: Decimal
    exchange: str
    product: Product
    tiers: tuple[SlippageTier, ...]
    participation_cap: Decimal
    circuit_band_pcts: tuple[Decimal, ...]
    circuit_tolerance_pct: Decimal
    default_max_positions: int = 10
    risk_free_annual: float = 0.0


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_date: date
    entry_price: Decimal
    exit_date: date
    exit_price: Decimal
    qty: int
    entry_costs: Decimal
    exit_costs: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    return_pct: float
    exit_reason: str
    holding_days: int
    reason: str = ""


@dataclass
class _Position:
    symbol: str
    qty: int
    entry_date: date
    entry_index: int
    entry_price: Decimal
    entry_costs_left: Decimal
    stop: Decimal | None
    target: Decimal | None
    max_hold_days: int
    reason: str


@dataclass
class BacktestResult:
    dates: list[date]
    equity: list[float]
    exposure: list[float]
    trades: list[Trade]
    metrics: Metrics
    benchmark_close: list[float] | None
    benchmark_missing: bool
    stats: dict[str, int] = field(default_factory=dict)


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


class _Run:
    """Mutable state and steps of one backtest run."""

    def __init__(
        self,
        data: MarketData,
        strategy: Strategy,
        dates: list[date],
        config: EngineConfig,
        rates_for: RatesFn,
    ) -> None:
        self.data = data
        self.strategy = strategy
        self.dates = dates
        self.date_index = {d: i for i, d in enumerate(dates)}
        self.cfg = config
        self.rates_for = rates_for
        self.max_pos = strategy.max_positions or config.default_max_positions
        self.cash = config.initial_capital
        self.equity_prev = config.initial_capital
        self.positions: dict[str, _Position] = {}
        self.trades: list[Trade] = []
        self.pending: list[Signal] = []
        self.last_close: dict[str, Decimal] = {}
        self.equity_curve: list[float] = []
        self.exposure: list[float] = []
        self.stats = {
            "signals": 0,
            "entries": 0,
            "entry_blocked_upper_lock": 0,
            "entry_no_bar": 0,
            "entry_no_cash": 0,
            "entry_partial_cap": 0,
            "exit_blocked_lower_lock": 0,
            "exit_deferred_cap": 0,
        }

    # -- row helpers -----------------------------------------------------

    def _slip_bps(self, row: Row) -> Decimal:
        adv = row.get("adv_turnover")
        return slippage_bps(None if adv is None or pd.isna(adv) else _d(adv), self.cfg.tiers)

    def _lock(self, row: Row) -> Any:
        pc = row.get("prev_close")
        bar = BarPrices(_d(row["open"]), _d(row["high"]), _d(row["low"]), _d(row["close"]))
        return circuit_lock(
            bar,
            None if pc is None or pd.isna(pc) else _d(pc),
            self.cfg.circuit_band_pcts,
            self.cfg.circuit_tolerance_pct,
        )

    # -- steps -----------------------------------------------------------

    def _sell(
        self,
        pos: _Position,
        qty: int,
        raw_price: Decimal,
        row: Row,
        *,
        d: date,
        reason: str,
        dp_done: set[str],
    ) -> None:
        px = apply_slippage(raw_price, Side.SELL, self._slip_bps(row))
        rates = self.rates_for(self.cfg.exchange, d)
        costs = compute_costs(Side.SELL, self.cfg.product, px * qty, rates).total
        if self.cfg.product is Product.DELIVERY and pos.symbol not in dp_done:
            costs += dp_charge(rates)
            dp_done.add(pos.symbol)
        entry_alloc = (pos.entry_costs_left * qty / pos.qty).quantize(Decimal("0.01"))
        pos.entry_costs_left -= entry_alloc
        gross = (px - pos.entry_price) * qty
        net = gross - entry_alloc - costs
        committed = pos.entry_price * qty
        self.cash += px * qty - costs
        self.trades.append(
            Trade(
                symbol=pos.symbol,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=d,
                exit_price=px,
                qty=qty,
                entry_costs=entry_alloc,
                exit_costs=costs,
                gross_pnl=gross,
                net_pnl=net,
                return_pct=float(net / committed) if committed else 0.0,
                exit_reason=reason,
                holding_days=self.date_index[d] - pos.entry_index,
                reason=pos.reason,
            )
        )
        pos.qty -= qty

    @staticmethod
    def _exit_trigger(pos: _Position, row: Row, held_days: int) -> tuple[Decimal, str] | None:
        """Which exit (if any) this bar triggers, and at what pre-slippage price."""
        o, h, low, c = _d(row["open"]), _d(row["high"]), _d(row["low"]), _d(row["close"])
        if pos.stop is not None and o <= pos.stop:
            return o, "stop"
        if pos.stop is not None and low <= pos.stop:
            return pos.stop, "stop"
        if pos.target is not None and o >= pos.target:
            return o, "target"
        if pos.target is not None and h >= pos.target:
            return pos.target, "target"
        if held_days >= pos.max_hold_days:
            return c, "time"
        return None

    def exits(self, d: date, idx: int, today: dict[str, Row], dp_done: set[str]) -> None:
        for sym in list(self.positions):
            pos = self.positions[sym]
            row = today.get(sym)
            if row is None or idx == pos.entry_index:
                continue
            trigger = self._exit_trigger(pos, row, idx - pos.entry_index)
            if trigger is None:
                continue
            if not can_sell(self._lock(row)):
                self.stats["exit_blocked_lower_lock"] += 1
                continue
            fill_qty = cap_quantity(pos.qty, int(row["volume"]), self.cfg.participation_cap)
            if fill_qty < pos.qty:
                self.stats["exit_deferred_cap"] += 1
            if fill_qty == 0:
                continue
            self._sell(
                pos, fill_qty, trigger[0], row, d=d, reason=trigger[1], dp_done=dp_done
            )
            if pos.qty == 0:
                del self.positions[sym]

    def _size_buy(self, px: Decimal, row: Row, d: date) -> tuple[int, Decimal]:
        alloc = min(self.equity_prev / self.max_pos, self.cash)
        qty = int(alloc / (px * (Decimal(1) + COST_BUFFER)))
        capped = cap_quantity(qty, int(row["volume"]), self.cfg.participation_cap)
        if capped < qty:
            self.stats["entry_partial_cap"] += 1
        qty = capped
        rates = self.rates_for(self.cfg.exchange, d)
        costs = compute_costs(Side.BUY, self.cfg.product, px * qty, rates).total
        while qty > 0 and px * qty + costs > self.cash:
            qty -= 1
            costs = compute_costs(Side.BUY, self.cfg.product, px * qty, rates).total
        return qty, costs

    def entries(self, d: date, idx: int, today: dict[str, Row]) -> None:
        for sig in self.pending:
            if len(self.positions) >= self.max_pos:
                break
            if sig.symbol in self.positions:
                continue
            row = today.get(sig.symbol)
            if row is None:
                self.stats["entry_no_bar"] += 1
                continue
            if not can_buy(self._lock(row)):
                self.stats["entry_blocked_upper_lock"] += 1
                continue
            px = apply_slippage(_d(row["open"]), Side.BUY, self._slip_bps(row))
            qty, costs = self._size_buy(px, row, d)
            if qty < 1:
                self.stats["entry_no_cash"] += 1
                continue
            self.cash -= px * qty + costs
            self.positions[sig.symbol] = _Position(
                symbol=sig.symbol,
                qty=qty,
                entry_date=d,
                entry_index=idx,
                entry_price=px,
                entry_costs_left=costs,
                stop=px * (Decimal(1) - sig.stop_pct) if sig.stop_pct is not None else None,
                target=px * (Decimal(1) + sig.target_pct) if sig.target_pct is not None else None,
                max_hold_days=sig.max_hold_days,
                reason=sig.reason,
            )
            self.stats["entries"] += 1
        self.pending = []

    def mark(self, d: date, today: dict[str, Row], *, is_last: bool, dp_done: set[str]) -> None:
        for sym, row in today.items():
            self.last_close[sym] = _d(row["close"])
        if is_last:
            for sym in list(self.positions):
                pos = self.positions.pop(sym)
                row = today.get(sym) or {"volume": 0, "adv_turnover": None}
                close_px = self.last_close.get(sym, pos.entry_price)
                self._sell(
                    pos, pos.qty, close_px, row, d=d, reason="end_of_window", dp_done=dp_done
                )
        invested = sum(
            (p.qty * self.last_close.get(p.symbol, p.entry_price) for p in self.positions.values()),
            ZERO,
        )
        equity = self.cash + invested
        self.equity_curve.append(float(equity))
        self.exposure.append(float(invested / equity) if equity else 0.0)
        self.equity_prev = equity

    def signal(self, d: date) -> None:
        view = PointInTimeView(self.data, d)
        sigs = self.strategy.signals(view, frozenset(self.positions))
        self.stats["signals"] += len(sigs)
        self.pending = sorted(sigs, key=lambda s: s.score, reverse=True)[: self.max_pos]


def run_backtest(  # noqa: PLR0917 -- a run is naturally (data, strategy, span, config, rates)
    data: MarketData,
    strategy: Strategy,
    start: date,
    end: date,
    config: EngineConfig,
    rates_for: RatesFn,
    *,
    benchmark: pd.DataFrame | None = None,
) -> BacktestResult:
    dates = data.trading_dates(start, end)
    if len(dates) < 2:
        raise ValueError(f"need at least 2 trading dates in [{start}, {end}], found {len(dates)}")

    bars_by_date: dict[date, dict[str, Row]] = {
        pd.Timestamp(k).date(): {str(r["symbol"]): r for r in grp.to_dict("records")}
        for k, grp in data.bars.groupby("date", sort=True)
        if start <= pd.Timestamp(k).date() <= end
    }

    run = _Run(data, strategy, dates, config, rates_for)
    for idx, d in enumerate(dates):
        today = bars_by_date.get(d, {})
        dp_done: set[str] = set()
        is_last = idx == len(dates) - 1
        run.exits(d, idx, today, dp_done)
        run.entries(d, idx, today)
        run.mark(d, today, is_last=is_last, dp_done=dp_done)
        if not is_last:
            run.signal(d)

    bench_close, missing = _align_benchmark(benchmark, dates)
    metrics = compute_metrics(
        dates,
        run.equity_curve,
        run.exposure,
        [TradeResult(float(t.net_pnl), t.return_pct, t.holding_days) for t in run.trades],
        benchmark_close=bench_close,
        risk_free_annual=config.risk_free_annual,
    )
    return BacktestResult(
        dates, run.equity_curve, run.exposure, run.trades, metrics, bench_close, missing, run.stats
    )


def _align_benchmark(
    benchmark: pd.DataFrame | None, dates: list[date]
) -> tuple[list[float] | None, bool]:
    """Benchmark closes aligned to ``dates`` (forward-filled), or (None, True) if uncovered.

    A benchmark that does not reach back to the window's first date is
    treated as MISSING for the window -- never back-filled: comparing a
    strategy to a series that starts two years later is not a comparison.
    """
    if benchmark is None or benchmark.empty:
        return None, True
    b = benchmark.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.date
    series = b.drop_duplicates("date").set_index("date")["close"].sort_index()
    if series.index.min() > dates[0]:
        return None, True
    aligned = series.reindex(sorted(set(series.index) | set(dates))).ffill().reindex(dates)
    if aligned.isna().any():
        return None, True
    return [float(x) for x in aligned], False

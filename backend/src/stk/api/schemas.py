"""Response shapes, camelCase on the wire, matching the design handoff's contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DelayedFeed(Wire):
    lag_minutes: int
    stale: bool


class StaleWarning(Wire):
    job: str
    since: str | None
    message: str


class JobAlert(Wire):
    """A scheduled step whose latest run failed or ended degraded."""

    job: str
    business_date: str | None
    status: str
    message: str


class Status(Wire):
    now_ist: str
    market_open: bool
    market_label: str
    data_as_of: str | None
    delayed_feed: DelayedFeed | None
    stale_warning: StaleWarning | None
    job_alerts: list[JobAlert]


class Pick(Wire):
    id: int
    symbol: str
    company: str
    exch: str
    sector: str | None  # no sector source exists yet; the UI shows a dash
    horizon: str
    strategy: str
    strategy_id: str
    score: float  # 0-100
    ref: float
    stop: float | None
    target: float | None
    window: str
    hold_days: int
    signal_date: str
    status: str
    pick_return: float | None  # this pick's own net return so far
    bt_cagr: float | None
    bt_win_rate: float | None
    live_return: float | None
    hit_rate: float | None
    approx: bool
    reason: str
    conflict: str | None


class StrategySummary(Wire):
    id: str
    name: str
    horizon: str
    status: str
    status_reason: str | None
    origin: str
    bt_cagr: float | None
    win_rate: float | None
    max_dd: float | None
    sharpe: float | None
    trades: int
    live_return: float | None
    hit_rate: float | None
    live_closed: int
    avg_hold: float | None
    approx: bool
    gate_verdict: str | None


class WalkForwardWindow(Wire):
    label: str
    result: str
    test_start: str
    test_end: str
    strat_return: float | None
    bench_return: float | None


class TradeRow(Wire):
    symbol: str
    date: str
    ret: float


class StrategyDetail(StrategySummary):
    notes: str
    rules: list[str]
    approx_reasons: list[str]
    curve_dates: list[str]
    equity_curve: list[float]
    nifty_curve: list[float]
    walk_forward: list[WalkForwardWindow]
    trade_list: list[TradeRow]
    trade_list_source: str  # 'live' | 'backtest' | 'none'


class StockHit(Wire):
    symbol: str
    company: str
    exch: str
    isin: str


class Fundamentals(Wire):
    as_of: str
    roce: float | None
    de_ratio: float | None
    sales_cagr3: float | None
    profit_cagr3: float | None
    eps_ttm: float | None
    approx: bool
    note: str


class FlaggedBy(Wire):
    strategy: str
    strategy_id: str
    horizon: str
    signal_date: str
    status: str


class StockDetail(Wire):
    symbol: str
    company: str
    exch: str
    isin: str
    tv_symbol: str
    last_close: float | None
    change_pct: float | None
    last_date: str | None
    fundamentals: Fundamentals | None
    flagged_by: list[FlaggedBy]


class Bar(Wire):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class BriefListItem(Wire):
    date: str
    pending: bool


class Brief(Wire):
    date: str
    pending: bool
    generated_at: str | None
    overview: str
    notable_picks: list[dict[str, str]]
    conflicts: list[str]
    position_notes: list[dict[str, str]]


class DemoteRequest(Wire):
    confirm: bool
    reason: str


# --- playground ------------------------------------------------------------------------------


class PositionOut(Wire):
    symbol: str
    qty: int
    avg: float
    ltp: float | None
    pnl: float | None
    pnl_pct: float | None
    days: int


class OrderOut(Wire):
    id: int
    symbol: str
    side: str
    type: str
    qty: int
    price: float | None  # the limit or trigger price
    status: str
    status_note: str | None
    created: str
    journal_note: str | None
    bracket_stop: float | None
    bracket_target: float | None
    parent_order_id: int | None


class TradeOut(Wire):
    id: int
    order_id: int
    symbol: str
    side: str
    qty: int
    fill: float
    time: str
    charges: float
    realised_pnl: float | None
    fill_basis: str  # 'delayed_intraday' | 'eod_fallback'
    delayed: bool
    fill_reason: str
    feed_lag_s: int | None
    journal_note: str | None


class PortfolioSummary(Wire):
    id: int
    name: str
    start_capital: float
    cash: float
    invested: float
    current_value: float
    realised_pnl: float
    unrealised_pnl: float
    charges: float
    return_pct: float
    nifty_return_pct: float | None
    xirr: float | None
    max_dd: float | None
    win_rate: float | None
    as_of: str | None


class PortfolioDetail(PortfolioSummary):
    positions: list[PositionOut]
    orders: list[OrderOut]
    trades: list[TradeOut]
    curve_dates: list[str]
    curve: list[float]
    nifty_curve: list[float]


class NewPortfolio(Wire):
    name: str
    start_capital: Decimal


class NewOrder(Wire):
    portfolio_id: int
    symbol: str
    side: str
    type: str
    qty: int
    limit_price: Decimal | None = None
    trigger_price: Decimal | None = None
    bracket_stop: Decimal | None = None
    bracket_target: Decimal | None = None
    journal_note: str | None = None
    pick_id: int | None = None


class CostPreview(Wire):
    price: float  # the reference price used
    est_price: float  # after estimated slippage
    slippage_bps: float
    value: float
    charges: float
    dp_charge: float
    total: float  # buy: value + charges. sell: value - charges.
    charge_breakdown: dict[str, float]
    note: str


class PreviewRequest(Wire):
    symbol: str
    side: str
    qty: int
    price: Decimal


class JournalUpdate(Wire):
    note: str


# --- proposals -------------------------------------------------------------------------------


class ProposalOut(Wire):
    id: int
    type: str  # 'new' | 'demote'
    title: str
    rationale: str
    status: str
    status_note: str | None
    date: str
    target_strategy: str | None
    strategy_id: str | None
    rules: list[str]
    validation_errors: list[str]
    gate_verdict: str | None
    bt_cagr: float | None
    bt_win_rate: float | None
    bt_max_dd: float | None
    approx: bool
    approx_reasons: list[str]


class DecisionRequest(Wire):
    confirm: bool = False

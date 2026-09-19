"""Response shapes, camelCase on the wire, matching the design handoff's contracts."""

from __future__ import annotations

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


class Status(Wire):
    now_ist: str
    market_open: bool
    market_label: str
    data_as_of: str | None
    delayed_feed: DelayedFeed | None
    stale_warning: StaleWarning | None


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

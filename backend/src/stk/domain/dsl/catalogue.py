"""The closed catalogue of indicators a strategy may reference.

A spec naming anything outside this table is rejected at validation, never
"best-effort" evaluated. Each entry records:

  kind            what the number MEANS, so the validator can refuse
                  nonsense (see the PRICE-vs-literal rule below)
  periods         the only allowed ``period`` values (empty = none allowed)
  available_from  the first date the underlying data exists, so a backtest
                  can be labelled approximate rather than silently treating
                  "no data yet" as "condition false" for years

THE PRICE-vs-LITERAL RULE. ``close``, the moving averages, the breakout
levels etc. are BACK-ADJUSTED prices: their ratios are stable when a later
corporate action arrives, but their absolute levels are not (a later 1:1
bonus halves every historical level). So a rule like ``close > 500`` would
mean different things depending on when the backtest was run. Price-kind
values may therefore only be compared with other price-kind values (or a
literal multiple of one); an absolute rupee floor must use ``close_raw``,
the unadjusted close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Kind(StrEnum):
    PRICE = "price"  # back-adjusted price level
    PRICE_RAW = "price_raw"  # unadjusted rupees
    RATIO = "ratio"  # dimensionless
    PCT = "pct"  # a fraction (0.05 = 5%) or percent-points, per the entry's note
    OSC = "osc"  # 0..100 oscillator
    RUPEES = "rupees"  # a turnover amount
    COUNT = "count"  # shares / days / bars
    FUND = "fund"  # fundamentals-derived


@dataclass(frozen=True)
class Indicator:
    name: str
    kind: Kind
    periods: tuple[int, ...] = ()
    available_from: date | None = None
    note: str = ""

    def column(self, period: int | None) -> str:
        return f"{self.name}{period}" if period is not None else self.name


_NIFTY500_FROM = date(2012, 2, 21)  # first day of the benchmark archive
_DELIVERY_FROM = date(2019, 9, 30)  # NSE delivery data exists from here (ADR 0003)


def _i(name: str, kind: Kind, periods: tuple[int, ...] = (), **kw) -> Indicator:  # type: ignore[no-untyped-def]
    return Indicator(name, kind, periods, **kw)


_ENTRIES = [
    _i("open", Kind.PRICE),
    _i("high", Kind.PRICE),
    _i("low", Kind.PRICE),
    _i("close", Kind.PRICE),
    _i("close_raw", Kind.PRICE_RAW, note="unadjusted close; use for absolute rupee floors"),
    _i("volume", Kind.COUNT),
    _i("sma", Kind.PRICE, (20, 50, 100, 200)),
    _i("ema", Kind.PRICE, (10, 20, 50, 100, 200)),
    _i("rsi", Kind.OSC, (2, 14)),
    _i("atr", Kind.PRICE, (14,)),
    _i("atr_pct", Kind.PCT, (14,), note="ATR / close, a fraction"),
    _i("ret", Kind.PCT, (1, 5, 20, 60, 120, 250), note="n-day return, a fraction"),
    _i("mom_12_1", Kind.PCT, note="close[t-21] / close[t-252] - 1, a fraction"),
    _i("high_prior", Kind.PRICE, (20, 55, 252), note="max high of the n bars ENDING YESTERDAY"),
    _i("low_prior", Kind.PRICE, (20, 60, 252), note="min low of the n bars ENDING YESTERDAY"),
    _i("high_252_prox", Kind.RATIO, note="close / 52-week high, <= 1"),
    _i("vol_ratio", Kind.RATIO, (20,), note="volume / mean volume of the prior n bars"),
    _i("gap_pct", Kind.PCT, note="(open / prev close - 1) * 100, PERCENT POINTS"),
    _i("close_location", Kind.RATIO, note="(close - low) / (high - low), 0..1"),
    _i("range_pct_prior", Kind.PCT, (10, 20), note="prior-n (high-low) / prev close, a fraction"),
    _i("turnover_med", Kind.RUPEES, (20,), note="median turnover of the prior n bars"),
    _i("bar_count", Kind.COUNT, note="bars since first listing in the loaded history"),
    _i("delivery_pct", Kind.PCT, available_from=_DELIVERY_FROM, note="PERCENT POINTS, 0..100"),
    _i("delivery_pct_sma", Kind.PCT, (20,), available_from=_DELIVERY_FROM),
    _i("rs", Kind.RATIO, (63, 126, 252), available_from=_NIFTY500_FROM,
       note="stock n-day return minus Nifty 500 n-day return"),
    # Fundamentals (point-in-time joined on filing availability -- see ingest.fundamentals_metrics)
    _i("roce", Kind.FUND, note="EBIT(TTM) / (equity + borrowings), a fraction"),
    _i("de_ratio", Kind.FUND, note="borrowings / equity"),
    _i("sales_cagr", Kind.FUND, (3,), note="annual revenue CAGR over n years, a fraction"),
    _i("profit_cagr", Kind.FUND, (3,), note="annual net-profit CAGR over n years, a fraction"),
    _i("pe_ttm", Kind.FUND, note="close_raw / EPS(TTM); null if EPS <= 0"),
    _i("fund_age_days", Kind.FUND, note="days since the latest filing became available"),
]

CATALOGUE: dict[str, Indicator] = {e.name: e for e in _ENTRIES}

FUNDAMENTAL_INDICATORS = frozenset(e.name for e in _ENTRIES if e.kind is Kind.FUND)


def column_for(name: str, period: int | None) -> str:
    return CATALOGUE[name].column(period)


def all_columns() -> set[str]:
    """Every concrete column name the catalogue can produce."""
    cols: set[str] = set()
    for e in _ENTRIES:
        if e.periods:
            cols.update(e.column(p) for p in e.periods)
        else:
            cols.add(e.name)
    return cols

"""Portfolio performance: value, P&L, return vs benchmark, XIRR, drawdown, win rate.

Marks use the latest UNADJUSTED close (what the shares would sell for). ``None`` means
"cannot be computed", and is shown as a dash -- never as 0%.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from stk.backtest.data import load_benchmark
from stk.core.money import to_money
from stk.core.time import today_ist
from stk.domain.metrics import max_drawdown
from stk.domain.xirr import xirr
from stk.playground import marketdata
from stk.playground.context import PlayCtx
from stk.playground.ledger import cash_balance

ZERO = Decimal(0)


@dataclass
class PositionView:
    symbol: str
    qty: int
    avg_cost: Decimal
    ltp: Decimal | None
    unrealised: Decimal | None
    unrealised_pct: float | None
    days_held: int


@dataclass
class Summary:
    portfolio_id: int
    name: str
    start_capital: Decimal
    cash: Decimal
    invested: Decimal  # at cost
    current_value: Decimal  # cash + positions marked to market
    realised_pnl: Decimal  # gross of charges
    unrealised_pnl: Decimal
    charges: Decimal
    return_pct: float
    nifty_return_pct: float | None
    xirr: float | None
    max_dd: float | None
    win_rate: float | None
    as_of: date | None
    positions: list[PositionView] = field(default_factory=list)


def _marks(ctx: PlayCtx, symbols: list[str], on: date) -> dict[str, tuple[date, Decimal]]:
    return marketdata.last_closes(ctx.parquet_root, ctx.cfg, symbols, on)


def summarise(conn: sqlite3.Connection, ctx: PlayCtx, portfolio_id: int,
              day: date | None = None) -> Summary:
    """A portfolio as of ``day`` (default: today). A report ABOUT a past day (the evening brief
    for 2026-09-18, re-run later) must pass that day: marks, days held and the XIRR end date all
    follow it, so nothing quietly reads today's prices."""
    on = day or today_ist()
    pf = conn.execute("SELECT * FROM portfolios WHERE portfolio_id=?", (portfolio_id,)).fetchone()
    if pf is None:
        raise KeyError(f"no portfolio {portfolio_id}")
    start = Decimal(pf["start_capital"])
    cash = cash_balance(conn, portfolio_id)

    held = conn.execute(
        "SELECT * FROM positions WHERE portfolio_id=? AND qty>0 ORDER BY symbol",
        (portfolio_id,)).fetchall()
    marks = _marks(ctx, [r["symbol"] for r in held], on)
    views: list[PositionView] = []
    invested = market_value = unrealised = ZERO
    as_of: date | None = None
    for r in held:
        qty, avg = r["qty"], Decimal(r["avg_cost"])
        mark = marks.get(r["symbol"])
        ltp = mark[1] if mark else None
        if mark and (as_of is None or mark[0] > as_of):
            as_of = mark[0]
        invested += avg * qty
        # No mark (suspended / not ingested): value it at cost rather than at zero, and say so
        # through ltp=None so the UI can show a dash.
        market_value += (ltp if ltp is not None else avg) * qty
        upnl = (ltp - avg) * qty if ltp is not None else None
        if upnl is not None:
            unrealised += upnl
        opened = date.fromisoformat(r["opened_at"][:10])
        views.append(PositionView(
            r["symbol"], qty, avg, ltp, upnl,
            float(ltp / avg - 1) if ltp is not None and avg else None,
            (on - opened).days))

    realised = sum((Decimal(r[0]) for r in conn.execute(
        "SELECT realised_pnl FROM positions WHERE portfolio_id=?", (portfolio_id,))), ZERO)
    charges = sum((Decimal(r[0]) for r in conn.execute(
        "SELECT charges_total FROM trades WHERE portfolio_id=?", (portfolio_id,))), ZERO)
    value = cash + market_value

    sells = conn.execute(
        "SELECT realised_pnl FROM trades WHERE portfolio_id=? AND side='sell'",
        (portfolio_id,)).fetchall()
    win_rate = (sum(1 for s in sells if Decimal(s[0]) > 0) / len(sells)) if sells else None

    deposits = conn.execute(
        "SELECT ts, amount FROM cash_ledger WHERE portfolio_id=? AND kind='deposit'",
        (portfolio_id,)).fetchall()
    flows = [(date.fromisoformat(d["ts"][:10]), -float(Decimal(d["amount"]))) for d in deposits]
    flows.append((on, float(value)))
    rate = xirr(flows) if start > 0 else None

    daily = conn.execute(
        "SELECT date, value, bench_close FROM portfolio_daily WHERE portfolio_id=? ORDER BY date",
        (portfolio_id,)).fetchall()
    series = [float(Decimal(d["value"])) for d in daily] + [float(value)]
    bench = [d["bench_close"] for d in daily if d["bench_close"] is not None]
    nifty = (bench[-1] / bench[0] - 1.0) if len(bench) >= 2 and bench[0] else None

    return Summary(
        portfolio_id=portfolio_id, name=pf["name"], start_capital=start, cash=cash,
        invested=to_money(invested), current_value=to_money(value),
        realised_pnl=to_money(realised), unrealised_pnl=to_money(unrealised),
        charges=to_money(charges), return_pct=float((value - start) / start),
        nifty_return_pct=nifty, xirr=rate,
        max_dd=max_drawdown(series) if len(series) >= 2 else None,
        win_rate=win_rate, as_of=as_of, positions=views,
    )


def snapshot(conn: sqlite3.Connection, ctx: PlayCtx, portfolio_id: int, day: date) -> None:
    """Record one day's value (for the equity curve, drawdown and the vs-Nifty comparison)."""
    cash = cash_balance(conn, portfolio_id)
    held = conn.execute("SELECT * FROM positions WHERE portfolio_id=? AND qty>0",
                        (portfolio_id,)).fetchall()
    marks = marketdata.last_closes(ctx.parquet_root, ctx.cfg, [r["symbol"] for r in held], day)
    invested = market = ZERO
    for r in held:
        avg = Decimal(r["avg_cost"])
        invested += avg * r["qty"]
        market += (marks[r["symbol"]][1] if r["symbol"] in marks else avg) * r["qty"]
    bench = load_benchmark(ctx.parquet_root, index_code=ctx.cfg.benchmark_index_code,
                           start=day, end=day)
    bench_close = float(bench["close"].iloc[-1]) if not bench.empty else None
    conn.execute(
        """INSERT INTO portfolio_daily (portfolio_id, date, value, cash, invested, bench_close)
           VALUES (?,?,?,?,?,?) ON CONFLICT (portfolio_id, date) DO UPDATE SET value=excluded.value,
               cash=excluded.cash, invested=excluded.invested, bench_close=excluded.bench_close""",
        (portfolio_id, day.isoformat(), str(to_money(cash + market)), str(cash),
         str(to_money(invested)), bench_close),
    )


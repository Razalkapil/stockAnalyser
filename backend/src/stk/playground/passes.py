"""The two ways an order gets filled: the delayed intraday feed, and the end-of-day fallback.

INTRADAY. The poller hands over today's candles for the symbols with open orders. Each active
order is tested against each candle in time order; the first touch wins. Bracket children are
created stamped with the END of the candle that filled their parent, so they can never fill on
that same candle.

EOD FALLBACK. If the feed is down, the order is marked ``pending_eod`` and NOTHING fills. After
the close, ``eod_pass`` tests it against the day's real (unadjusted) bar. A LIMIT or STOP order
can fill on that bar only if it was placed before the session opened -- otherwise the candle's
high/low would include price action from before the order existed, which is look-ahead. A LIMIT
or STOP placed mid-session with the feed down therefore waits for the NEXT session's bar. A
MARKET order is different: it fills at that bar's CLOSE if it was placed during the session (the
close happened strictly after it, so this is not look-ahead -- see ``domain.orders``), and is
CANCELLED if it is still unfilled once its own session has ended, rather than silently rolling to
a later session at a different price.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from stk.core.time import IST, MARKET_CLOSE, MARKET_OPEN
from stk.domain.fills import BarPrices, Lock, circuit_lock
from stk.domain.orders import Candle, OrderStatus, market_order_expired, resolve_oco, try_fill
from stk.playground import marketdata
from stk.playground.context import PlayCtx
from stk.playground.fills import DELAYED, EOD, FillContext, apply_fill
from stk.playground.orders import ACTIVE, PENDING_NOTE, set_status, to_domain
from stk.providers.base import IntradayCandle


@dataclass
class PassResult:
    fills: int = 0
    rejected: int = 0
    trade_ids: list[int] = field(default_factory=list)


def active_orders(conn: sqlite3.Connection, symbol: str | None = None) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(ACTIVE))
    sql = f"SELECT * FROM orders WHERE status IN ({marks})"
    args: list[object] = [*ACTIVE]
    if symbol:
        sql += " AND symbol=?"
        args.append(symbol)
    return conn.execute(sql + " ORDER BY order_id", args).fetchall()


def active_symbols(conn: sqlite3.Connection) -> list[str]:
    """Symbols that need candles: any with an active order or an open position."""
    rows = conn.execute(
        """SELECT symbol FROM orders WHERE status IN ('open','pending_eod')
           UNION SELECT symbol FROM positions WHERE qty > 0 ORDER BY symbol""").fetchall()
    return [r["symbol"] for r in rows]


def session_open(day: date) -> datetime:
    return datetime.combine(day, MARKET_OPEN, tzinfo=IST)


def session_close(day: date) -> datetime:
    return datetime.combine(day, MARKET_CLOSE, tzinfo=IST)


def _lock(ctx: PlayCtx, c: Candle, prev_close: Decimal | None) -> Lock:
    return circuit_lock(BarPrices(c.open, c.high, c.low, c.close), prev_close,
                        tuple(ctx.cfg.circuit_band_pcts), ctx.cfg.circuit_tolerance_pct)


def _evaluate(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    rows: list[sqlite3.Row],
    candle: Candle,
    lock: Lock,
    *,
    fc: FillContext,
    adv: Decimal | None,
    result: PassResult,
) -> None:
    """Fill whatever this one candle fills, honouring OCO groups (the stop wins a tie)."""
    seen: set[int] = set()
    for row in rows:
        if row["order_id"] in seen:
            continue
        chosen: sqlite3.Row | None = None
        fill_price: Decimal | None = None
        reason = ""
        if row["oco_group"]:
            group = [r for r in rows if r["oco_group"] == row["oco_group"]]
            seen |= {r["order_id"] for r in group}
            hit = resolve_oco([to_domain(r) for r in group], candle, lock)
            if hit is not None:
                order, fill = hit
                chosen = next(r for r in group if r["order_id"] == order.order_id)
                fill_price, reason = fill.price, fill.reason
        else:
            seen.add(row["order_id"])
            single = try_fill(to_domain(row), candle, lock)
            if single is not None:
                chosen, fill_price, reason = row, single.price, single.reason
        if chosen is None or fill_price is None:
            continue
        fresh = conn.execute("SELECT * FROM orders WHERE order_id=?",
                             (chosen["order_id"],)).fetchone()
        if fresh["status"] not in ACTIVE:  # an earlier fill in this pass already resolved it
            continue
        trade_id = apply_fill(conn, ctx, fresh, fill_price,
                              fc=FillContext(fc.basis, reason, fc.when, fc.feed_source,
                                             fc.feed_lag_s),
                              adv_turnover=adv)
        if trade_id is None:
            result.rejected += 1
        else:
            result.fills += 1
            result.trade_ids.append(trade_id)


def intraday_pass(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    candles: dict[str, list[IntradayCandle]],
    *,
    feed_source: str,
    feed_lag_s: int,
    candle_minutes: int = 5,
    prev_close: dict[str, Decimal | None] | None = None,
    adv: dict[str, Decimal] | None = None,
) -> PassResult:
    """Test every active order against the delayed candles, oldest candle first."""
    result = PassResult()
    prev_close = prev_close or {}
    adv = adv or {}
    for symbol, cs in candles.items():
        for ic in sorted(cs, key=lambda c: c.start):
            rows = active_orders(conn, symbol)
            if not rows:
                break
            candle_end = ic.start + timedelta(minutes=candle_minutes)
            candle = Candle(ic.start, ic.open, ic.high, ic.low, ic.close, ic.volume,
                            end=candle_end)
            fc = FillContext(DELAYED, "", candle_end, feed_source, feed_lag_s)
            _evaluate(conn, ctx, rows, candle, _lock(ctx, candle, prev_close.get(symbol)),
                      fc=fc, adv=adv.get(symbol), result=result)
    # The feed is alive for these symbols: anything parked as pending_eod goes back to open.
    restore_open(conn, list(candles))
    return result


def eod_pass(conn: sqlite3.Connection, ctx: PlayCtx, day: date) -> PassResult:
    """Fallback fills against the day's real bar. Run AFTER corporate actions for ``day``."""
    result = PassResult()
    rows = active_orders(conn)
    symbols = sorted({r["symbol"] for r in rows})
    bars = marketdata.bars_on_day(ctx.parquet_root, ctx.cfg, symbols, day)
    adv = marketdata.adv_turnover(ctx.parquet_root, ctx.cfg, symbols, day)
    close = session_close(day)
    covered = [s for s in symbols if s in bars]
    for symbol in symbols:
        bar = bars.get(symbol)
        if bar is None:
            continue  # no bar for it today (suspended / not ingested): leave it waiting
        candle = Candle(session_open(day), bar["open"] or Decimal(0), bar["high"] or Decimal(0),
                        bar["low"] or Decimal(0), bar["close"] or Decimal(0), end=close)
        fc = FillContext(EOD, "", close, None, None)
        _evaluate(conn, ctx, active_orders(conn, symbol), candle,
                  _lock(ctx, candle, bar["prev_close"]), fc=fc, adv=adv.get(symbol),
                  result=result)
    restore_open(conn, covered)
    _expire_market_orders(conn, covered, close)
    return result


def _expire_market_orders(conn: sqlite3.Connection, symbols: list[str], close: datetime) -> None:
    """A MARKET day order still active once its own session's bar has been tried is cancelled --
    a real broker does not carry a market order into a later session at a different price."""
    for row in active_orders(conn):
        if row["symbol"] not in symbols:
            continue
        if market_order_expired(to_domain(row), close):
            set_status(conn, row["order_id"], OrderStatus.CANCELLED,
                      note="market order not filled by session close — cancelled, not carried "
                           "forward to a later session", closed=True)


def mark_pending_eod(conn: sqlite3.Connection, symbols: list[str] | None = None) -> int:
    """The feed is stale: park OPEN orders as pending_eod. Nothing fills on stale data."""
    n = 0
    for row in active_orders(conn):
        if symbols is not None and row["symbol"] not in symbols:
            continue
        if row["status"] == OrderStatus.OPEN.value:
            set_status(conn, row["order_id"], OrderStatus.PENDING_EOD, note=PENDING_NOTE)
            n += 1
    return n


def restore_open(conn: sqlite3.Connection, symbols: list[str]) -> None:
    for row in active_orders(conn):
        if row["symbol"] in symbols and row["status"] == OrderStatus.PENDING_EOD.value:
            set_status(conn, row["order_id"], OrderStatus.OPEN, note=None)



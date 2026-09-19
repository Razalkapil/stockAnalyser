"""Turning a touched price into a trade: slippage, charges, cash, position, order status."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stk.core.money import to_money
from stk.domain.costs import Product, Side, compute_costs, dp_charge
from stk.domain.orders import OrderStatus
from stk.domain.positions import PositionError, apply_buy, apply_sell
from stk.domain.slippage import apply_slippage, slippage_bps
from stk.playground.context import PlayCtx
from stk.playground.ledger import (
    add_cash,
    cash_balance,
    get_position,
    iso,
    save_position,
)
from stk.playground.orders import ACTIVE, set_status
from stk.store.db.engine import transaction

ZERO = Decimal(0)
DELAYED = "delayed_intraday"
EOD = "eod_fallback"


@dataclass(frozen=True)
class FillContext:
    """Where a fill's price came from -- recorded on every trade and shown in the UI."""

    basis: str  # DELAYED | EOD
    reason: str  # e.g. 'limit_touch', 'stop_gap', 'market_open'
    when: datetime  # the moment the fill is booked (a candle's END, so nothing fills early)
    feed_source: str | None = None
    feed_lag_s: int | None = None


def _dp_already_charged(conn: sqlite3.Connection, pid: int, symbol: str, day: str) -> bool:
    """The DP charge is per scrip per DAY on the sell leg, however many sell orders fill."""
    return conn.execute(
        "SELECT 1 FROM trades WHERE portfolio_id=? AND symbol=? AND side='sell' "
        "AND substr(filled_at,1,10)=? AND CAST(json_extract(charges_json,'$.dp') AS REAL) > 0 "
        "LIMIT 1", (pid, symbol, day)).fetchone() is not None


def _reject(conn: sqlite3.Connection, order_id: int, note: str) -> None:
    set_status(conn, order_id, OrderStatus.REJECTED, note=note, closed=True)


def apply_fill(
    conn: sqlite3.Connection,
    ctx: PlayCtx,
    order: sqlite3.Row,
    raw_price: Decimal,
    *,
    fc: FillContext,
    adv_turnover: Decimal | None,
) -> int | None:
    """Book one fill. Returns the trade id, or None if the order was rejected instead.

    Everything happens in one transaction: a fill that half-applied (cash moved, position not)
    would be worse than no fill at all.
    """
    side = Side(order["side"])
    qty, pid, symbol = order["qty"], order["portfolio_id"], order["symbol"]
    day = fc.when.date()

    bps = slippage_bps(adv_turnover, ctx.cfg.tiers())
    price = to_money(apply_slippage(raw_price, side, bps))
    gross = price * qty
    rates = ctx.rates_for(order["exchange"], day)
    breakdown = compute_costs(side, Product(ctx.cfg.product), gross, rates)
    dp = ZERO
    if side is Side.SELL and Product(ctx.cfg.product) is Product.DELIVERY \
            and not _dp_already_charged(conn, pid, symbol, day.isoformat()):
        dp = dp_charge(rates)
    charges = breakdown.total + dp

    with transaction(conn):
        pos = get_position(conn, pid, order["exchange"], symbol)
        realised: Decimal | None = None
        if side is Side.BUY:
            if gross + charges > cash_balance(conn, pid):
                _reject(conn, order["order_id"],
                        f"insufficient cash at fill: needs {gross + charges}, "
                        f"have {cash_balance(conn, pid)}")
                return None
            new_pos = apply_buy(pos, qty, price)
        else:
            try:
                new_pos = apply_sell(pos, qty, price)
            except PositionError as exc:
                _reject(conn, order["order_id"], f"rejected at fill: {exc}")
                return None
            realised = new_pos.realised_pnl - pos.realised_pnl

        cur = conn.execute(
            """INSERT INTO trades (order_id, portfolio_id, exchange, symbol, side, qty, price,
                   raw_price, slippage_bps, gross_value, charges_total, charges_json,
                   realised_pnl, fill_basis, fill_reason, feed_source, feed_lag_s, journal_note,
                   filled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order["order_id"], pid, order["exchange"], symbol, side.value, qty, str(price),
             str(raw_price), str(bps), str(gross), str(charges),
             json.dumps({"brokerage": str(breakdown.brokerage), "stt": str(breakdown.stt),
                         "stamp_duty": str(breakdown.stamp_duty),
                         "exchange_txn": str(breakdown.exchange_txn), "ipft": str(breakdown.ipft),
                         "sebi_fee": str(breakdown.sebi_fee), "gst": str(breakdown.gst),
                         "dp": str(dp)}),
             str(realised) if realised is not None else None, fc.basis, fc.reason,
             fc.feed_source, fc.feed_lag_s, order["journal_note"], iso(fc.when)),
        )
        trade_id = int(cur.lastrowid or 0)
        save_position(conn, pid, order["exchange"], symbol, new_pos, when=fc.when)
        add_cash(conn, pid, side.value, -gross if side is Side.BUY else gross, fc.when,
                 ref_trade_id=trade_id, note=f"{side.value} {qty} {symbol} @ {price}")
        add_cash(conn, pid, "charges", -charges, fc.when, ref_trade_id=trade_id,
                 note="brokerage, STT, taxes" + (" + DP charge" if dp else ""))
        set_status(conn, order["order_id"], OrderStatus.FILLED, closed=True,
                   note=f"filled: {fc.reason}")
        _cancel_oco_siblings(conn, order)
        if side is Side.BUY:
            _create_bracket(conn, order, fc.when)
    return trade_id


def _cancel_oco_siblings(conn: sqlite3.Connection, order: sqlite3.Row) -> None:
    group = order["oco_group"]
    if not group:
        return
    for sib in conn.execute(
        f"SELECT order_id FROM orders WHERE oco_group=? AND order_id != ? "
        f"AND status IN ({','.join('?' * len(ACTIVE))})", (group, order["order_id"], *ACTIVE)
    ).fetchall():
        set_status(conn, sib["order_id"], OrderStatus.CANCELLED, closed=True,
                   note="cancelled: its OCO partner filled")


def _create_bracket(conn: sqlite3.Connection, parent: sqlite3.Row, when: datetime) -> None:
    """A filled buy with a bracket spawns its stop-loss / target sells as an OCO pair.

    They are stamped with the fill's END time, so they cannot fill on the very candle that
    filled their parent (that would be using price action from before the position existed).
    """
    stop, target = parent["bracket_stop"], parent["bracket_target"]
    if stop is None and target is None:
        return
    group = f"bk{parent['order_id']}"
    for kind, trig in (("SL", stop), ("TARGET", target)):
        if trig is None:
            continue
        conn.execute(
            """INSERT INTO orders (portfolio_id, exchange, symbol, side, order_type, qty,
                   trigger_price, oco_group, status, parent_order_id, created_at, updated_at)
               VALUES (?,?,?, 'sell', ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (parent["portfolio_id"], parent["exchange"], parent["symbol"], kind, parent["qty"],
             trig, group, parent["order_id"], iso(when), iso(when)),
        )

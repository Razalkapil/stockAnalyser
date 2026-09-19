"""Placing and cancelling paper orders."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from stk.core.time import now_ist
from stk.domain.costs import Side
from stk.domain.orders import (
    Order,
    OrderError,
    OrderStatus,
    OrderType,
    transition,
    validate_order,
)
from stk.playground.context import EXCHANGE
from stk.playground.ledger import LedgerError, get_position, iso
from stk.store.db.engine import transaction

ACTIVE = (OrderStatus.OPEN.value, OrderStatus.PENDING_EOD.value)
PENDING_NOTE = "Delayed feed down — will fall back to EOD fill"


def _dec(v: object) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def to_domain(row: sqlite3.Row) -> Order:
    return Order(
        order_id=row["order_id"], side=Side(row["side"]), type=OrderType(row["order_type"]),
        qty=row["qty"], created_at=datetime.fromisoformat(row["created_at"]),
        limit_price=_dec(row["limit_price"]), trigger_price=_dec(row["trigger_price"]),
        status=OrderStatus(row["status"]), oco_group=row["oco_group"],
    )


def _sellable(conn: sqlite3.Connection, pid: int, symbol: str) -> int:
    return get_position(conn, pid, EXCHANGE, symbol).qty


def place_order(
    conn: sqlite3.Connection,
    portfolio_id: int,
    symbol: str,
    *,
    side: Side,
    order_type: OrderType,
    qty: int,
    limit_price: Decimal | None = None,
    trigger_price: Decimal | None = None,
    bracket_stop: Decimal | None = None,
    bracket_target: Decimal | None = None,
    source_pick_id: int | None = None,
    journal_note: str | None = None,
) -> int:
    """Validate and store an order; it then waits (GTT-style) until a candle touches it.

    Cash is checked when the order FILLS, not now -- like a real resting order, it may become
    unaffordable by then and is rejected at that point. Sells are checked now: there is no
    shorting, so you cannot place a sell for shares you do not hold.
    """
    try:
        validate_order(side, order_type, qty, limit_price, trigger_price)
    except OrderError as exc:
        raise LedgerError(str(exc)) from exc
    if (bracket_stop or bracket_target) and side is not Side.BUY:
        raise LedgerError("a bracket (stop/target) can only be attached to a buy")
    for name, val in (("stop", bracket_stop), ("target", bracket_target)):
        if val is not None and val <= 0:
            raise LedgerError(f"the bracket {name} must be positive")
    if bracket_stop is not None and bracket_target is not None and bracket_stop >= bracket_target:
        raise LedgerError("the bracket stop must be below its target")

    symbol = symbol.strip().upper()
    if conn.execute("SELECT 1 FROM listings WHERE exchange=? AND symbol=? LIMIT 1",
                    (EXCHANGE, symbol)).fetchone() is None:
        raise LedgerError(f"{symbol} is not a known {EXCHANGE} symbol")
    if conn.execute("SELECT 1 FROM portfolios WHERE portfolio_id=? AND archived_at IS NULL",
                    (portfolio_id,)).fetchone() is None:
        raise LedgerError(f"no active portfolio {portfolio_id}")

    if side is Side.SELL:
        held = _sellable(conn, portfolio_id, symbol)
        if qty > held:
            raise LedgerError(f"cannot sell {qty} {symbol}: only {held} held (no shorting)")

    now = iso(now_ist())
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO orders (portfolio_id, exchange, symbol, side, order_type, qty,
                   limit_price, trigger_price, bracket_stop, bracket_target, status,
                   source_pick_id, journal_note, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?,?,?,?)""",
            (portfolio_id, EXCHANGE, symbol, side.value, order_type.value, qty,
             str(limit_price) if limit_price is not None else None,
             str(trigger_price) if trigger_price is not None else None,
             str(bracket_stop) if bracket_stop is not None else None,
             str(bracket_target) if bracket_target is not None else None,
             source_pick_id, journal_note, now, now),
        )
        return int(cur.lastrowid or 0)


def set_status(conn: sqlite3.Connection, order_id: int, new: OrderStatus, *,
               note: str | None = None, closed: bool = False) -> None:
    """Move an order through the state machine (illegal moves raise) and stamp the change."""
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no order {order_id}")
    transition(OrderStatus(row["status"]), new)
    now = iso(now_ist())
    conn.execute(
        "UPDATE orders SET status=?, status_note=?, updated_at=?, closed_at=? WHERE order_id=?",
        (new.value, note, now, now if closed else None, order_id),
    )


def cancel_order(conn: sqlite3.Connection, order_id: int) -> None:
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        raise LedgerError(f"no order {order_id}")
    if row["status"] not in ACTIVE:
        raise LedgerError(f"order {order_id} is already {row['status']}")
    set_status(conn, order_id, OrderStatus.CANCELLED, note="cancelled by you", closed=True)


def set_journal(conn: sqlite3.Connection, trade_id: int, note: str) -> None:
    cur = conn.execute("UPDATE trades SET journal_note=? WHERE trade_id=?", (note, trade_id))
    if cur.rowcount == 0:
        raise LedgerError(f"no trade {trade_id}")

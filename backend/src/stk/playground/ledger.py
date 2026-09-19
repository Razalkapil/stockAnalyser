"""Portfolios, cash and positions: the database side of the ledger."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from stk.core.money import to_money
from stk.core.time import now_ist
from stk.domain.positions import Position
from stk.store.db.engine import transaction

ZERO = Decimal(0)


class LedgerError(ValueError):
    pass


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def cash_balance(conn: sqlite3.Connection, portfolio_id: int) -> Decimal:
    """Cash is the LAST ledger row's balance -- there is no other copy to fall out of step."""
    row = conn.execute(
        "SELECT balance_after FROM cash_ledger WHERE portfolio_id=? ORDER BY entry_id DESC LIMIT 1",
        (portfolio_id,),
    ).fetchone()
    return Decimal(row["balance_after"]) if row else ZERO


def add_cash(
    conn: sqlite3.Connection,
    portfolio_id: int,
    kind: str,
    amount: Decimal,
    when: datetime,
    *,
    ref_trade_id: int | None = None,
    ref_ca_key: str | None = None,
    note: str | None = None,
) -> Decimal:
    """Append a signed cash movement and return the new balance."""
    balance = cash_balance(conn, portfolio_id) + amount
    conn.execute(
        """INSERT INTO cash_ledger (portfolio_id, ts, kind, amount, balance_after, ref_trade_id,
               ref_ca_key, note) VALUES (?,?,?,?,?,?,?,?)""",
        (portfolio_id, iso(when), kind, str(amount), str(balance), ref_trade_id, ref_ca_key, note),
    )
    return balance


def create_portfolio(conn: sqlite3.Connection, name: str, start_capital: Decimal) -> int:
    name = name.strip()
    if not name:
        raise LedgerError("a portfolio needs a name")
    if start_capital <= 0:
        raise LedgerError("starting capital must be positive")
    now = now_ist()
    with transaction(conn):
        try:
            cur = conn.execute(
                "INSERT INTO portfolios (name, start_capital, created_at) VALUES (?,?,?)",
                (name, str(to_money(start_capital)), iso(now)),
            )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(f"a portfolio called {name!r} already exists") from exc
        pid = int(cur.lastrowid or 0)
        add_cash(conn, pid, "deposit", to_money(start_capital), now, note="starting capital")
    return pid


def get_position(conn: sqlite3.Connection, portfolio_id: int, exchange: str, symbol: str
                 ) -> Position:
    row = conn.execute(
        "SELECT qty, avg_cost, realised_pnl FROM positions "
        "WHERE portfolio_id=? AND exchange=? AND symbol=?",
        (portfolio_id, exchange, symbol),
    ).fetchone()
    if row is None:
        return Position()
    return Position(row["qty"], Decimal(row["avg_cost"]), Decimal(row["realised_pnl"]))


def save_position(
    conn: sqlite3.Connection,
    portfolio_id: int,
    exchange: str,
    symbol: str,
    pos: Position,
    *,
    when: datetime,
) -> None:
    """Persist a position. A closed position keeps its row (its realised P&L must survive)."""
    conn.execute(
        """INSERT INTO positions (portfolio_id, exchange, symbol, qty, avg_cost, realised_pnl,
               opened_at, updated_at) VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT (portfolio_id, exchange, symbol) DO UPDATE SET qty=excluded.qty,
               avg_cost=excluded.avg_cost, realised_pnl=excluded.realised_pnl,
               updated_at=excluded.updated_at""",
        (portfolio_id, exchange, symbol, pos.qty, str(pos.avg_cost), str(pos.realised_pnl),
         iso(when), iso(when)),
    )


def held_at_start_of(
    conn: sqlite3.Connection, portfolio_id: int, exchange: str, symbol: str, *, day: str
) -> int:
    """Shares held BEFORE ``day`` began, by replaying the day's trades backwards.

    A dividend goes to whoever held the stock at the previous close, so a buy made ON the
    ex-date earns nothing and a sale made on it still does.
    """
    pos = get_position(conn, portfolio_id, exchange, symbol)
    qty = pos.qty
    for t in conn.execute(
        "SELECT side, qty FROM trades WHERE portfolio_id=? AND exchange=? AND symbol=? "
        "AND substr(filled_at, 1, 10) >= ?",
        (portfolio_id, exchange, symbol, day),
    ):
        qty += -t["qty"] if t["side"] == "buy" else t["qty"]
    return max(qty, 0)

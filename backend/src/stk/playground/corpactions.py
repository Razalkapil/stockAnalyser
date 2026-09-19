"""Corporate actions applied to paper holdings and resting orders.

IDEMPOTENT. Each (portfolio, action) is recorded in ``position_ca_events`` under the action's
ECONOMIC identity -- symbol, ex-date, type, ratio, factor -- not its ``source_hash``. NSE
republishes corrected rows as new hashes, so keying on the hash would apply one bonus twice. A
re-run for the same date therefore changes nothing.

SPLITS / BONUSES / CONSOLIDATIONS multiply the share count and divide the average cost (total
cost is conserved -- see ``domain.positions.apply_split_or_bonus``). RESTING ORDERS on the stock
are rescaled too: a stop-loss at Rs 950 on a stock that has just split 5:1 must become Rs 190,
or it would trigger instantly.

DIVIDENDS credit cash for the shares held at the PREVIOUS close (a buy on the ex-date earns
nothing; a sale on it still does).

RUN ORDER: this must run BEFORE ``eod_pass`` for the same date, because the ex-date's bar is
already post-action while the orders and positions are still in pre-action terms.

Not modelled, and said so: cash paid in lieu of a fractional share (its cost is written off),
rights issues, buybacks and demergers (they are counted in the run's metrics, not applied).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from stk.core.time import now_ist
from stk.domain.orders import OrderStatus
from stk.domain.positions import apply_split_or_bonus, dividend_cash
from stk.playground.context import EXCHANGE
from stk.playground.ledger import (
    add_cash,
    get_position,
    held_at_start_of,
    iso,
    save_position,
)
from stk.playground.orders import ACTIVE, set_status
from stk.store.db.engine import transaction

PRICE_ACTIONS = ("BONUS", "SPLIT", "CONSOLIDATION")
CASH_ACTIONS = ("DIVIDEND", "DISTRIBUTION")
PAISE = Decimal("0.01")


@dataclass
class CorpActionResult:
    splits_applied: int = 0
    orders_rescaled: int = 0
    dividends_credited: int = 0
    dividend_total: Decimal = Decimal(0)
    skipped_already_applied: int = 0


def _key(row: sqlite3.Row) -> str:
    return "|".join(str(x) for x in (row["symbol"], row["ex_date"], row["action_type"],
                                     row["ratio_numerator"], row["ratio_denominator"],
                                     row["price_factor"], row["dividend_per_share"]))


def _record(conn: sqlite3.Connection, pid: int, key: str, row: sqlite3.Row, detail: dict
            ) -> bool:
    """Claim (portfolio, action). False means it was already applied -- do nothing."""
    cur = conn.execute(
        """INSERT INTO position_ca_events (portfolio_id, ca_key, exchange, symbol, kind,
               detail_json, applied_at) VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (portfolio_id, ca_key) DO NOTHING""",
        (pid, key, EXCHANGE, row["symbol"], row["action_type"], json.dumps(detail, default=str),
         iso(now_ist())),
    )
    return cur.rowcount > 0


def _rescale_orders(
    conn: sqlite3.Connection,
    pid: int,
    symbol: str,
    *,
    price_factor: Decimal,
    volume_factor: Decimal,
    note: str,
) -> int:
    n = 0
    for o in conn.execute(
        f"SELECT * FROM orders WHERE portfolio_id=? AND symbol=? "
        f"AND status IN ({','.join('?' * len(ACTIVE))})", (pid, symbol, *ACTIVE)
    ).fetchall():
        def scale(v: str | None, o: sqlite3.Row = o) -> str | None:
            return None if v is None else str(
                (Decimal(v) * price_factor).quantize(PAISE, rounding=ROUND_HALF_UP))
        new_qty = int((Decimal(o["qty"]) * volume_factor).to_integral_value(rounding=ROUND_FLOOR))
        if new_qty < 1:
            set_status(conn, o["order_id"], OrderStatus.CANCELLED, closed=True,
                       note=f"cancelled: quantity became zero after {note}")
            continue
        conn.execute(
            "UPDATE orders SET qty=?, limit_price=?, trigger_price=?, bracket_stop=?, "
            "bracket_target=?, status_note=?, updated_at=? WHERE order_id=?",
            (new_qty, scale(o["limit_price"]), scale(o["trigger_price"]),
             scale(o["bracket_stop"]), scale(o["bracket_target"]),
             f"adjusted for {note}", iso(now_ist()), o["order_id"]),
        )
        n += 1
    return n


def apply_corporate_actions(conn: sqlite3.Connection, day: date) -> CorpActionResult:
    result = CorpActionResult()
    actions = conn.execute(
        """SELECT * FROM corporate_actions WHERE exchange=? AND ex_date=? AND parse_status='parsed'
           ORDER BY ca_id""", (EXCHANGE, day.isoformat())).fetchall()

    seen: set[str] = set()
    for row in actions:
        key = _key(row)
        if key in seen:  # NSE republished it: one economic event, one application
            continue
        seen.add(key)
        symbol, kind = row["symbol"], row["action_type"]
        holders = [r["portfolio_id"] for r in conn.execute(
            "SELECT DISTINCT portfolio_id FROM (SELECT portfolio_id FROM positions WHERE symbol=? "
            "AND qty>0 UNION SELECT portfolio_id FROM orders WHERE symbol=? AND status IN "
            "('open','pending_eod'))", (symbol, symbol))]

        for pid in holders:
            with transaction(conn):
                if kind in PRICE_ACTIONS and row["price_factor"] is not None:
                    pf, vf = Decimal(str(row["price_factor"])), Decimal(str(row["volume_factor"]))
                    pos = get_position(conn, pid, EXCHANGE, symbol)
                    res = apply_split_or_bonus(pos, vf)
                    detail = {"qty_before": pos.qty, "qty_after": res.position.qty,
                              "avg_before": str(pos.avg_cost),
                              "avg_after": str(res.position.avg_cost),
                              "dropped_shares": str(res.dropped_shares),
                              "dropped_cost": str(res.dropped_cost)}
                    if not _record(conn, pid, key, row, detail):
                        result.skipped_already_applied += 1
                        continue
                    if pos.qty:
                        save_position(conn, pid, EXCHANGE, symbol, res.position, when=now_ist())
                    result.orders_rescaled += _rescale_orders(
                        conn, pid, symbol, price_factor=pf, volume_factor=vf,
                        note=f"{kind.lower()} ({row['subject_raw']})")
                    result.splits_applied += 1
                elif kind in CASH_ACTIONS and row["dividend_per_share"]:
                    held = held_at_start_of(conn, pid, EXCHANGE, symbol, day=day.isoformat())
                    cash = dividend_cash(held, Decimal(str(row["dividend_per_share"])))
                    if not _record(conn, pid, key, row, {"qty": held, "cash": str(cash)}):
                        result.skipped_already_applied += 1
                        continue
                    if cash > 0:
                        add_cash(conn, pid, "dividend", cash, now_ist(), ref_ca_key=key,
                                 note=f"{symbol} {row['subject_raw']} x {held}")
                        result.dividends_credited += 1
                        result.dividend_total += cash
    return result

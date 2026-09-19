"""The paper-trading ledger, end to end: orders -> fills -> cash/positions -> corporate actions.

Every fill assertion reconciles against the SAME cost model the backtest uses, and the cash
ledger is checked to sum to the balance -- a ledger that does not reconcile is worse than none.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from integration.lake import write_panel_by_year
from stk.backtest.setup import make_rates_fn
from stk.config.backtest import load_backtest_config
from stk.core.time import IST, today_ist
from stk.domain.costs import Product, Side, compute_costs, dp_charge
from stk.domain.orders import OrderType
from stk.playground.context import PlayCtx
from stk.playground.corpactions import apply_corporate_actions
from stk.playground.fills import DELAYED, EOD
from stk.playground.ledger import (
    LedgerError,
    add_cash,
    cash_balance,
    create_portfolio,
    get_position,
)
from stk.playground.orders import PENDING_NOTE, cancel_order, place_order, set_journal
from stk.playground.passes import eod_pass, intraday_pass, mark_pending_eod
from stk.playground.performance import snapshot, summarise
from stk.providers.base import IntradayCandle
from stk.store.db.engine import connect, migrate

D = Decimal
TODAY = today_ist()
# The last day that actually has a bar: `today` may be a weekend, when the lake has none.
LAST = pd.bdate_range(end=TODAY, periods=1)[0].date()
BIG_ADV = {"AAA": D(10**9), "BBB": D(10**9)}  # >= Rs 50 cr -> the 5 bps slippage tier
FIVE_BPS = D("0.0005")


def at(hh: int, mm: int = 0, day: date | None = None) -> datetime:
    base = datetime.combine(day or TODAY, datetime.min.time(), tzinfo=IST)
    return base.replace(hour=hh, minute=mm)


def candle(hh, mm, o, h, low, *, c=None, day=None) -> IntradayCandle:
    return IntradayCandle(start=at(hh, mm, day), open=D(str(o)), high=D(str(h)), low=D(str(low)),
                          close=D(str(c if c is not None else o)), volume=10_000)


@pytest.fixture
def world(tmp_path):
    db, root = tmp_path / "app.db", tmp_path / "parquet"
    root.mkdir()
    migrate(db)
    days = [d.date() for d in pd.bdate_range(end=LAST, periods=15)]
    write_panel_by_year(root, days, {"AAA": [100.0] * len(days), "BBB": [50.0] * len(days)})
    conn = connect(db)
    for i, sym in enumerate(("AAA", "BBB"), start=1):
        conn.execute(
            """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
                   primary_exchange, status, first_seen_on, last_seen_on, updated_at)
               VALUES (?,?,?,?, 'NSE','ACTIVE','2020-01-01','2026-01-01','2026-01-01')""",
            (i, f"INE00{i}A01010", sym, f"{sym} Ltd"))
        conn.execute("INSERT INTO listings (security_id, exchange, symbol, series, source, "
                     "updated_at) VALUES (?, 'NSE', ?, 'EQ', 't', '2026-01-01')", (i, sym))
    cfg = load_backtest_config()
    ctx = PlayCtx(root, cfg, make_rates_fn())
    pid = create_portfolio(conn, "Main", D("1000000"))
    yield conn, ctx, pid
    conn.close()


def place(conn, pid, symbol="AAA", *, side=Side.BUY, type_=OrderType.MARKET, qty=10,
          created=None, **kw) -> int:
    oid = place_order(conn, pid, symbol, side=side, order_type=type_, qty=qty, **kw)
    conn.execute("UPDATE orders SET created_at=? WHERE order_id=?",
                 ((created or at(9, 30)).isoformat(timespec="seconds"), oid))
    return oid


def run(conn, ctx, candles, symbol="AAA", **kw):
    return intraday_pass(conn, ctx, {symbol: candles}, feed_source="test", feed_lag_s=600,
                         adv=BIG_ADV, **kw)


def order(conn, oid):
    return conn.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()


def trade(conn, oid):
    return conn.execute("SELECT * FROM trades WHERE order_id=?", (oid,)).fetchone()


def ledger_reconciles(conn, pid):
    rows = conn.execute("SELECT amount, balance_after FROM cash_ledger WHERE portfolio_id=? "
                        "ORDER BY entry_id", (pid,)).fetchall()
    running = D(0)
    for r in rows:
        running += D(r["amount"])
        assert running == D(r["balance_after"])  # every line agrees with the running total
    assert running == cash_balance(conn, pid)


class TestPortfolio:
    def test_starts_with_a_deposit_and_the_ledger_reconciles(self, world):
        conn, _ctx, pid = world
        assert cash_balance(conn, pid) == D("1000000.00")
        ledger_reconciles(conn, pid)

    def test_names_are_unique_and_capital_positive(self, world):
        conn, _ctx, _pid = world
        with pytest.raises(LedgerError, match="already exists"):
            create_portfolio(conn, "Main", D("1"))
        with pytest.raises(LedgerError, match="positive"):
            create_portfolio(conn, "Zero", D("0"))
        with pytest.raises(LedgerError, match="needs a name"):
            create_portfolio(conn, "  ", D("1"))


class TestPlacing:
    @pytest.mark.parametrize(("kw", "match"), [
        (dict(symbol="NOPE"), "not a known NSE symbol"),
        (dict(side=Side.SELL), "only 0 held"),
        (dict(side=Side.BUY, type_=OrderType.STOP_LOSS, trigger_price=D("90")), "sell-side"),
        (dict(type_=OrderType.LIMIT), "limit price"),
        (dict(qty=0), "at least 1"),
        (dict(bracket_stop=D("90"), bracket_target=D("80")), "below its target"),
        (dict(bracket_stop=D("-1")), "positive"),
    ])
    def test_rejected_at_the_door(self, world, kw, match):
        conn, _ctx, pid = world
        with pytest.raises(LedgerError, match=match):
            place(conn, pid, **kw)
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0

    def test_a_bracket_cannot_be_attached_to_a_sell(self, world):
        conn, _ctx, pid = world
        with pytest.raises(LedgerError):
            place_order(conn, pid, "AAA", side=Side.SELL, order_type=OrderType.MARKET, qty=1,
                        bracket_stop=D("1"))

    def test_an_archived_or_missing_portfolio_is_refused(self, world):
        conn, _ctx, _pid = world
        with pytest.raises(LedgerError, match="no active portfolio"):
            place(conn, 999)


class TestFillingAtTheDelayedFeed:
    def test_market_buy_fills_at_the_next_open_with_slippage_and_full_charges(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, qty=10)
        r = run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        assert r.fills == 1
        t = trade(conn, oid)
        assert t["fill_basis"] == DELAYED and t["feed_source"] == "test" and t["feed_lag_s"] == 600
        assert D(t["raw_price"]) == D("100") and D(t["price"]) == D("100.05")  # +5 bps
        gross = D("100.05") * 10
        want = compute_costs(Side.BUY, Product.DELIVERY, gross, ctx.rates_for("NSE", TODAY)).total
        assert D(t["charges_total"]) == want > 0
        assert cash_balance(conn, pid) == D("1000000") - gross - want
        pos = get_position(conn, pid, "NSE", "AAA")
        assert (pos.qty, pos.avg_cost) == (10, D("100.05"))  # cost excludes charges
        assert order(conn, oid)["status"] == "filled"
        ledger_reconciles(conn, pid)

    def test_charges_are_itemised_on_the_trade(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, qty=100)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        items = json.loads(trade(conn, oid)["charges_json"])
        assert set(items) == {"brokerage", "stt", "stamp_duty", "exchange_txn", "ipft",
                              "sebi_fee", "gst", "dp"}
        assert D(items["stt"]) > 0 and D(items["dp"]) == 0  # no DP charge on a buy

    def test_a_limit_that_is_never_touched_does_not_fill(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"))
        r = run(conn, ctx, [candle(9, 35, 100, 101, 96), candle(9, 40, 100, 102, 97)])
        assert r.fills == 0 and order(conn, oid)["status"] == "open"
        assert cash_balance(conn, pid) == D("1000000.00")

    def test_a_limit_touched_by_the_low_fills_at_the_limit_not_the_last_price(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"))
        run(conn, ctx, [candle(9, 35, 100, 101, 94, c=100)])
        assert D(trade(conn, oid)["raw_price"]) == D("95")
        assert trade(conn, oid)["fill_reason"] == "limit_touch"

    def test_price_action_before_the_order_existed_cannot_fill_it(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"), created=at(10, 0))
        run(conn, ctx, [candle(9, 55, 100, 101, 90)])  # the low was BEFORE the order
        assert order(conn, oid)["status"] == "open"

    def test_insufficient_cash_rejects_the_order_and_changes_nothing(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, qty=100_000)  # Rs 1 crore of stock on Rs 10 lakh
        r = run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        assert (r.fills, r.rejected) == (0, 1)
        o = order(conn, oid)
        assert o["status"] == "rejected" and "insufficient cash" in o["status_note"]
        assert cash_balance(conn, pid) == D("1000000.00")
        assert get_position(conn, pid, "NSE", "AAA").qty == 0
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0

    def test_a_fill_is_all_or_nothing(self, world):
        """If booking fails part-way (here: a sell that no longer has the shares), no cash moves."""
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        oid = place(conn, pid, side=Side.SELL, qty=10, created=at(9, 40))
        conn.execute("UPDATE positions SET qty=3")  # holdings vanished behind the order's back
        before = cash_balance(conn, pid)
        run(conn, ctx, [candle(9, 45, 100, 101, 99)])
        assert order(conn, oid)["status"] == "rejected"
        assert cash_balance(conn, pid) == before

    def test_rerunning_the_same_candles_does_not_fill_twice(self, world):
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        cs = [candle(9, 35, 100, 101, 99)]
        run(conn, ctx, cs)
        again = run(conn, ctx, cs)
        assert again.fills == 0
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


class TestSelling:
    def buy(self, conn, ctx, pid, qty=10):
        place(conn, pid, qty=qty)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])

    def test_sell_realises_gross_pnl_and_levies_the_dp_charge(self, world):
        conn, ctx, pid = world
        self.buy(conn, ctx, pid)
        oid = place(conn, pid, side=Side.SELL, qty=10, created=at(10, 0))
        run(conn, ctx, [candle(10, 5, 110, 111, 109)])
        t = trade(conn, oid)
        assert D(t["price"]) == D("109.9450") or D(t["price"]) == D("109.95")  # -5 bps of 110
        assert D(t["realised_pnl"]) == (D(t["price"]) - D("100.05")) * 10
        assert D(json.loads(t["charges_json"])["dp"]) == dp_charge(ctx.rates_for("NSE", TODAY))
        assert get_position(conn, pid, "NSE", "AAA").qty == 0
        ledger_reconciles(conn, pid)

    def test_the_dp_charge_is_once_per_scrip_per_day_across_partial_sells(self, world):
        conn, ctx, pid = world
        self.buy(conn, ctx, pid, qty=10)
        a = place(conn, pid, side=Side.SELL, qty=4, created=at(10, 0))
        b = place(conn, pid, side=Side.SELL, qty=6, created=at(10, 0))
        run(conn, ctx, [candle(10, 5, 110, 111, 109)])
        dps = sorted(D(json.loads(trade(conn, o)["charges_json"])["dp"]) for o in (a, b))
        assert dps[0] == 0 and dps[1] > 0

    def test_win_rate_counts_profitable_sells(self, world):
        conn, ctx, pid = world
        self.buy(conn, ctx, pid, qty=20)
        place(conn, pid, side=Side.SELL, qty=10, created=at(10, 0))
        run(conn, ctx, [candle(10, 5, 120, 121, 119)])  # a win
        place(conn, pid, side=Side.SELL, qty=10, created=at(10, 10))
        run(conn, ctx, [candle(10, 15, 80, 81, 79)])  # a loss
        assert summarise(conn, ctx, pid).win_rate == pytest.approx(0.5)


class TestBrackets:
    def bracket(self, conn, pid):
        return place(conn, pid, qty=10, bracket_stop=D("95"), bracket_target=D("110"))

    def test_entry_creates_an_oco_pair_sized_to_the_fill(self, world):
        conn, ctx, pid = world
        parent = self.bracket(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        kids = conn.execute("SELECT * FROM orders WHERE parent_order_id=? ORDER BY order_type",
                            (parent,)).fetchall()
        assert [(k["order_type"], k["side"], k["qty"], k["status"]) for k in kids] == [
            ("SL", "sell", 10, "open"), ("TARGET", "sell", 10, "open")]
        assert kids[0]["oco_group"] == kids[1]["oco_group"] == f"bk{parent}"

    def test_the_children_cannot_fill_on_the_candle_that_filled_their_parent(self, world):
        """That candle's low is below the stop, but the position did not exist for all of it.

        The real poller re-fetches the WHOLE day's candles on every poll, so the entry candle is
        seen again on the next poll -- the children's creation stamp (the candle's END) is what
        stops them filling on it. (Within a single pass they are simply not evaluated, which is
        why this test polls twice: one pass alone cannot tell the two defences apart.)
        """
        conn, ctx, pid = world
        self.bracket(conn, pid)
        entry_candle = candle(9, 35, 100, 112, 90)  # touches BOTH stop and target
        run(conn, ctx, [entry_candle])
        run(conn, ctx, [entry_candle])  # the next poll returns the same candle again
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1  # only the entry
        assert get_position(conn, pid, "NSE", "AAA").qty == 10
        stamped = conn.execute("SELECT created_at FROM orders WHERE parent_order_id IS NOT NULL"
                               ).fetchall()
        assert {datetime.fromisoformat(r[0]) for r in stamped} == {at(9, 40)}  # candle END

    def test_target_fills_later_and_cancels_the_stop(self, world):
        conn, ctx, pid = world
        parent = self.bracket(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99), candle(9, 40, 101, 111, 100)])
        kids = {k["order_type"]: k["status"] for k in conn.execute(
            "SELECT order_type, status FROM orders WHERE parent_order_id=?", (parent,))}
        assert kids == {"SL": "cancelled", "TARGET": "filled"}
        assert get_position(conn, pid, "NSE", "AAA").qty == 0
        ledger_reconciles(conn, pid)

    def test_the_stop_wins_when_one_candle_touches_both(self, world):
        conn, ctx, pid = world
        parent = self.bracket(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99), candle(9, 40, 100, 115, 90)])
        kids = {k["order_type"]: k["status"] for k in conn.execute(
            "SELECT order_type, status FROM orders WHERE parent_order_id=?", (parent,))}
        assert kids == {"SL": "filled", "TARGET": "cancelled"}

    def test_a_gap_through_the_stop_fills_at_the_worse_open(self, world):
        conn, ctx, pid = world
        parent = self.bracket(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99), candle(9, 40, 90, 92, 88)])
        sl = conn.execute("SELECT order_id FROM orders WHERE parent_order_id=? AND "
                          "order_type='SL'", (parent,)).fetchone()[0]
        assert D(trade(conn, sl)["raw_price"]) == D("90")  # not the 95 stop

    def test_a_rejected_entry_creates_no_children(self, world):
        conn, ctx, pid = world
        parent = place(conn, pid, qty=100_000, bracket_stop=D("95"))
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        assert conn.execute("SELECT COUNT(*) FROM orders WHERE parent_order_id=?",
                            (parent,)).fetchone()[0] == 0


class TestStaleFeedFallsBackToEod:
    def test_a_stale_feed_parks_orders_with_the_designs_message_and_fills_nothing(self, world):
        conn, _ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"))
        assert mark_pending_eod(conn) == 1
        o = order(conn, oid)
        assert o["status"] == "pending_eod" and o["status_note"] == PENDING_NOTE
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0

    def test_parking_is_idempotent(self, world):
        conn, _ctx, pid = world
        place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"))
        mark_pending_eod(conn)
        assert mark_pending_eod(conn) == 0

    def test_the_feed_coming_back_restores_and_can_fill_a_parked_order(self, world):
        conn, ctx, pid = world
        parked = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("95"))
        idle = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("50"))
        mark_pending_eod(conn)
        run(conn, ctx, [candle(9, 35, 100, 101, 94)])
        assert order(conn, parked)["status"] == "filled"
        assert order(conn, idle)["status"] == "open"  # back to open, note cleared
        assert order(conn, idle)["status_note"] is None

    def test_eod_fallback_fills_from_the_days_real_bar_and_says_so(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("100"),
                    created=at(10, 0, LAST - timedelta(days=3)))  # placed on an earlier day
        r = eod_pass(conn, ctx, LAST)
        assert r.fills == 1
        t = trade(conn, oid)
        assert t["fill_basis"] == EOD and t["feed_source"] is None
        assert D(t["raw_price"]) == D("100")
        assert datetime.fromisoformat(t["filled_at"]).hour == 15  # booked at the close

    def test_an_order_placed_mid_session_cannot_use_that_days_full_range(self, world):
        """Its high/low include price action from before the order existed -- that would be
        look-ahead. It waits for the NEXT session's bar."""
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.MARKET, created=at(11, 0, LAST))
        assert eod_pass(conn, ctx, LAST).fills == 0
        assert order(conn, oid)["status"] == "open"

    def test_an_order_placed_before_the_open_can_use_that_days_bar(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.MARKET, created=at(8, 30, LAST))
        assert eod_pass(conn, ctx, LAST).fills == 1
        assert trade(conn, oid)["fill_basis"] == EOD

    def test_a_symbol_with_no_bar_is_left_waiting_not_dropped(self, world):
        conn, ctx, pid = world
        oid = place(
            conn, pid, type_=OrderType.MARKET, created=at(8, 30, LAST - timedelta(days=2))
        )
        assert eod_pass(conn, ctx, LAST + timedelta(days=400)).fills == 0
        assert order(conn, oid)["status"] == "open"


class TestCancelAndJournal:
    def test_cancel_an_open_order(self, world):
        conn, _ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("50"))
        cancel_order(conn, oid)
        assert order(conn, oid)["status"] == "cancelled" and order(conn, oid)["closed_at"]

    def test_a_finished_order_cannot_be_cancelled(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        with pytest.raises(LedgerError, match="already filled"):
            cancel_order(conn, oid)

    def test_a_journal_note_can_be_added_to_a_trade(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        tid = trade(conn, oid)["trade_id"]
        set_journal(conn, tid, "bought the breakout")
        assert trade(conn, oid)["journal_note"] == "bought the breakout"
        with pytest.raises(LedgerError):
            set_journal(conn, 999, "x")

    def test_the_journal_note_from_placement_carries_onto_the_fill(self, world):
        conn, ctx, pid = world
        oid = place(conn, pid, journal_note="thesis: earnings beat")
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        assert trade(conn, oid)["journal_note"] == "thesis: earnings beat"


def add_action(conn, symbol, ex, kind, *, pf=None, vf=None, num=None, den=None, div=None,
               hash_="h1", subject="x"):
    conn.execute(
        """INSERT INTO corporate_actions (symbol, exchange, ex_date, subject_raw, action_type,
               dividend_per_share, ratio_numerator, ratio_denominator, price_factor,
               volume_factor, parse_status, parser_version, source, source_hash, captured_at)
           VALUES (?, 'NSE', ?, ?, ?, ?, ?, ?, ?, ?, 'parsed', 2, 't', ?, '2026-01-01')""",
        (symbol, ex.isoformat(), subject, kind, div, num, den, pf, vf, hash_))


class TestCorporateActions:
    def hold(self, conn, ctx, pid, qty=10):
        place(conn, pid, qty=qty, created=at(9, 30, TODAY - timedelta(days=5)))
        run(conn, ctx, [candle(9, 35, 100, 101, 99, day=TODAY - timedelta(days=5))])
        # the fill's day is the candle's day; keep the trade in the past so it predates ex-date

    def test_a_bonus_doubles_shares_halves_cost_and_keeps_cash(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        cash = cash_balance(conn, pid)
        add_action(conn, "AAA", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1, subject="Bonus 1:1")
        r = apply_corporate_actions(conn, TODAY)
        pos = get_position(conn, pid, "NSE", "AAA")
        assert r.splits_applied == 1 and (pos.qty, pos.avg_cost) == (20, D("50.025"))
        assert pos.cost_basis == D("100.05") * 10  # total cost is conserved
        assert cash_balance(conn, pid) == cash

    def test_resting_orders_are_rescaled_so_a_stop_does_not_trigger_instantly(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        stop = place(conn, pid, side=Side.SELL, type_=OrderType.STOP_LOSS, qty=10,
                     trigger_price=D("90"))
        add_action(conn, "AAA", TODAY, "SPLIT", pf=0.2, vf=5.0, subject="split 5:1")
        r = apply_corporate_actions(conn, TODAY)
        o = order(conn, stop)
        assert r.orders_rescaled == 1
        assert (D(o["trigger_price"]), o["qty"]) == (D("18.00"), 50)
        assert "adjusted for split" in o["status_note"]

    def test_running_it_twice_changes_nothing(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        add_action(conn, "AAA", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1)
        apply_corporate_actions(conn, TODAY)
        again = apply_corporate_actions(conn, TODAY)
        assert again.splits_applied == 0 and again.skipped_already_applied == 1
        assert get_position(conn, pid, "NSE", "AAA").qty == 20

    def test_a_republished_row_with_a_new_hash_is_still_one_bonus(self, world):
        """NSE republishing a corrected subject creates a second row by design."""
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        add_action(conn, "AAA", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1, hash_="h1")
        add_action(conn, "AAA", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1, hash_="h2")
        apply_corporate_actions(conn, TODAY)
        assert get_position(conn, pid, "NSE", "AAA").qty == 20  # 20, not 40

    def test_a_reverse_split_that_leaves_less_than_a_share_cancels_the_orders(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        oid = place(conn, pid, side=Side.SELL, qty=5, type_=OrderType.TARGET,
                    trigger_price=D("150"))
        add_action(conn, "AAA", TODAY, "CONSOLIDATION", pf=100.0, vf=0.01)
        apply_corporate_actions(conn, TODAY)
        assert order(conn, oid)["status"] == "cancelled"

    def test_a_dividend_credits_cash_for_shares_held_at_the_previous_close(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        before = cash_balance(conn, pid)
        add_action(conn, "AAA", TODAY, "DIVIDEND", div=17.7, subject="Dividend - Rs 17.70")
        r = apply_corporate_actions(conn, TODAY)
        assert r.dividends_credited == 1 and r.dividend_total == D("177.00")
        assert cash_balance(conn, pid) == before + D("177.00")
        ledger_reconciles(conn, pid)

    def test_a_buy_on_the_ex_date_earns_no_dividend(self, world):
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])  # bought TODAY, the ex-date
        before = cash_balance(conn, pid)
        add_action(conn, "AAA", TODAY, "DIVIDEND", div=17.7)
        assert apply_corporate_actions(conn, TODAY).dividends_credited == 0
        assert cash_balance(conn, pid) == before

    def test_a_dividend_is_credited_once(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        add_action(conn, "AAA", TODAY, "DIVIDEND", div=5.0)
        apply_corporate_actions(conn, TODAY)
        before = cash_balance(conn, pid)
        apply_corporate_actions(conn, TODAY)
        assert cash_balance(conn, pid) == before

    def test_a_stock_nobody_holds_is_ignored(self, world):
        conn, _ctx, _pid = world
        add_action(conn, "BBB", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1)
        r = apply_corporate_actions(conn, TODAY)
        assert (r.splits_applied, r.dividends_credited) == (0, 0)

    def test_unparsed_actions_are_never_applied(self, world):
        conn, ctx, pid = world
        self.hold(conn, ctx, pid, 10)
        add_action(conn, "AAA", TODAY, "BONUS", pf=0.5, vf=2.0, num=1, den=1)
        conn.execute("UPDATE corporate_actions SET parse_status='ambiguous'")
        apply_corporate_actions(conn, TODAY)
        assert get_position(conn, pid, "NSE", "AAA").qty == 10


class TestPerformance:
    def test_summary_reconciles(self, world):
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        s = summarise(conn, ctx, pid)
        assert s.cash + s.invested == s.start_capital - s.charges  # nothing is unaccounted for
        assert s.positions[0].symbol == "AAA" and s.positions[0].ltp == D("100")
        assert s.unrealised_pnl == (D("100") - D("100.05")) * 10  # marked at the real close
        assert s.current_value == s.cash + D("1000.00")
        assert s.return_pct < 0  # slippage and charges are a real cost
        assert s.realised_pnl == 0 and s.win_rate is None  # no sells yet: unknown, not 0%

    def test_xirr_is_undefined_on_day_one_not_zero(self, world):
        conn, ctx, pid = world
        assert summarise(conn, ctx, pid).xirr is None

    def test_xirr_after_time_has_passed(self, world):
        """Rs 10 lakh deposited exactly 365 days ago, now worth Rs 11 lakh: XIRR is 10%."""
        conn, ctx, pid = world
        year_ago = at(9, 0, TODAY - timedelta(days=365)).isoformat()
        conn.execute("UPDATE cash_ledger SET ts=? WHERE kind='deposit'", (year_ago,))
        add_cash(conn, pid, "dividend", D("100000"), at(9, 0), note="a gain")
        assert summarise(conn, ctx, pid).xirr == pytest.approx(0.10, abs=1e-6)

    def test_xirr_of_a_flat_year_is_zero_not_undefined(self, world):
        conn, ctx, pid = world
        conn.execute("UPDATE cash_ledger SET ts=? WHERE kind='deposit'",
                     (at(9, 0, TODAY - timedelta(days=365)).isoformat(),))
        assert summarise(conn, ctx, pid).xirr == pytest.approx(0.0, abs=1e-9)

    def test_snapshots_are_idempotent_and_drive_the_drawdown(self, world):
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        days = [TODAY - timedelta(days=2), TODAY - timedelta(days=1)]
        for d in days:
            snapshot(conn, ctx, pid, d)
            snapshot(conn, ctx, pid, d)  # again
        assert conn.execute("SELECT COUNT(*) FROM portfolio_daily").fetchone()[0] == 2
        conn.execute("UPDATE portfolio_daily SET value='1000000' WHERE date=?",
                     (days[0].isoformat(),))
        conn.execute("UPDATE portfolio_daily SET value='900000' WHERE date=?",
                     (days[1].isoformat(),))
        assert summarise(conn, ctx, pid).max_dd == pytest.approx(-0.1, abs=0.02)

    def test_a_position_with_no_price_is_valued_at_cost_not_zero(self, world):
        conn, ctx, pid = world
        place(conn, pid, qty=10)
        run(conn, ctx, [candle(9, 35, 100, 101, 99)])
        conn.execute("UPDATE positions SET symbol='ZZZ'")  # no bars exist for ZZZ
        s = summarise(conn, ctx, pid)
        assert s.positions[0].ltp is None and s.positions[0].unrealised is None
        assert s.current_value == s.cash + D("100.05") * 10

    def test_unknown_portfolio(self, world):
        conn, ctx, _pid = world
        with pytest.raises(KeyError):
            summarise(conn, ctx, 999)



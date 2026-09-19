"""Portfolio and order endpoints. All money in responses is a float for DISPLAY; requests carry
exact Decimals, and nothing here does arithmetic on the floats."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from stk.api import schemas as s
from stk.api.deps import Conn, require_token
from stk.domain.costs import Product, Side, compute_costs, dp_charge
from stk.domain.orders import OrderType
from stk.domain.slippage import apply_slippage, slippage_bps
from stk.playground import marketdata
from stk.playground.context import EXCHANGE, PlayCtx
from stk.playground.ledger import LedgerError, create_portfolio
from stk.playground.orders import cancel_order, place_order, set_journal
from stk.playground.performance import Summary, summarise

router = APIRouter(dependencies=[Depends(require_token)])


def play_ctx(request: Request) -> PlayCtx:
    ctx: PlayCtx = request.app.state.play_ctx
    return ctx


Play = Annotated[PlayCtx, Depends(play_ctx)]


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _summary(x: Summary) -> s.PortfolioSummary:
    return s.PortfolioSummary(
        id=x.portfolio_id, name=x.name, start_capital=float(x.start_capital), cash=float(x.cash),
        invested=float(x.invested), current_value=float(x.current_value),
        realised_pnl=float(x.realised_pnl), unrealised_pnl=float(x.unrealised_pnl),
        charges=float(x.charges), return_pct=x.return_pct, nifty_return_pct=x.nifty_return_pct,
        xirr=x.xirr, max_dd=x.max_dd, win_rate=x.win_rate,
        as_of=x.as_of.isoformat() if x.as_of else None,
    )


def _err(exc: Exception) -> HTTPException:
    return HTTPException(422, str(exc))



@router.get("/api/portfolios", response_model=list[s.PortfolioSummary])
def portfolios(conn: Conn, ctx: Play) -> list[s.PortfolioSummary]:
    ids = [x[0] for x in conn.execute(
        "SELECT portfolio_id FROM portfolios WHERE archived_at IS NULL ORDER BY portfolio_id")]
    return [_summary(summarise(conn, ctx, i)) for i in ids]

@router.post("/api/portfolios", response_model=s.PortfolioSummary, status_code=201)
def new_portfolio(body: s.NewPortfolio, conn: Conn, ctx: Play) -> s.PortfolioSummary:
    try:
        pid = create_portfolio(conn, body.name, body.start_capital)
    except LedgerError as exc:
        raise _err(exc) from exc
    return _summary(summarise(conn, ctx, pid))

@router.get("/api/portfolios/{pid}", response_model=s.PortfolioDetail)
def portfolio(pid: int, conn: Conn, ctx: Play) -> s.PortfolioDetail:
    try:
        x = summarise(conn, ctx, pid)
    except KeyError as exc:
        raise HTTPException(404, f"no portfolio {pid}") from exc
    orders = conn.execute(
        """SELECT * FROM orders WHERE portfolio_id=? AND (status IN ('open','pending_eod')
           OR closed_at >= date('now','-7 day')) ORDER BY order_id DESC LIMIT 100""",
        (pid,)).fetchall()
    trades = conn.execute("SELECT * FROM trades WHERE portfolio_id=? ORDER BY trade_id DESC "
                          "LIMIT 100", (pid,)).fetchall()
    daily = conn.execute("SELECT date, value, bench_close FROM portfolio_daily WHERE "
                         "portfolio_id=? ORDER BY date", (pid,)).fetchall()
    first_bench = next((d["bench_close"] for d in daily if d["bench_close"]), None)
    return s.PortfolioDetail(
        **_summary(x).model_dump(),
        positions=[s.PositionOut(
            symbol=p.symbol, qty=p.qty, avg=float(p.avg_cost), ltp=_f(p.ltp), pnl=_f(p.unrealised),
            pnl_pct=p.unrealised_pct, days=p.days_held) for p in x.positions],
        orders=[s.OrderOut(
            id=o["order_id"], symbol=o["symbol"], side=o["side"], type=o["order_type"],
            qty=o["qty"], price=float(o["limit_price"] or o["trigger_price"] or 0) or None,
            status=o["status"], status_note=o["status_note"], created=o["created_at"],
            journal_note=o["journal_note"],
            bracket_stop=float(o["bracket_stop"]) if o["bracket_stop"] else None,
            bracket_target=float(o["bracket_target"]) if o["bracket_target"] else None,
            parent_order_id=o["parent_order_id"]) for o in orders],
        trades=[s.TradeOut(
            id=t["trade_id"], order_id=t["order_id"], symbol=t["symbol"], side=t["side"],
            qty=t["qty"], fill=float(t["price"]), time=t["filled_at"],
            charges=float(t["charges_total"]),
            realised_pnl=float(t["realised_pnl"]) if t["realised_pnl"] else None,
            fill_basis=t["fill_basis"], delayed=t["fill_basis"] == "delayed_intraday",
            fill_reason=t["fill_reason"], feed_lag_s=t["feed_lag_s"],
            journal_note=t["journal_note"]) for t in trades],
        curve_dates=[d["date"] for d in daily],
        curve=[float(d["value"]) for d in daily],
        nifty_curve=([d["bench_close"] / first_bench * float(daily[0]["value"])
                      for d in daily if d["bench_close"]]
                     if first_bench and all(d["bench_close"] for d in daily) else []),
    )

@router.post("/api/orders", status_code=201)
def new_order(body: s.NewOrder, conn: Conn) -> dict[str, int]:
    try:
        oid = place_order(
            conn, body.portfolio_id, body.symbol, side=Side(body.side.lower()),
            order_type=OrderType(body.type.upper()), qty=body.qty,
            limit_price=body.limit_price, trigger_price=body.trigger_price,
            bracket_stop=body.bracket_stop, bracket_target=body.bracket_target,
            source_pick_id=body.pick_id, journal_note=body.journal_note)
    except (LedgerError, ValueError) as exc:
        raise _err(exc) from exc
    return {"id": oid}

@router.delete("/api/orders/{oid}")
def delete_order(oid: int, conn: Conn) -> dict[str, str]:
    try:
        cancel_order(conn, oid)
    except LedgerError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "cancelled"}

@router.post("/api/orders/preview", response_model=s.CostPreview)
def preview(body: s.PreviewRequest, ctx: Play) -> s.CostPreview:
    """What an order would cost, using the SAME model the fills use -- so the ticket's
    estimate is not a different number from what actually gets booked."""
    if body.qty < 1 or body.price <= 0:
        raise HTTPException(422, "quantity and price must be positive")
    side = Side(body.side.lower())
    today = date.today()
    adv = marketdata.adv_turnover(ctx.parquet_root, ctx.cfg, [body.symbol.upper()], today)
    bps = slippage_bps(adv.get(body.symbol.upper()), ctx.cfg.tiers())
    px = apply_slippage(body.price, side, bps)
    value = px * body.qty
    rates = ctx.rates_for(EXCHANGE, today)
    b = compute_costs(side, Product(ctx.cfg.product), value, rates)
    dp = dp_charge(rates) if side is Side.SELL else Decimal(0)
    charges = b.total + dp
    return s.CostPreview(
        price=float(body.price), est_price=float(px), slippage_bps=float(bps),
        value=float(value), charges=float(charges), dp_charge=float(dp),
        total=float(value + charges if side is Side.BUY else value - charges),
        charge_breakdown={"brokerage": float(b.brokerage), "stt": float(b.stt),
                          "stamp_duty": float(b.stamp_duty),
                          "exchange_txn": float(b.exchange_txn), "ipft": float(b.ipft),
                          "sebi_fee": float(b.sebi_fee), "gst": float(b.gst),
                          "dp": float(dp)},
        note="Estimate at today's rates and the liquidity-tiered slippage the fill engine uses.",
    )

@router.patch("/api/trades/{tid}")
def journal(tid: int, body: s.JournalUpdate, conn: Conn) -> dict[str, str]:
    try:
        set_journal(conn, tid, body.note)
    except LedgerError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "ok"}


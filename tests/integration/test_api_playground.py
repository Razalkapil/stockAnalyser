"""Portfolio and order endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from integration.lake import write_panel_by_year
from integration.test_playground import LAST, at, candle
from stk.api import auth
from stk.api.app import create_app
from stk.backtest.setup import make_rates_fn
from stk.config.backtest import load_backtest_config
from stk.domain.costs import Product, Side, compute_costs, dp_charge
from stk.playground.context import PlayCtx
from stk.playground.passes import intraday_pass
from stk.store.db.engine import connect, migrate

D = Decimal


@pytest.fixture
def api(tmp_path):
    db, root = tmp_path / "app.db", tmp_path / "parquet"
    root.mkdir()
    migrate(db)
    days = [d.date() for d in pd.bdate_range(end=LAST, periods=15)]
    write_panel_by_year(root, days, {"AAA": [100.0] * 15})
    conn = connect(db)
    conn.execute(
        """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
               primary_exchange, status, first_seen_on, last_seen_on, updated_at)
           VALUES (1,'INE001A01010','AAA','AAA Ltd','NSE','ACTIVE','2020-01-01','2026-01-01',
                   '2026-01-01')""")
    conn.execute("INSERT INTO listings (security_id, exchange, symbol, series, source, updated_at)"
                 " VALUES (1,'NSE','AAA','EQ','t','2026-01-01')")
    token = auth.create_token(conn, "t")
    conn.close()
    cfg = load_backtest_config()
    app = create_app(sqlite_path=db, parquet_root=root, cfg=cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    ctx = PlayCtx(root, cfg, make_rates_fn())
    return client, db, ctx, app


def make_portfolio(client, name="Main", capital="1000000"):
    r = client.post("/api/portfolios", json={"name": name, "startCapital": capital})
    assert r.status_code == 201, r.text
    return r.json()


class TestAuth:
    @pytest.mark.parametrize(("method", "path"), [
        ("get", "/api/portfolios"), ("get", "/api/portfolios/1"), ("post", "/api/orders"),
        ("delete", "/api/orders/1"), ("post", "/api/orders/preview"), ("patch", "/api/trades/1")])
    def test_every_route_needs_a_token(self, api, method, path):
        r = getattr(TestClient(api[3]), method)(path)
        assert r.status_code == 401


class TestPortfolios:
    def test_create_and_list(self, api):
        client = api[0]
        p = make_portfolio(client)
        assert p["name"] == "Main" and p["cash"] == 1_000_000 and p["currentValue"] == 1_000_000
        assert p["returnPct"] == 0 and p["xirr"] is None and p["winRate"] is None
        assert [x["id"] for x in client.get("/api/portfolios").json()] == [p["id"]]

    def test_duplicate_name_and_bad_capital_are_422(self, api):
        client = api[0]
        make_portfolio(client)
        assert client.post("/api/portfolios", json={"name": "Main", "startCapital": "5"}
                           ).status_code == 422
        assert client.post("/api/portfolios", json={"name": "X", "startCapital": "0"}
                           ).status_code == 422

    def test_detail_shape_matches_the_designs_portfolio_contract(self, api):
        client = api[0]
        pid = make_portfolio(client)["id"]
        d = client.get(f"/api/portfolios/{pid}").json()
        # design: id, name, startCapital, cash, invested, currentValue, realisedPnl,
        # unrealisedPnl, charges, returnPct, niftyReturnPct, xirr, maxDD, winRate + lists
        for key in ("id", "name", "startCapital", "cash", "invested", "currentValue",
                    "realisedPnl", "unrealisedPnl", "charges", "returnPct", "niftyReturnPct",
                    "xirr", "maxDd", "winRate", "positions", "orders", "trades", "curve"):
            assert key in d, key
        assert d["positions"] == d["orders"] == d["trades"] == []

    def test_unknown_portfolio_is_404(self, api):
        assert api[0].get("/api/portfolios/999").status_code == 404


class TestOrders:
    def order(self, pid, **over):
        body = {"portfolioId": pid, "symbol": "AAA", "side": "buy", "type": "MARKET", "qty": 10}
        body.update(over)
        return body

    def test_place_lists_as_open_and_can_be_cancelled(self, api):
        client = api[0]
        pid = make_portfolio(client)["id"]
        r = client.post("/api/orders", json=self.order(
            pid, type="LIMIT", limitPrice="95", journalNote="dip buy"))
        assert r.status_code == 201
        o = client.get(f"/api/portfolios/{pid}").json()["orders"][0]
        assert (o["symbol"], o["side"], o["type"], o["status"], o["price"]) == (
            "AAA", "buy", "LIMIT", "open", 95.0)
        assert o["journalNote"] == "dip buy"
        assert client.delete(f"/api/orders/{o['id']}").status_code == 200
        again = client.get(f"/api/portfolios/{pid}").json()["orders"][0]
        assert again["status"] == "cancelled"
        assert client.delete(f"/api/orders/{o['id']}").status_code == 409  # already cancelled

    @pytest.mark.parametrize(("over", "msg"), [
        ({"symbol": "NOPE"}, "not a known NSE symbol"),
        ({"side": "sell"}, "only 0 held"),
        ({"type": "LIMIT"}, "limit price"),
        ({"type": "SL", "triggerPrice": "90"}, "sell-side"),
        ({"qty": 0}, "at least 1"),
    ])
    def test_invalid_orders_are_422_with_a_reason(self, api, over, msg):
        client = api[0]
        pid = make_portfolio(client)["id"]
        r = client.post("/api/orders", json=self.order(pid, **over))
        assert r.status_code == 422 and msg in r.json()["detail"]

    def test_a_fill_appears_as_a_position_and_a_delayed_feed_trade(self, api):
        client, db, ctx, _ = api
        pid = make_portfolio(client)["id"]
        client.post("/api/orders", json=self.order(pid, qty=10))
        conn = connect(db)
        conn.execute("UPDATE orders SET created_at=?", (at(9, 30).isoformat(),))
        intraday_pass(conn, ctx, {"AAA": [candle(9, 35, 100, 101, 99)]}, feed_source="yf",
                      feed_lag_s=840, adv={"AAA": D(10**9)})
        conn.close()
        d = client.get(f"/api/portfolios/{pid}").json()
        (pos,) = d["positions"]
        assert (pos["symbol"], pos["qty"], pos["ltp"]) == ("AAA", 10, 100.0)
        assert pos["avg"] == pytest.approx(100.05)
        (t,) = d["trades"]
        assert t["delayed"] is True and t["fillBasis"] == "delayed_intraday"
        assert t["feedLagS"] == 840 and t["charges"] > 0 and t["fillReason"] == "market_open"
        assert d["charges"] == pytest.approx(t["charges"])
        assert d["cash"] == pytest.approx(1_000_000 - 100.05 * 10 - t["charges"])

    def test_journal_note_on_a_trade(self, api):
        client, db, ctx, _ = api
        pid = make_portfolio(client)["id"]
        client.post("/api/orders", json=self.order(pid))
        conn = connect(db)
        conn.execute("UPDATE orders SET created_at=?", (at(9, 30).isoformat(),))
        intraday_pass(conn, ctx, {"AAA": [candle(9, 35, 100, 101, 99)]}, feed_source="yf",
                      feed_lag_s=0, adv={"AAA": D(10**9)})
        conn.close()
        tid = client.get(f"/api/portfolios/{pid}").json()["trades"][0]["id"]
        assert client.patch(f"/api/trades/{tid}", json={"note": "followed the plan"}
                            ).status_code == 200
        assert client.get(f"/api/portfolios/{pid}").json()["trades"][0]["journalNote"] == \
            "followed the plan"
        assert client.patch("/api/trades/999", json={"note": "x"}).status_code == 404

    def test_a_bracket_is_accepted_on_a_buy(self, api):
        client = api[0]
        pid = make_portfolio(client)["id"]
        r = client.post("/api/orders", json=self.order(pid, bracketStop="90", bracketTarget="120"))
        assert r.status_code == 201
        o = client.get(f"/api/portfolios/{pid}").json()["orders"][0]
        assert (o["bracketStop"], o["bracketTarget"]) == (90.0, 120.0)


class TestCostPreview:
    def test_matches_the_cost_model_the_fills_use(self, api):
        client, _db, ctx, _ = api
        r = client.post("/api/orders/preview",
                        json={"symbol": "AAA", "side": "buy", "qty": 10, "price": "2945"}).json()
        px = D(str(r["estPrice"]))
        want = compute_costs(Side.BUY, Product.DELIVERY, px * 10,
                             ctx.rates_for("NSE", date.today()))
        assert r["value"] == pytest.approx(float(px * 10))
        assert r["charges"] == pytest.approx(float(want.total), abs=0.01)
        assert r["total"] == pytest.approx(r["value"] + r["charges"])  # a buy costs value + charges
        assert r["dpCharge"] == 0 and r["slippageBps"] > 0
        assert set(r["chargeBreakdown"]) >= {"stt", "stamp_duty", "gst", "dp"}

    def test_a_sell_adds_the_dp_charge_and_nets_charges_off_the_proceeds(self, api):
        client, _db, ctx, _ = api
        r = client.post("/api/orders/preview",
                        json={"symbol": "AAA", "side": "sell", "qty": 10, "price": "2945"}).json()
        assert r["dpCharge"] == pytest.approx(float(dp_charge(ctx.rates_for("NSE", date.today()))))
        assert r["total"] == pytest.approx(r["value"] - r["charges"])
        assert r["estPrice"] < 2945  # adverse slippage on a sell

    def test_bad_input_is_422(self, api):
        client = api[0]
        assert client.post("/api/orders/preview", json={
            "symbol": "AAA", "side": "buy", "qty": 0, "price": "10"}).status_code == 422

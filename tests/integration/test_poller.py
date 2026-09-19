"""The poller: fresh feed fills, stale feed parks, outages are recorded, raw bytes are kept."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from integration.test_playground import LAST, at, candle, place, world  # noqa: F401 (fixture)
from stk.config.playground import PollerConfig
from stk.core.errors import DataNotPublished, ProviderUnavailable
from stk.domain.costs import Side
from stk.domain.orders import OrderType
from stk.ingest.calendar import SEGMENT
from stk.playground.nightly import run_eod
from stk.playground.orders import PENDING_NOTE
from stk.playground.poller import market_is_open, poll_once
from stk.providers.base import IntradayCandle, IntradayProvider, ProviderCapabilities, RawArtifact

D = Decimal
CFG = PollerConfig(interval="5m", poll_every_s=180, stale_after_s=1500)


class FakeFeed(IntradayProvider):
    """Serves canned candles per symbol; a value that is an Exception is raised instead."""

    def __init__(self, by_symbol: dict[str, list[IntradayCandle] | Exception]) -> None:
        self.by_symbol = by_symbol
        self.calls: list[str] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(name="fake_feed", exchanges=frozenset({"NSE"}),
                                    supports_intraday=True, is_approximate=True)

    def fetch_candles_raw(self, symbol, exchange, interval="5m") -> RawArtifact:
        self.calls.append(symbol)
        v = self.by_symbol[symbol]
        if isinstance(v, Exception):
            raise v
        body = json.dumps({"symbol": symbol, "n": len(v)}).encode()
        return RawArtifact(source="fake_feed", business_date=None, url=f"fake://{symbol}",
                           content=body, content_type="application/json", http_status=200,
                           fetched_at=datetime.now(UTC))

    def parse_candles(self, artifact) -> list[IntradayCandle]:
        return self.by_symbol[json.loads(artifact.content)["symbol"]]  # type: ignore[return-value]


def poll(conn, ctx, feed, tmp_path, now):
    return poll_once(conn, ctx, feed, raw_root=tmp_path / "raw", cfg=CFG, now=now)


def runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM poller_runs ORDER BY run_id")]


class TestFreshFeed:
    def test_fills_and_stamps_the_feed_lag(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        oid = place(conn, pid, qty=10, created=at(9, 30))
        feed = FakeFeed({"AAA": [candle(9, 35, 100, 101, 99)]})
        out = poll(conn, ctx, feed, tmp_path, now=at(9, 55))  # candle ends 9:40 -> 15 min lag
        assert (out.status, out.fills, out.lag_s) == ("ok", 1, 900)
        t = conn.execute("SELECT * FROM trades WHERE order_id=?", (oid,)).fetchone()
        assert (t["fill_basis"], t["feed_source"], t["feed_lag_s"]) == (
            "delayed_intraday", "fake_feed", 900)

    def test_only_symbols_with_orders_or_positions_are_fetched(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        place(conn, pid, "AAA", qty=1, created=at(9, 30))
        feed = FakeFeed({"AAA": [candle(9, 35, 100, 101, 99)], "BBB": [candle(9, 35, 50, 51, 49)]})
        poll(conn, ctx, feed, tmp_path, now=at(9, 55))
        assert feed.calls == ["AAA"]

    def test_the_raw_bytes_are_persisted_before_parsing(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        place(conn, pid, qty=1, created=at(9, 30))
        poll(conn, ctx, FakeFeed({"AAA": [candle(9, 35, 100, 101, 99)]}), tmp_path, at(9, 55))
        stored = list((tmp_path / "raw" / "fake_feed" / "by-sha").rglob("*.json"))
        assert len(stored) == 1
        assert conn.execute("SELECT COUNT(*) FROM raw_artifacts WHERE source='fake_feed'"
                            ).fetchone()[0] == 1

    def test_nothing_to_do_is_an_idle_run_that_fetches_nothing(self, world, tmp_path):  # noqa: F811
        conn, ctx, _pid = world
        feed = FakeFeed({})
        out = poll(conn, ctx, feed, tmp_path, now=at(10, 0))
        assert out.status == "idle" and feed.calls == []
        assert runs(conn)[-1]["status"] == "idle"


class TestStaleFeed:
    def test_a_stale_newest_candle_parks_the_orders_and_fills_nothing(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        # touched by the candle, but the candle ended at 9:40 and it is now 11:00
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("99"), created=at(9, 30))
        feed = FakeFeed({"AAA": [candle(9, 35, 100, 101, 98)]})
        out = poll(conn, ctx, feed, tmp_path, now=at(11, 0))
        assert (out.status, out.fills, out.parked) == ("stale", 0, 1)
        o = conn.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()
        assert (o["status"], o["status_note"]) == ("pending_eod", PENDING_NOTE)
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0

    def test_a_feed_that_errors_is_stale_and_the_error_is_recorded(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        place(conn, pid, type_=OrderType.LIMIT, limit_price=D("99"), created=at(9, 30))
        feed = FakeFeed({"AAA": ProviderUnavailable("yahoo is rate limiting us")})
        out = poll(conn, ctx, feed, tmp_path, now=at(10, 0))
        assert out.status == "stale" and out.parked == 1
        assert "rate limiting" in runs(conn)[-1]["error"]

    def test_an_empty_feed_is_stale(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        place(conn, pid, type_=OrderType.LIMIT, limit_price=D("99"), created=at(9, 30))
        out = poll(conn, ctx, FakeFeed({"AAA": DataNotPublished("no candles")}), tmp_path,
                   at(10, 0))
        assert out.status == "stale"

    def test_one_dead_symbol_does_not_park_the_others(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        good = place(conn, pid, "AAA", type_=OrderType.LIMIT, limit_price=D("99"),
                     created=at(9, 30))
        bad = place(conn, pid, "BBB", type_=OrderType.LIMIT, limit_price=D("45"), created=at(9, 30))
        feed = FakeFeed({"AAA": [candle(9, 55, 100, 101, 98)],
                         "BBB": ProviderUnavailable("no ticker")})
        out = poll(conn, ctx, feed, tmp_path, now=at(10, 10))
        assert out.status == "ok" and out.fills == 1  # AAA filled; overall not "stale"
        status = {r["order_id"]: r["status"] for r in conn.execute("SELECT * FROM orders")}
        assert status[good] == "filled" and status[bad] == "pending_eod"

    def test_recovery_restores_parked_orders_on_the_next_good_poll(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        oid = place(conn, pid, type_=OrderType.LIMIT, limit_price=D("50"), created=at(9, 30))
        poll(conn, ctx, FakeFeed({"AAA": ProviderUnavailable("down")}), tmp_path, at(10, 0))
        assert conn.execute("SELECT status FROM orders").fetchone()[0] == "pending_eod"
        poll(conn, ctx, FakeFeed({"AAA": [candle(10, 5, 100, 101, 99)]}), tmp_path, at(10, 20))
        row = conn.execute("SELECT status, status_note FROM orders WHERE order_id=?",
                           (oid,)).fetchone()
        assert (row["status"], row["status_note"]) == ("open", None)

    def test_every_poll_is_recorded_so_an_outage_is_visible_afterwards(self, world, tmp_path):  # noqa: F811
        conn, ctx, pid = world
        place(conn, pid, type_=OrderType.LIMIT, limit_price=D("50"), created=at(9, 30))
        poll(conn, ctx, FakeFeed({"AAA": [candle(9, 55, 100, 101, 99)]}), tmp_path, at(10, 10))
        poll(conn, ctx, FakeFeed({"AAA": ProviderUnavailable("down")}), tmp_path, at(10, 30))
        assert [r["status"] for r in runs(conn)] == ["ok", "stale"]


class TestMarketHours:
    @pytest.mark.parametrize(("hh", "mm", "expected"), [
        (9, 14, False), (9, 15, True), (12, 0, True), (15, 30, True), (15, 31, False)])
    def test_only_between_0915_and_1530_on_a_trading_day(self, world, hh, mm, expected):  # noqa: F811
        conn, _ctx, _pid = world
        weekday = LAST  # a business day
        assert market_is_open(conn, at(hh, mm, weekday)) is expected

    def test_a_known_holiday_is_closed_even_at_noon(self, world):  # noqa: F811
        conn, _ctx, _pid = world
        conn.execute("""INSERT INTO trading_calendar (cal_date, exchange, segment, is_trading_day,
                            holiday_description, source, captured_at)
                        VALUES (?, 'NSE', ?, 0, 'Holiday', 't', '2026-01-01')""",
                     (LAST.isoformat(), SEGMENT))
        assert market_is_open(conn, at(12, 0, LAST)) is False

    def test_a_weekend_is_closed(self, world):  # noqa: F811
        conn, _ctx, _pid = world
        saturday = LAST + timedelta(days=(5 - LAST.weekday()) % 7 or 7)
        assert market_is_open(conn, at(12, 0, saturday)) is False


class TestNightlyOrdering:
    def test_a_split_is_applied_before_the_eod_fill_so_a_stop_does_not_fire_on_it(
        self, world  # noqa: F811
    ) -> None:
        """AAA falls from 100 to 20 on the ex-date purely because of a 5:1 split. An unadjusted
        stop at 90 would 'trigger' on that. Adjusting first makes it 18 -- untouched."""
        conn, ctx, pid = world
        from stk.playground.ledger import get_position  # noqa: PLC0415
        from stk.playground.passes import intraday_pass  # noqa: PLC0415
        place(conn, pid, "AAA", qty=10, created=at(9, 30, LAST - timedelta(days=5)))
        entry = candle(9, 35, 100, 101, 99, day=LAST - timedelta(days=5))
        intraday_pass(conn, ctx, {"AAA": [entry]}, feed_source="t", feed_lag_s=0,
                      adv={"AAA": D(10**9)})
        stop = place(conn, pid, "AAA", side=Side.SELL, type_=OrderType.STOP_LOSS, qty=10,
                     trigger_price=D("90"), created=at(9, 30, LAST - timedelta(days=4)))
        conn.execute("""INSERT INTO corporate_actions (symbol, exchange, ex_date, subject_raw,
                            action_type, price_factor, volume_factor, parse_status,
                            parser_version, source, source_hash, captured_at)
                        VALUES ('AAA','NSE',?,'split 5:1','SPLIT',0.2,5.0,'parsed',2,'t','h',
                                'x')""",
                     (LAST.isoformat(),))
        # today's real bar for AAA is 20 (post-split): overwrite the lake's flat 100
        import pandas as pd  # noqa: PLC0415

        from integration.lake import write_panel_by_year  # noqa: PLC0415
        days = [d.date() for d in pd.bdate_range(end=LAST, periods=15)]
        write_panel_by_year(ctx.parquet_root, days,
                            {"AAA": [100.0] * 14 + [20.0], "BBB": [50.0] * 15})
        res = run_eod(conn, ctx, LAST)
        assert res.corp.splits_applied == 1 and res.fills.fills == 0
        o = conn.execute("SELECT * FROM orders WHERE order_id=?", (stop,)).fetchone()
        assert (o["status"], D(o["trigger_price"]), o["qty"]) == ("open", D("18.00"), 50)
        assert get_position(conn, pid, "NSE", "AAA").qty == 50
        assert conn.execute("SELECT status FROM job_runs WHERE job_name='playground_eod'"
                            ).fetchone()[0] == "success"

    def test_eod_snapshots_every_active_portfolio(self, world):  # noqa: F811
        conn, ctx, pid = world
        res = run_eod(conn, ctx, LAST)
        assert res.snapshots == 1
        assert conn.execute("SELECT COUNT(*) FROM portfolio_daily WHERE portfolio_id=?",
                            (pid,)).fetchone()[0] == 1

"""The HTTP API, end to end, against a real temp database and lake."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from integration.lake import write_panel_by_year
from stk.api import auth
from stk.api.app import create_app
from stk.config.backtest import load_backtest_config as _load_cfg
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.preview import preview
from stk.strategies.repo import get_strategy, register_spec, set_status
from stk.strategies.scan import scan
from stk.strategies.tracking import track_picks


def load_backtest_config():
    """Synthetic stocks trade ~Rs 1 lakh/day, far below the real liquidity floor; these tests are
    about mechanics, not liquidity (that has its own tests in test_backtest_data), so it is off."""
    return _load_cfg().model_copy(update={"panel_min_peak_turnover_inr": Decimal(0)})


SPEC = StrategySpec.model_validate({
    "slug": "always_on", "name": "Always on", "horizon": "swing",
    "entry": {"left": {"ind": "bar_count"}, "op": ">", "right": 30},
    "exit": {"stop": {"type": "pct", "value": 0.5}, "max_hold_days": 10},
    "rank": {"by": [{"ind": "ret", "period": 20, "dir": "desc", "weight": 2.0}],
             "max_new_per_day": 2},
    "sizing": {"max_positions": 4},
})
N = 120
DAYS = [d.date() for d in pd.bdate_range("2025-01-01", periods=N)]


@pytest.fixture
def world(tmp_path):
    """A migrated db, a 3-stock lake, one live strategy with picks (some closed), one token."""
    db_path, root = tmp_path / "app.db", tmp_path / "parquet"
    root.mkdir()
    migrate(db_path)
    rng = np.random.default_rng(3)
    write_panel_by_year(root, DAYS, {
        s: [float(c) for c in 100 * np.cumprod(1 + rng.normal(0.001, 0.01, N))]
        for s in ("AAA", "BBB", "CCC")})
    conn = connect(db_path)
    for i, (sym, name) in enumerate([("AAA", "Alpha Industries Ltd"), ("BBB", "Beta Corp"),
                                     ("CCC", "Gamma Ltd")], start=1):
        conn.execute(
            """INSERT INTO securities (security_id, isin, canonical_symbol, company_name,
                   primary_exchange, status, first_seen_on, last_seen_on, updated_at)
               VALUES (?,?,?,?, 'NSE','ACTIVE','2020-01-01','2026-01-01','2026-01-01')""",
            (i, f"INE00{i}A01010", sym, name))
        conn.execute(
            """INSERT INTO listings (security_id, exchange, symbol, series, source, updated_at)
               VALUES (?, 'NSE', ?, 'EQ', 't', '2026-01-01')""", (i, sym))
    sid, _, _ = register_spec(conn, SPEC, origin="seed")
    set_status(conn, sid, "live", actor="user", reason="test")
    cfg = load_backtest_config()
    scan(conn, parquet_root=root, cfg=cfg, scan_date=DAYS[60])
    track_picks(conn, parquet_root=root, cfg=cfg)
    token = auth.create_token(conn, "test")
    conn.close()
    app = create_app(sqlite_path=db_path, parquet_root=root, cfg=cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    return client, db_path, token, app


def anon(world):
    return TestClient(world[3])


class TestAuth:
    def test_health_is_open(self, world):
        assert anon(world).get("/api/health").json() == {"status": "ok"}

    @pytest.mark.parametrize("path", ["/api/status", "/api/picks", "/api/strategies",
                                      "/api/stocks/AAA", "/api/stocks/search?q=a",
                                      "/api/briefs"])
    def test_every_data_route_needs_a_token(self, world, path):
        assert anon(world).get(path).status_code == 401

    def test_a_wrong_token_is_rejected(self, world):
        r = anon(world).get("/api/status", headers={"Authorization": "Bearer stk_nope"})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"

    def test_a_revoked_token_stops_working(self, world):
        client, db_path, _token, _ = world
        assert client.get("/api/status").status_code == 200
        conn = connect(db_path)
        assert auth.revoke_token(conn, "test")
        conn.close()
        assert client.get("/api/status").status_code == 401

    def test_only_a_hash_is_stored(self, world):
        _client, db_path, token, _ = world
        conn = connect(db_path)
        stored = conn.execute("SELECT token_sha256 FROM api_tokens").fetchone()[0]
        conn.close()
        assert token not in stored and stored == auth.hash_token(token) and len(stored) == 64

    def test_last_used_is_recorded(self, world):
        client, db_path, _t, _ = world
        client.get("/api/status")
        conn = connect(db_path)
        assert conn.execute("SELECT last_used_at FROM api_tokens").fetchone()[0] is not None
        conn.close()


class TestConfiguredToken:
    """The token from STK_AUTH__TOKEN (.env) is passed into the app and accepted on its own,
    with no api_tokens row behind it."""

    CONFIGURED = "c" * 40

    @pytest.fixture
    def app_with_configured_token(self, tmp_path):
        db, root = tmp_path / "a.db", tmp_path / "p"
        root.mkdir(); migrate(db)  # noqa: E702
        conn = connect(db); db_token = auth.create_token(conn, "t"); conn.close()  # noqa: E702
        app = create_app(sqlite_path=db, parquet_root=root, auth_token=self.CONFIGURED)
        return app, db_token

    def bearer(self, app, token):
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_it_is_accepted_without_a_database_row(self, app_with_configured_token):
        app, _ = app_with_configured_token
        assert self.bearer(app, self.CONFIGURED).get("/api/status").status_code == 200

    def test_database_tokens_still_work_beside_it(self, app_with_configured_token):
        """Configuring one in .env must not quietly invalidate the ones already minted."""
        app, db_token = app_with_configured_token
        assert self.bearer(app, db_token).get("/api/status").status_code == 200

    def test_a_near_miss_is_still_rejected(self, app_with_configured_token):
        app, _ = app_with_configured_token
        r = self.bearer(app, self.CONFIGURED[:-1] + "d").get("/api/status")
        assert r.status_code == 401

    def test_it_writes_no_token_row(self, app_with_configured_token, tmp_path):
        """It is not registered on first use: nothing to revoke, nothing to leak from app.db."""
        app, _ = app_with_configured_token
        self.bearer(app, self.CONFIGURED).get("/api/status")
        conn = connect(app.state.ctx.sqlite_path)
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 1
        conn.close()

    def test_an_app_given_no_token_does_not_pick_one_up(self, tmp_path):
        """create_app reads no environment of its own -- it accepts exactly what it was given."""
        db, root = tmp_path / "b.db", tmp_path / "q"
        root.mkdir(); migrate(db)  # noqa: E702
        app = create_app(sqlite_path=db, parquet_root=root)
        assert self.bearer(app, self.CONFIGURED).get("/api/status").status_code == 401


class TestPicks:
    def test_shape_matches_the_design_contract(self, world):
        picks = world[0].get("/api/picks").json()
        assert len(picks) == 2
        p = picks[0]
        # the design's Pick: symbol, company, exch, sector, horizon, strategy, score, ref, stop,
        # target, window, btCagr, liveReturn, hitRate, reason, conflict?
        for key in ("symbol", "company", "exch", "sector", "horizon", "strategy", "score", "ref",
                    "stop", "target", "window", "btCagr", "liveReturn", "hitRate", "reason",
                    "conflict", "approx", "signalDate", "holdDays", "strategyId", "pickReturn"):
            assert key in p, key
        assert p["company"] in ("Alpha Industries Ltd", "Beta Corp", "Gamma Ltd")
        assert p["exch"] == "NSE" and p["horizon"] == "swing" and p["strategy"] == "Always on"
        assert p["window"] == "up to 10 trading days" and p["sector"] is None

    def test_score_is_normalised_to_0_100_whatever_the_rank_weights(self, world):
        """The strategy's single rank key has weight 2.0, so its raw ceiling is 2 -- not 100."""
        scores = [p["score"] for p in world[0].get("/api/picks").json()]
        assert all(0 <= s <= 100 for s in scores) and max(scores) == pytest.approx(100.0)

    def test_defaults_to_the_latest_signal_date_and_filters(self, world):
        client = world[0]
        assert len(client.get("/api/picks?horizon=swing").json()) == 2
        assert client.get("/api/picks?horizon=momentum").json() == []
        assert client.get("/api/picks?date=2000-01-01").json() == []

    def test_a_strategy_with_no_backtest_is_marked_approximate_not_flattered(self, world):
        p = world[0].get("/api/picks").json()[0]
        assert p["approx"] is True and p["btCagr"] is None  # unknown, not zero

    def test_closed_picks_carry_their_net_return(self, world):
        p = world[0].get("/api/picks").json()[0]
        assert p["status"] == "closed" and p["pickReturn"] is not None

    def test_no_picks_at_all_is_an_empty_list(self, tmp_path):
        db, root = tmp_path / "a.db", tmp_path / "p"
        root.mkdir(); migrate(db)  # noqa: E702
        conn = connect(db); tok = auth.create_token(conn, "t"); conn.close()  # noqa: E702
        c = TestClient(create_app(sqlite_path=db, parquet_root=root),
                       headers={"Authorization": f"Bearer {tok}"})
        assert c.get("/api/picks").json() == []


class TestStrategies:
    def test_list_and_detail(self, world):
        client = world[0]
        rows = client.get("/api/strategies").json()
        assert [r["id"] for r in rows] == ["always_on"] and rows[0]["status"] == "live"
        assert rows[0]["liveClosed"] == 2 and rows[0]["hitRate"] is not None
        d = client.get("/api/strategies/always_on").json()
        assert d["rules"][0] == "bar_count > 30"
        assert d["tradeListSource"] == "live" and len(d["tradeList"]) == 2
        assert d["equityCurve"] == [] and "not yet backtested" in d["approxReasons"]

    def test_unknown_strategy_is_404(self, world):
        assert world[0].get("/api/strategies/nope").status_code == 404

    def test_approve_refuses_anything_that_has_not_passed_the_gate(self, world):
        client, db_path, _t, _ = world
        conn = connect(db_path)
        set_status(conn, get_strategy(conn, "always_on").strategy_id, "candidate",
                   actor="user", reason="test")
        conn.close()
        r = client.post("/api/strategies/always_on/approve")
        assert r.status_code == 409 and "promotion gate" in r.json()["detail"]

    def test_approve_takes_a_gate_passing_candidate_live_and_audits_it(self, world):
        client, db_path, _t, _ = world
        conn = connect(db_path)
        set_status(conn, get_strategy(conn, "always_on").strategy_id, "candidate",
                   actor="user", reason="test")
        conn.execute(
            """INSERT INTO backtest_runs (strategy_ref, kind, status, exchange, data_start,
                   data_end, started_at, gate_verdict, approx_reasons_json)
               VALUES ('always_on','walk_forward','success','NSE','2024-01-01','2024-12-31',
                       '2025-01-01','pass','[]')""")
        conn.close()
        r = client.post("/api/strategies/always_on/approve")
        assert r.status_code == 200 and r.json()["status"] == "live"
        conn = connect(db_path)
        ev = conn.execute("SELECT actor, reason FROM strategy_status_events "
                          "ORDER BY event_id DESC").fetchone()
        conn.close()
        assert (ev["actor"], ev["reason"]) == ("user", "approved in the UI")

    def test_only_a_candidate_can_be_approved(self, world):
        assert world[0].post("/api/strategies/always_on/approve").status_code == 409  # live

    def test_retiring_needs_explicit_confirmation(self, world):
        client = world[0]
        assert client.post("/api/strategies/always_on/retire",
                           json={"confirm": False, "reason": "x"}).status_code == 422
        assert get_status(world) == "live"
        r = client.post("/api/strategies/always_on/retire",
                        json={"confirm": True, "reason": "stopped working"})
        assert r.status_code == 200 and r.json()["status"] == "retired"

    def test_retire_unknown_is_404(self, world):
        assert world[0].post("/api/strategies/nope/retire",
                             json={"confirm": True, "reason": ""}).status_code == 404


def get_status(world) -> str:
    conn = connect(world[1])
    try:
        return get_strategy(conn, "always_on").status
    finally:
        conn.close()


class TestStocks:
    def test_search_by_symbol_prefix_and_company_name(self, world):
        client = world[0]
        assert [h["symbol"] for h in client.get("/api/stocks/search?q=aa").json()] == ["AAA"]
        assert [h["symbol"] for h in client.get("/api/stocks/search?q=beta").json()] == ["BBB"]
        assert client.get("/api/stocks/search?q=zzz").json() == []
        assert client.get("/api/stocks/search?q=").json() == []

    def test_exact_symbol_ranks_first(self, world):
        hits = world[0].get("/api/stocks/search?q=CCC").json()
        assert hits[0]["symbol"] == "CCC"

    def test_detail(self, world):
        d = world[0].get("/api/stocks/aaa").json()  # case-insensitive
        assert d["symbol"] == "AAA" and d["company"] == "Alpha Industries Ltd"
        assert d["tvSymbol"] == "NSE:AAA" and d["lastClose"] is not None
        assert d["changePct"] is not None and d["fundamentals"] is None
        assert d["flaggedBy"] and d["flaggedBy"][0]["strategyId"] == "always_on"

    def test_unknown_symbol_is_404(self, world):
        assert world[0].get("/api/stocks/NOPE").status_code == 404

    def test_bars_are_adjusted_series_in_date_order(self, world):
        bars = world[0].get("/api/stocks/AAA/bars").json()
        assert len(bars) == N and bars == sorted(bars, key=lambda b: b["time"])
        assert set(bars[0]) == {"time", "open", "high", "low", "close", "volume"}

    def test_bars_respect_the_requested_range(self, world):
        bars = world[0].get(f"/api/stocks/AAA/bars?from={DAYS[10]}&to={DAYS[19]}").json()
        assert len(bars) == 10 and bars[0]["time"] == DAYS[10].isoformat()


class TestStatusAndBriefs:
    def test_status_shape(self, world):
        s = world[0].get("/api/status").json()
        assert set(s) >= {"nowIst", "marketOpen", "marketLabel", "dataAsOf", "delayedFeed",
                          "staleWarning"}
        assert s["dataAsOf"] == DAYS[-1].isoformat()

    def test_old_data_raises_the_stale_banner_even_with_no_failed_job(self, world):
        """The nightly timer simply never fired: no job_runs row exists at all. A status page
        that only reads failures would say everything is fine."""
        s = world[0].get("/api/status").json()
        assert s["staleWarning"] is not None
        assert "should be through" in s["staleWarning"]["message"]
        assert s["staleWarning"]["job"] == "ingest_nse_prices"

    def test_a_failed_ingest_is_named_in_the_banner(self, world):
        client, db_path, _t, _ = world
        from stk.api.services import expected_data_date  # noqa: PLC0415
        from stk.core.time import now_ist  # noqa: PLC0415
        conn = connect(db_path)
        want = expected_data_date(conn, now_ist())
        conn.execute(
            """INSERT INTO job_runs (job_name, business_date, status, started_at, error_message,
                   code_version) VALUES ('ingest_nse_prices', ?, 'failed', '2026-09-19T20:30:00',
                   'HTTP 503 from nsearchives', 'x')""", (want.isoformat(),))
        conn.close()
        msg = client.get("/api/status").json()["staleWarning"]["message"]
        assert "HTTP 503 from nsearchives" in msg

    def test_empty_lake_is_a_warning_not_a_crash(self, tmp_path):
        db, root = tmp_path / "a.db", tmp_path / "p"
        root.mkdir(); migrate(db)  # noqa: E702
        conn = connect(db); tok = auth.create_token(conn, "t"); conn.close()  # noqa: E702
        c = TestClient(create_app(sqlite_path=db, parquet_root=root),
                       headers={"Authorization": f"Bearer {tok}"})
        s = c.get("/api/status").json()
        assert s["dataAsOf"] is None and "no price data yet" in s["staleWarning"]["message"]
        assert c.get("/api/stocks/AAA/bars").json() == []

    def test_briefs_are_honestly_pending_until_the_ai_review_exists(self, world):
        client = world[0]
        listing = client.get("/api/briefs").json()
        assert listing and all(b["pending"] for b in listing)
        b = client.get(f"/api/briefs/{listing[0]['date']}").json()
        assert b["pending"] is True and b["overview"] == "" and b["generatedAt"] is None

    def test_a_malformed_brief_date_is_422(self, world):
        assert world[0].get("/api/briefs/not-a-date").status_code == 422

    def test_every_pending_day_says_which_kind_of_pending(self, world):
        """A bare `pending` told the user nothing and offered them nothing. Never attempted,
        nothing to review and the model refused are different problems with different fixes."""
        client, db_path, _t, _ = world
        listing = client.get("/api/briefs").json()
        day = listing[0]["date"]
        assert client.get(f"/api/briefs/{day}").json()["state"] == "pending"

        conn = connect(db_path)
        conn.execute(
            "INSERT INTO ai_runs (kind, business_date, model, status, started_at, error) "
            "VALUES ('evening_review', ?, 'm', 'skipped', '2026-01-01T00:00:00+00:00', "
            "'no picks today')", (day,))
        conn.close()
        b = client.get(f"/api/briefs/{day}").json()
        assert b["state"] == "skipped" and b["stateReason"] == "no picks today"
        assert b["pending"] is True  # still not a brief, and old clients still see that

    def test_generate_queues_a_request_and_calls_no_model(self, world):
        client, db_path, _t, _ = world
        day = client.get("/api/briefs").json()[0]["date"]
        r = client.post(f"/api/briefs/{day}/generate")
        assert r.status_code == 200 and r.json()["state"] == "queued"
        conn = connect(db_path)
        rows = conn.execute("SELECT kind, status, requested_by FROM ai_requests").fetchall()
        runs = conn.execute("SELECT count(*) AS n FROM ai_runs").fetchone()["n"]
        conn.close()
        # The route's ONLY effect: a queued row. No ai_runs row, because no call was made --
        # the API cannot make one (an import-linter contract keeps stk.ai out of stk.api).
        assert [tuple(r) for r in rows] == [("evening_review", "queued", "dashboard")]
        assert runs == 0

    def test_pressing_generate_twice_queues_one_request(self, world):
        client, db_path, _t, _ = world
        day = client.get("/api/briefs").json()[0]["date"]
        assert client.post(f"/api/briefs/{day}/generate").status_code == 200
        assert client.post(f"/api/briefs/{day}/generate").status_code == 200
        conn = connect(db_path)
        n = conn.execute("SELECT count(*) AS n FROM ai_requests").fetchone()["n"]
        conn.close()
        assert n == 1

    def test_generate_rejects_a_malformed_date_before_queueing_anything(self, world):
        client, db_path, _t, _ = world
        assert client.post("/api/briefs/nope/generate").status_code == 422
        conn = connect(db_path)
        n = conn.execute("SELECT count(*) AS n FROM ai_requests").fetchone()["n"]
        conn.close()
        assert n == 0


class TestPreviews:
    def test_no_previews_is_an_empty_list_not_an_error(self, world):
        r = world[0].get("/api/previews")
        assert r.status_code == 200 and r.json() == []

    def test_a_rejected_strategys_preview_is_served_with_its_status(self, world):
        client, db_path, _t, _ = world
        conn = connect(db_path)
        sid = get_strategy(conn, "always_on").strategy_id
        set_status(conn, sid, "rejected", actor="gate", reason="failed the promotion gate")
        preview(conn, parquet_root=client.app.state.ctx.parquet_root,
                cfg=load_backtest_config(), scan_date=DAYS[61])
        conn.close()
        rows = client.get("/api/previews").json()
        assert rows
        assert {r["strategyStatus"] for r in rows} == {"rejected"}
        assert {r["strategyId"] for r in rows} == {"always_on"}
        # The company name is resolved the same way a pick's is.
        assert all(r["company"] != r["symbol"] for r in rows)

    def test_previews_can_be_filtered_to_one_strategy(self, world):
        client, db_path, _t, _ = world
        conn = connect(db_path)
        sid = get_strategy(conn, "always_on").strategy_id
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        preview(conn, parquet_root=client.app.state.ctx.parquet_root,
                cfg=load_backtest_config(), scan_date=DAYS[61])
        conn.close()
        assert client.get("/api/previews?slug=always_on").json()
        assert client.get("/api/previews?slug=nothing_here").json() == []

    def test_a_preview_never_appears_among_the_picks(self, world):
        client, db_path, _t, _ = world
        conn = connect(db_path)
        sid = get_strategy(conn, "always_on").strategy_id
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        preview(conn, parquet_root=client.app.state.ctx.parquet_root,
                cfg=load_backtest_config(), scan_date=DAYS[61])
        conn.close()
        previewed = {r["symbol"] for r in client.get("/api/previews").json()}
        picked = {p["symbol"] for p in client.get(f"/api/picks?date={DAYS[61]}").json()}
        assert previewed and not picked


class TestJobAlerts:
    def test_a_failed_nightly_step_reaches_the_status_payload(self, world):
        from stk.core.time import today_ist  # noqa: PLC0415

        client, db_path, _t, _ = world
        assert client.get("/api/status").json()["jobAlerts"] == []
        day = today_ist().isoformat()
        conn = connect(db_path)
        conn.execute(
            "INSERT INTO job_runs (job_name, business_date, status, started_at, attempt, "
            "error_message, code_version) VALUES ('nightly.scan', ?, 'failed', 'x', 1, "
            "'exit 1: boom', 'v')", (day,))
        conn.close()
        (alert,) = client.get("/api/status").json()["jobAlerts"]
        assert alert["job"] == "nightly.scan" and alert["status"] == "failed"
        assert alert["businessDate"] == day and "boom" in alert["message"]

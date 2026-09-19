"""scan -> track -> stats -> decay, on a synthetic lake."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from integration.lake import write_panel_by_year
from stk.config.backtest import load_backtest_config
from stk.config.promotion import DecayConfig, PromotionConfig
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.repo import get_strategy, register_spec, set_status
from stk.strategies.runner import lake_span
from stk.strategies.scan import scan
from stk.strategies.stats import backtest_stats, flag_decay, live_stats
from stk.strategies.tracking import round_trip_cost_pct, track_picks

# fires on every symbol with enough history, so the scan/track mechanics are what is tested
SPEC = StrategySpec.model_validate({
    "slug": "always_on", "name": "Always on", "horizon": "swing",
    "entry": {"left": {"ind": "bar_count"}, "op": ">", "right": 30},
    "exit": {"stop": {"type": "pct", "value": 0.5}, "max_hold_days": 10},
    "rank": {"by": [{"ind": "ret", "period": 20, "dir": "desc"}], "max_new_per_day": 2},
    "sizing": {"max_positions": 4},
})
N = 120


def days():
    return [d.date() for d in pd.bdate_range("2025-01-01", periods=N)]


def build_lake(root, drift=0.001):
    rng = np.random.default_rng(3)
    panel = {}
    for sym in ("AAA", "BBB", "CCC"):
        close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, N))
        panel[sym] = [float(c) for c in close]
    write_panel_by_year(root, days(), panel)


@pytest.fixture
def db(tmp_db_path):
    migrate(tmp_db_path)
    conn = connect(tmp_db_path)
    sid, _, _ = register_spec(conn, SPEC, origin="seed")
    yield conn, sid
    conn.close()


def live(conn, sid):
    set_status(conn, sid, "live", actor="user", reason="test")


class TestScan:
    def test_only_live_and_decaying_strategies_are_scanned(self, db, tmp_parquet_root):
        conn, sid = db
        build_lake(tmp_parquet_root)
        r = scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                 scan_date=days()[60])
        assert r.strategies == 0 and r.picks_created == 0  # still a candidate
        live(conn, sid)
        r = scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                 scan_date=days()[60])
        assert r.strategies == 1 and r.picks_created == 2  # max_new_per_day

    def test_rescanning_never_double_counts(self, db, tmp_parquet_root):
        conn, sid = db
        live(conn, sid)
        build_lake(tmp_parquet_root)
        kw = dict(parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                  scan_date=days()[60])
        first = scan(conn, **kw)
        second = scan(conn, **kw)
        assert (second.picks_created, second.picks_existing) == (0, first.picks_created)
        assert conn.execute("SELECT COUNT(*) AS n FROM picks").fetchone()["n"] == 2

    def test_pick_carries_display_prices_and_a_holding_window(self, db, tmp_parquet_root):
        conn, sid = db
        live(conn, sid)
        build_lake(tmp_parquet_root)
        scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(), scan_date=days()[60])
        p = conn.execute("SELECT * FROM picks ORDER BY rank_in_strategy").fetchone()
        assert p["status"] == "pending_entry" and p["horizon"] == "swing"
        assert p["stop_price"] == pytest.approx(p["ref_price"] * 0.5)
        assert p["target_price"] is None and p["hold_days"] == 10
        assert p["window_end"] > p["signal_date"]
        assert "Always on" in p["reason"]

    def test_a_date_outside_the_lake_or_with_no_bars_is_refused(self, db, tmp_parquet_root):
        conn, sid = db
        live(conn, sid)
        build_lake(tmp_parquet_root)
        with pytest.raises(ValueError, match="outside the lake"):
            scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                 scan_date=pd.Timestamp("2030-01-01").date())
        with pytest.raises(ValueError, match="no bars"):
            scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                 scan_date=pd.Timestamp("2025-01-04").date())  # a Saturday inside the range

    def test_an_empty_lake_says_what_to_run(self, db, tmp_parquet_root):
        conn, sid = db
        live(conn, sid)
        with pytest.raises(ValueError, match="stk backfill prices"):
            scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())


class TestTrack:
    def scanned(self, db, root, at=60, drift=0.001):
        conn, sid = db
        live(conn, sid)
        build_lake(root, drift)
        scan(conn, parquet_root=root, cfg=load_backtest_config(), scan_date=days()[at])
        return conn, sid

    def test_picks_are_entered_marked_and_closed_on_time(self, db, tmp_parquet_root):
        conn, _sid = self.scanned(db, tmp_parquet_root)
        r = track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        assert (r.entered, r.closed) == (2, 2)  # 60 bars of history after a 10-day hold
        outs = conn.execute("SELECT * FROM pick_outcomes").fetchall()
        assert {o["exit_reason"] for o in outs} == {"time"} and all(o["holding_days"] == 10
                                                                    for o in outs)
        marks = conn.execute("SELECT COUNT(*) AS n FROM pick_marks").fetchone()["n"]
        assert marks == 2 * 11  # one per session held, entry day included
        assert {p["status"] for p in conn.execute("SELECT status FROM picks")} == {"closed"}

    def test_a_pick_signalled_on_the_last_bar_is_still_pending_and_then_voids(
        self, db, tmp_parquet_root
    ):
        conn, _sid = self.scanned(db, tmp_parquet_root, at=N - 1)
        r = track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        assert r.entered == 0 and r.voided == 0  # signalled today: fair to wait
        assert {p["status"] for p in conn.execute("SELECT status FROM picks")} == {"pending_entry"}

    def test_a_pick_that_never_gets_a_bar_is_voided_not_left_pending_forever(
        self, db, tmp_parquet_root
    ):
        conn, _sid = self.scanned(db, tmp_parquet_root, at=60)
        conn.execute("UPDATE picks SET symbol='GHOST' || pick_id")  # e.g. delisted / renamed
        r = track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        assert r.voided == 2
        assert {o["exit_reason"] for o in conn.execute("SELECT * FROM pick_outcomes")} == {"void"}

    def test_tracking_twice_is_idempotent(self, db, tmp_parquet_root):
        conn, _ = self.scanned(db, tmp_parquet_root)
        track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        before = [tuple(r) for r in conn.execute("SELECT * FROM pick_marks ORDER BY 1,2")]
        again = track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        assert again.tracked == 0  # closed picks are not revisited
        assert before == [tuple(r) for r in conn.execute("SELECT * FROM pick_marks ORDER BY 1,2")]

    def test_returns_are_net_of_round_trip_costs(self, db, tmp_parquet_root):
        conn, _ = self.scanned(db, tmp_parquet_root)
        track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        o = conn.execute("SELECT * FROM pick_outcomes LIMIT 1").fetchone()
        gross = o["exit_price"] / o["entry_price"] - 1.0
        cost = round_trip_cost_pct("NSE", lake_span(tmp_parquet_root, "NSE").last)
        assert o["net_return"] == pytest.approx(gross - cost)
        assert 0.001 < cost < 0.01  # ~ STT both legs + stamp + DP on Rs 1 lakh: tenths of a percent

    def test_a_stop_closes_a_falling_stock(self, db, tmp_parquet_root):
        conn, sid = db
        live(conn, sid)
        # everything falls 10%/day after the scan date: the 50% stop is hit on day 7,
        # well inside the 10-day hold
        d = days()
        closes = [100.0] * 61 + [100.0 * 0.9 ** i for i in range(1, N - 60)]
        write_panel_by_year(tmp_parquet_root, d, dict.fromkeys(("AAA", "BBB", "CCC"), closes))
        scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(), scan_date=d[60])
        track_picks(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())
        reasons = {o["exit_reason"] for o in conn.execute("SELECT * FROM pick_outcomes")}
        assert "stop" in reasons


class TestStatsAndDecay:
    def add_backtest(self, conn, sid, wins: int, total: int):
        cur = conn.execute(
            """INSERT INTO backtest_runs (strategy_ref, kind, status, exchange, data_start,
                   data_end, started_at, approx_reasons_json) VALUES
                   ('always_on','walk_forward','success','NSE','2024-01-01','2024-12-31',
                    '2025-01-01', '[]')""")
        run = cur.lastrowid
        for i in range(total):
            conn.execute(
                """INSERT INTO backtest_trades (run_id, symbol, entry_date, entry_price, exit_date,
                       exit_price, qty, entry_costs, exit_costs, gross_pnl, net_pnl, return_pct,
                       exit_reason, holding_days) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run, "X", "2024-01-01", "1", "2024-01-05", "1", 1, "0", "0", "0",
                 "5" if i < wins else "-5", 0.0, "time", 4))

    def add_closed_picks(self, conn, sid, hits: int, total: int):
        vid = get_strategy(conn, "always_on").latest_version_id
        for i in range(total):
            cur = conn.execute(
                """INSERT INTO picks (strategy_id, strategy_version_id, exchange, symbol, horizon,
                       signal_date, ref_price, hold_days, window_end, score, rank_in_strategy,
                       reason, status, created_at)
                   VALUES (?,?, 'NSE', ?, 'swing', '2025-02-01', 100, 5, '2025-02-10', 1, 1, 'r',
                           'closed', '2025-02-01')""", (sid, vid, f"S{i}"))
            conn.execute(
                """INSERT INTO pick_outcomes (pick_id, exit_reason, net_return, holding_days,
                       closed_at) VALUES (?, 'time', ?, 5, '2025-02-10')""",
                (cur.lastrowid, 0.05 if i < hits else -0.05))

    def promo(self, min_picks=10, drop=15.0):
        return PromotionConfig(decay=DecayConfig(min_closed_picks=min_picks,
                                                 hit_rate_drop_pts=drop))

    def test_live_and_backtest_numbers_sit_side_by_side(self, db):
        conn, sid = db
        self.add_backtest(conn, sid, wins=8, total=10)
        self.add_closed_picks(conn, sid, hits=5, total=20)
        assert backtest_stats(conn, "always_on").win_rate == pytest.approx(0.8)
        ls = live_stats(conn, sid)
        assert (ls.closed, ls.hit_rate) == (20, 0.25) and ls.live_return == pytest.approx(-0.025)

    def test_a_strategy_whose_live_hit_rate_collapsed_is_flagged_decaying(self, db):
        conn, sid = db
        live(conn, sid)
        self.add_backtest(conn, sid, wins=8, total=10)  # 80% in backtest
        self.add_closed_picks(conn, sid, hits=5, total=20)  # 25% live
        assert flag_decay(conn, self.promo()) == ["always_on"]
        row = get_strategy(conn, "always_on")
        assert row.status == "decaying"
        assert "25%" in row.status_reason and "80%" in row.status_reason
        ev = conn.execute("SELECT actor FROM strategy_status_events ORDER BY event_id DESC"
                          ).fetchone()
        assert ev["actor"] == "system"  # the system may demote; only a person retires

    def test_too_few_closed_picks_is_not_evidence_of_decay(self, db):
        conn, sid = db
        live(conn, sid)
        self.add_backtest(conn, sid, wins=8, total=10)
        self.add_closed_picks(conn, sid, hits=0, total=5)  # 0% but only 5 picks
        assert flag_decay(conn, self.promo(min_picks=15)) == []
        assert get_strategy(conn, "always_on").status == "live"

    def test_a_small_drop_within_tolerance_is_left_alone(self, db):
        conn, sid = db
        live(conn, sid)
        self.add_backtest(conn, sid, wins=6, total=10)  # 60%
        self.add_closed_picks(conn, sid, hits=10, total=20)  # 50%: 10 pts, tolerance 15
        assert flag_decay(conn, self.promo()) == []

    def test_no_backtest_means_nothing_to_compare_against(self, db):
        conn, sid = db
        live(conn, sid)
        self.add_closed_picks(conn, sid, hits=0, total=20)
        assert flag_decay(conn, self.promo()) == []

    def test_only_live_strategies_are_considered(self, db):
        conn, sid = db  # still a candidate
        self.add_backtest(conn, sid, wins=8, total=10)
        self.add_closed_picks(conn, sid, hits=0, total=20)
        assert flag_decay(conn, self.promo()) == []

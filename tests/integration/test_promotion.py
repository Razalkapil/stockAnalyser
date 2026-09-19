"""promote(): data -> walk-forward -> gate -> stored run -> audited status change."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from integration.lake import write_index_by_year, write_panel_by_year
from stk.config.backtest import WalkForwardConfig, load_backtest_config
from stk.config.promotion import PromotionConfig, _Thresholds
from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.promotion import promote
from stk.strategies.repo import register_spec
from stk.strategies.runner import (
    approx_reasons,
    benchmark_reason,
    indicators_used,
    lake_span,
)

SPEC = StrategySpec.model_validate({
    "slug": "promo_test", "name": "Promotion test", "horizon": "swing",
    "universe": {"min_price_raw": 10},
    "entry": {"left": {"ind": "rsi", "period": 2}, "op": "<", "right": 25},
    "exit": {"stop": {"type": "atr", "mult": 2.0}, "target": {"type": "atr", "mult": 3.0},
             "max_hold_days": 12},
    "rank": {"by": [{"ind": "rsi", "period": 2, "dir": "asc"}], "max_new_per_day": 2},
    "sizing": {"max_positions": 4},
})


def build_lake(root, *, with_index: bool, years: float = 3.4) -> None:
    n = int(252 * years)
    days = [d.date() for d in pd.bdate_range("2021-01-04", periods=n)]
    rng = np.random.default_rng(13)
    panel = {}
    for sym in ("AAA", "BBB", "CCC", "DDD"):
        close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.02, n))
        panel[sym] = [float(c) for c in close]
    write_panel_by_year(root, days, panel)
    if with_index:
        write_index_by_year(root, "NIFTY_500", "Nifty 500", days,
                            [float(x) for x in np.linspace(1000, 1300, n)])


def cfg():
    return load_backtest_config().model_copy(update={
        "walk_forward": WalkForwardConfig(train_months=6, test_months=3, step_months=3),
        "adv_lookback_days": 20,
        # synthetic stocks trade ~Rs 1 lakh/day; liquidity has its own tests
        "panel_min_peak_turnover_inr": Decimal(0),
    })


@pytest.fixture
def db(tmp_db_path):
    migrate(tmp_db_path)
    conn = connect(tmp_db_path)
    register_spec(conn, SPEC, origin="seed")
    yield conn
    conn.close()


def lenient() -> PromotionConfig:
    return PromotionConfig(default=_Thresholds(min_scored_windows=2, min_pass_ratio=0.0,
                                               max_drawdown=-0.99, min_total_trades=0),
                           auto_live_origins=["seed"])


class TestPromote:
    def test_runs_walk_forward_stores_everything_and_records_the_verdict(
        self, db, tmp_parquet_root
    ):
        build_lake(tmp_parquet_root, with_index=True)
        span = lake_span(tmp_parquet_root, "NSE")
        row, report, run_id = promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(),
                                      promo=lenient(), exchange="NSE",
                                      start=span.first, end=span.last)

        windows = db.execute("SELECT * FROM backtest_windows WHERE run_id=?", (run_id,)).fetchall()
        assert len(windows) >= 3
        assert {w["result"] for w in windows} <= {"pass", "fail"}  # benchmark covered them all
        run = db.execute("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
        assert run["kind"] == "walk_forward" and run["status"] == "success"
        assert run["gate_verdict"] == report.verdict
        assert json.loads(run["gate_report_json"])["verdict"] == report.verdict
        assert run["strategy_version_id"] == row.latest_version_id

    def test_a_lenient_gate_takes_a_seed_live_and_the_event_links_to_the_run(
        self, db, tmp_parquet_root
    ):
        build_lake(tmp_parquet_root, with_index=True)
        span = lake_span(tmp_parquet_root, "NSE")
        row, report, run_id = promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(),
                                      promo=lenient(), exchange="NSE",
                                      start=span.first, end=span.last)
        assert report.verdict == "pass" and row.status == "live"
        ev = db.execute("SELECT * FROM strategy_status_events ORDER BY event_id DESC").fetchone()
        assert (ev["actor"], ev["to_status"], ev["backtest_run_id"]) == ("gate", "live", run_id)

    def test_a_real_failure_is_rejected_and_says_which_check_failed(self, db, tmp_parquet_root):
        """Enough windows and trades to judge, and it fails the drawdown limit."""
        build_lake(tmp_parquet_root, with_index=True)
        span = lake_span(tmp_parquet_root, "NSE")
        strict = PromotionConfig(default=_Thresholds(min_scored_windows=2, min_pass_ratio=0.0,
                                                     max_drawdown=-0.0000001, min_total_trades=0))
        row, report, _ = promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(),
                                 promo=strict, exchange="NSE", start=span.first, end=span.last)
        assert report.verdict == "fail" and row.status == "rejected"
        assert "max_drawdown" in row.status_reason

    def test_too_few_trades_leaves_a_candidate_not_a_rejection(self, db, tmp_parquet_root):
        build_lake(tmp_parquet_root, with_index=True)
        span = lake_span(tmp_parquet_root, "NSE")
        untestable = PromotionConfig(default=_Thresholds(
            min_scored_windows=2, min_pass_ratio=0.0, max_drawdown=-0.99, min_total_trades=10**6))
        row, report, _ = promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(),
                                 promo=untestable, exchange="NSE", start=span.first, end=span.last)
        assert report.verdict == "insufficient_evidence" and row.status == "candidate"
        assert "trades, need" in row.status_reason

    def test_without_a_benchmark_windows_are_unscored_so_the_gate_cannot_decide(
        self, db, tmp_parquet_root
    ):
        build_lake(tmp_parquet_root, with_index=False)
        span = lake_span(tmp_parquet_root, "NSE")
        row, report, run_id = promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(),
                                      promo=lenient(), exchange="NSE",
                                      start=span.first, end=span.last)
        assert report.verdict == "insufficient_evidence"
        assert row.status == "candidate"  # NOT rejected: "could not tell" is not "no"
        results = {w["result"] for w in db.execute(
            "SELECT result FROM backtest_windows WHERE run_id=?", (run_id,))}
        assert results == {"no_benchmark"}
        assert db.execute("SELECT benchmark_missing FROM backtest_runs WHERE run_id=?",
                          (run_id,)).fetchone()[0] == 1

    def test_an_unknown_strategy_is_a_clear_error(self, db, tmp_parquet_root):
        build_lake(tmp_parquet_root, with_index=True)
        with pytest.raises(KeyError, match="stk strategies seed"):
            promote(db, "nope", parquet_root=tmp_parquet_root, cfg=cfg(), promo=lenient(),
                    exchange="NSE", start=pd.Timestamp("2021-01-04").date(),
                    end=pd.Timestamp("2024-01-01").date())

    def test_an_empty_lake_says_what_to_run(self, db, tmp_parquet_root):
        with pytest.raises(ValueError, match="stk backfill prices"):
            promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(), promo=lenient(),
                    exchange="NSE", start=pd.Timestamp("2021-01-04").date(),
                    end=pd.Timestamp("2024-01-01").date())

    def test_a_span_too_short_for_one_window_is_a_clear_error(self, db, tmp_parquet_root):
        build_lake(tmp_parquet_root, with_index=True, years=1.0)
        with pytest.raises(ValueError, match="too short"):
            promote(db, "promo_test", parquet_root=tmp_parquet_root, cfg=cfg(), promo=lenient(),
                    exchange="NSE", start=pd.Timestamp("2021-01-04").date(),
                    end=pd.Timestamp("2021-06-01").date())


class TestApproximationLabels:
    def test_indicators_used_walks_the_whole_spec(self):
        assert indicators_used(SPEC) == {"rsi"}

    def test_seed_specs_report_their_data_limits(self):
        seeds = Path(__file__).parent.parent.parent / "config" / "strategies"
        delivery = StrategySpec.model_validate_json(
            (seeds / "short_volume_breakout_delivery.json").read_text())
        reasons = approx_reasons(delivery, pd.Timestamp("2015-01-01").date(),
                                 benchmark_missing=False)
        assert any("delivery_pct has no data before 2019-09-30" in r for r in reasons)
        assert approx_reasons(delivery, pd.Timestamp("2021-01-01").date(),
                              benchmark_missing=False) == []

    def test_fundamentals_strategies_are_always_labelled(self):
        path = (Path(__file__).parent.parent.parent / "config" / "strategies"
                / "longterm_quality_growth_value.json")
        spec = StrategySpec.model_validate_json(path.read_text())
        assert any("fundamentals" in r for r in approx_reasons(
            spec, pd.Timestamp("2024-01-01").date(), benchmark_missing=False))

    def test_missing_benchmark_is_a_stated_reason(self):
        reasons = approx_reasons(SPEC, pd.Timestamp("2021-01-01").date(), benchmark_missing=True,
                                 benchmark_note="some cause")
        assert any("benchmark did not cover" in r and "some cause" in r for r in reasons)

    def test_the_benchmark_reason_names_the_real_cause(self):
        """Regression: it once blamed the 2012 archive start when NO index data was ingested."""
        empty = pd.DataFrame({"date": []})
        assert "no NIFTY_500 index data has been ingested" in benchmark_reason(empty, "NIFTY_500")
        late = pd.DataFrame({"date": pd.to_datetime(["2024-03-01"])})
        assert "starts 2024-03-01" in benchmark_reason(late, "NIFTY_500")

"""Preview: the scan's read-only shadow for strategies the gate has NOT approved.

The safety property these tests exist to hold down is negative -- a preview must never reach
anything that reads `picks` -- so most of them assert about what did NOT happen.
"""

from __future__ import annotations

import pytest

from integration.test_picks_pipeline import SPEC, build_lake, days, load_backtest_config
from stk.ai.inputs import build_input
from stk.backtest.setup import make_rates_fn
from stk.config.ai import load_ai_config
from stk.playground.context import PlayCtx
from stk.store.db.engine import connect, migrate
from stk.strategies.preview import preview
from stk.strategies.repo import register_spec, set_status
from stk.strategies.scan import scan


@pytest.fixture
def db(tmp_db_path):
    migrate(tmp_db_path)
    conn = connect(tmp_db_path)
    sid, _, _ = register_spec(conn, SPEC, origin="seed")
    yield conn, sid
    conn.close()


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


class TestPreview:
    def test_a_rejected_strategy_still_shows_what_it_would_buy(self, db, tmp_parquet_root):
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "rejected", actor="gate", reason="failed the promotion gate")
        r = preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                    scan_date=days()[60])
        assert r.strategies == 1 and r.rows_created == 2  # max_new_per_day

    def test_a_preview_is_never_a_pick(self, db, tmp_parquet_root):
        """Tracking and out-of-sample stats read `picks`, so a preview that landed there would
        become a tracked recommendation by accident. The AI review may read previews, but only as
        context and with no ids -- see stk/ai/inputs.py::_previews."""
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                scan_date=days()[60])
        assert count(conn, "strategy_previews") > 0
        assert count(conn, "picks") == 0

    def test_the_ai_input_may_read_a_preview_but_never_as_a_rankable_item(
            self, db, tmp_parquet_root):
        """The narrowed invariant, pinned as code: context only, and nothing to rank."""
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        cfg = load_backtest_config()
        preview(conn, parquet_root=tmp_parquet_root, cfg=cfg, scan_date=days()[60])
        inp = build_input(conn, PlayCtx(tmp_parquet_root, cfg, make_rates_fn()), load_ai_config(),
                          days()[60])
        assert inp.pick_ids == {} and inp.preview_count > 0
        for p in inp.payload["strategy_previews"]["would_be_picks"]:
            assert not any(k.endswith("_id") or k == "id" for k in p)

    def test_a_promoted_strategy_is_not_previewed(self, db, tmp_parquet_root):
        """Exactly the complement of the scan: never both tables for the same strategy-day."""
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "live", actor="user", reason="test")
        r = preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                    scan_date=days()[60])
        assert r.strategies == 0 and r.rows_created == 0

    def test_scan_and_preview_partition_the_strategies(self, db, tmp_parquet_root):
        conn, live_sid = db
        build_lake(tmp_parquet_root)
        other = SPEC.model_copy(update={"slug": "also_on", "name": "Also on"})
        rejected_sid, _, _ = register_spec(conn, other, origin="seed")
        set_status(conn, live_sid, "live", actor="user", reason="test")
        set_status(conn, rejected_sid, "rejected", actor="gate", reason="nope")

        day = days()[60]
        s = scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(), scan_date=day)
        p = preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                    scan_date=day)
        assert (s.strategies, p.strategies) == (1, 1)
        assert {r["strategy_id"] for r in conn.execute("SELECT strategy_id FROM picks")} == \
            {live_sid}
        assert {r["strategy_id"] for r in
                conn.execute("SELECT strategy_id FROM strategy_previews")} == {rejected_sid}

    def test_the_same_signals_the_scan_would_have_produced(self, db, tmp_parquet_root):
        """Preview and scan share one evaluation, so a preview is a true dry run -- otherwise
        it would describe a strategy you do not have."""
        conn, sid = db
        build_lake(tmp_parquet_root)
        day = days()[60]
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(), scan_date=day)
        previewed = conn.execute(
            "SELECT symbol, score, ref_price, stop_price, rank_in_strategy FROM strategy_previews"
            " ORDER BY rank_in_strategy").fetchall()

        set_status(conn, sid, "live", actor="user", reason="promoted after all")
        scan(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(), scan_date=day)
        picked = conn.execute(
            "SELECT symbol, score, ref_price, stop_price, rank_in_strategy FROM picks"
            " ORDER BY rank_in_strategy").fetchall()

        assert [tuple(r) for r in previewed] == [tuple(r) for r in picked]

    def test_rerunning_never_double_counts(self, db, tmp_parquet_root):
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        kw = {"parquet_root": tmp_parquet_root, "cfg": load_backtest_config(),
              "scan_date": days()[60]}
        first = preview(conn, **kw)
        second = preview(conn, **kw)
        assert (second.rows_created, second.rows_existing) == (0, first.rows_created)
        assert count(conn, "strategy_previews") == first.rows_created

    def test_the_row_records_the_status_it_was_made_under(self, db, tmp_parquet_root):
        conn, sid = db
        build_lake(tmp_parquet_root)
        set_status(conn, sid, "rejected", actor="gate", reason="nope")
        preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                scan_date=days()[60])
        statuses = {r["status_at_preview"] for r in
                    conn.execute("SELECT status_at_preview FROM strategy_previews")}
        assert statuses == {"rejected"}

    def test_one_slug_can_be_previewed_alone(self, db, tmp_parquet_root):
        conn, _sid = db
        build_lake(tmp_parquet_root)
        other = SPEC.model_copy(update={"slug": "also_on", "name": "Also on"})
        register_spec(conn, other, origin="seed")
        r = preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config(),
                    scan_date=days()[60], slug="also_on")
        assert r.strategies == 1
        slugs = {row["slug"] for row in conn.execute(
            "SELECT st.slug FROM strategy_previews v "
            "JOIN strategies st ON st.strategy_id = v.strategy_id")}
        assert slugs == {"also_on"}

    def test_an_empty_lake_says_what_to_run(self, db, tmp_parquet_root):
        conn, _ = db
        with pytest.raises(ValueError, match="price lake is empty"):
            preview(conn, parquet_root=tmp_parquet_root, cfg=load_backtest_config())

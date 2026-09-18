"""Strategy registry: immutable versions and an audit trail for every status change."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stk.domain.dsl.model import StrategySpec
from stk.store.db.engine import connect, migrate
from stk.strategies.repo import (
    canonical_json,
    get_strategy,
    list_strategies,
    load_spec,
    register_spec,
    set_status,
)

REPO = Path(__file__).parent.parent.parent


def spec(**over) -> StrategySpec:
    d = {"slug": "reg_test", "name": "Registry test", "horizon": "swing",
         "entry": {"left": {"ind": "rsi", "period": 14}, "op": "<", "right": 30},
         "exit": {"stop": {"type": "pct", "value": 0.1}, "max_hold_days": 20}}
    d.update(over)
    return StrategySpec.model_validate(d)


@pytest.fixture
def conn(tmp_db_path):
    migrate(tmp_db_path)
    c = connect(tmp_db_path)
    yield c
    c.close()


class TestRegister:
    def test_a_new_strategy_starts_as_candidate_with_an_audit_event(self, conn):
        sid, _vid, created = register_spec(conn, spec(), origin="seed")
        assert created
        row = get_strategy(conn, "reg_test")
        assert row.status == "candidate" and row.origin == "seed"
        events = conn.execute("SELECT * FROM strategy_status_events").fetchall()
        assert len(events) == 1 and events[0]["to_status"] == "candidate"
        assert events[0]["strategy_id"] == sid

    def test_registering_identical_rules_twice_is_a_noop(self, conn):
        a = register_spec(conn, spec(), origin="seed")
        b = register_spec(conn, spec(), origin="seed")
        assert a[:2] == b[:2] and b[2] is False
        assert conn.execute("SELECT COUNT(*) AS n FROM strategy_versions").fetchone()["n"] == 1

    def test_changing_a_rule_makes_a_new_version_and_keeps_the_old_one(self, conn):
        _, v1, _ = register_spec(conn, spec(), origin="seed")
        changed = spec(exit={"stop": {"type": "pct", "value": 0.2}, "max_hold_days": 20})
        _, v2, created = register_spec(conn, changed, origin="seed")
        assert created and v2 != v1
        assert load_spec(conn, v1).exit.stop.value == 0.1  # the old version is untouched
        assert load_spec(conn, v2).exit.stop.value == 0.2
        assert get_strategy(conn, "reg_test").latest_version_id == v2

    def test_canonical_json_is_stable_regardless_of_key_order(self):
        a = spec()
        b = StrategySpec.model_validate(json.loads(json.dumps(
            {"exit": {"max_hold_days": 20, "stop": {"value": 0.1, "type": "pct"}},
             "entry": {"op": "<", "right": 30, "left": {"period": 14, "ind": "rsi"}},
             "horizon": "swing", "name": "Registry test", "slug": "reg_test"})))
        assert canonical_json(a) == canonical_json(b)

    def test_every_seed_file_registers(self, conn):
        for path in sorted((REPO / "config" / "strategies").glob("*.json")):
            register_spec(conn, StrategySpec.model_validate_json(path.read_text()), origin="seed")
        assert len(list_strategies(conn)) == 10


class TestStatus:
    def test_a_change_is_recorded_with_actor_and_reason(self, conn):
        sid, _, _ = register_spec(conn, spec(), origin="seed")
        assert set_status(conn, sid, "live", actor="gate", reason="passed", backtest_run_id=None)
        ev = conn.execute("SELECT * FROM strategy_status_events ORDER BY event_id").fetchall()[-1]
        assert (ev["from_status"], ev["to_status"], ev["actor"]) == ("candidate", "live", "gate")

    def test_setting_the_same_status_changes_nothing_and_logs_nothing(self, conn):
        sid, _, _ = register_spec(conn, spec(), origin="seed")
        before = conn.execute("SELECT COUNT(*) AS n FROM strategy_status_events").fetchone()["n"]
        assert set_status(conn, sid, "candidate", actor="system", reason="x") is False
        after = conn.execute("SELECT COUNT(*) AS n FROM strategy_status_events").fetchone()["n"]
        assert before == after

    def test_unknown_status_is_rejected(self, conn):
        sid, _, _ = register_spec(conn, spec(), origin="seed")
        with pytest.raises(ValueError):
            set_status(conn, sid, "totally_live", actor="user", reason="x")

    def test_unknown_strategy_is_an_error(self, conn):
        with pytest.raises(KeyError):
            set_status(conn, 999, "live", actor="user", reason="x")

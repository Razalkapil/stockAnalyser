"""The committed JSON Schema is what the AI strategy lab will be handed, so it must
never quietly fall behind the pydantic models it describes."""

from __future__ import annotations

import json
from pathlib import Path

from stk.domain.dsl.model import StrategySpec

COMMITTED = Path(__file__).parent.parent.parent / "config" / "strategy.schema.json"


def test_committed_schema_matches_the_models():
    assert json.loads(COMMITTED.read_text()) == StrategySpec.model_json_schema(), (
        "config/strategy.schema.json is stale -- regenerate it with "
        "`uv run stk strategies schema --out config/strategy.schema.json`"
    )


def test_schema_forbids_unknown_keys_at_the_top_level():
    assert json.loads(COMMITTED.read_text())["additionalProperties"] is False

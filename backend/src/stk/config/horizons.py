"""Typed loader for config/horizons.yaml -> the DSL validator's HorizonWindow map."""

from __future__ import annotations

from pathlib import Path

from stk.config.loader import load_named_yaml
from stk.domain.dsl.validate import HorizonWindow


def load_horizons(config_dir: Path | None = None) -> dict[str, HorizonWindow]:
    raw = load_named_yaml("horizons", config_dir=config_dir)["horizons"]
    return {
        name: HorizonWindow(int(v["hold_days_min"]), int(v["hold_days_max"]))
        for name, v in raw.items()
    }

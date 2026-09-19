"""Typed loader for config/playground.yaml."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml


class PollerConfig(BaseModel):
    interval: str = "5m"
    poll_every_s: int = 180
    stale_after_s: int = 1500

    @property
    def interval_minutes(self) -> int:
        return int(self.interval.rstrip("m"))


class PlaygroundConfig(BaseModel):
    poller: PollerConfig = Field(default_factory=PollerConfig)


def load_playground_config(config_dir: Path | None = None) -> PlaygroundConfig:
    return PlaygroundConfig(**load_named_yaml("playground", config_dir=config_dir))

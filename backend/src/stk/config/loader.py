"""YAML config loading and layering.

Precedence, highest wins:
  1. Process env / .env               (secrets, paths, tokens only)
  2. config/env/{APP_ENV}.yaml         (per-environment overlay)
  3. config/defaults.yaml              (base config for everything)

Rule: anything a non-programmer would tune lives in committed YAML.
Anything secret lives in .env and is never committed. Cost rates,
liquidity thresholds and horizon windows are configuration data, not
secrets -- they belong in YAML precisely so a rate change is a config
diff, not a code change.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from stk.core.errors import ConfigError


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base``. ``overlay`` wins on conflicts."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def find_config_dir(start: Path | None = None) -> Path:
    """Locate the repo's top-level config/ directory by walking upward.

    Works regardless of the current working directory the CLI is
    invoked from, which matters once this ships as an installed console
    script rather than being run from the repo root.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        config_dir = candidate / "config"
        if (config_dir / "defaults.yaml").is_file():
            return config_dir
    raise ConfigError(
        f"could not locate config/defaults.yaml walking up from {current}; "
        "run from within the stockAnalyser repo or set STK_CONFIG_DIR"
    )


def load_yaml_config(env: str | None = None, config_dir: Path | None = None) -> dict[str, Any]:
    """Load and merge defaults.yaml + env/{env}.yaml.

    ``env`` defaults to the STK_APP__ENV env var, then "local".
    """
    resolved_env = env or os.environ.get("STK_APP__ENV", "local")

    if config_dir is None:
        env_override = os.environ.get("STK_CONFIG_DIR")
        config_dir = Path(env_override) if env_override else find_config_dir()

    defaults_path = config_dir / "defaults.yaml"
    if not defaults_path.is_file():
        raise ConfigError(f"missing required config file: {defaults_path}")

    with defaults_path.open() as f:
        merged = yaml.safe_load(f) or {}

    env_path = config_dir / "env" / f"{resolved_env}.yaml"
    if env_path.is_file():
        with env_path.open() as f:
            overlay = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, overlay)

    return merged


def load_named_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load a single named config file from config/ (e.g. 'costs', 'universe', 'horizons')."""
    resolved_dir = config_dir or find_config_dir()
    path = resolved_dir / f"{name}.yaml"
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    with path.open() as f:
        return yaml.safe_load(f) or {}

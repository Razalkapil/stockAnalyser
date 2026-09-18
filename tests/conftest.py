"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _isolated_config_dir(monkeypatch):
    """Point STK_CONFIG_DIR at the real repo config/ for every test.

    Tests run from any cwd should still find config/defaults.yaml etc.
    """
    monkeypatch.setenv("STK_CONFIG_DIR", str(REPO_ROOT / "config"))
    monkeypatch.setenv("STK_APP__ENV", "local")


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "app.db"


@pytest.fixture
def tmp_parquet_root(tmp_path: Path) -> Path:
    root = tmp_path / "parquet"
    root.mkdir()
    return root

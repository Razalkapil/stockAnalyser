"""The worker's stale-code detector. It exists because a worker once ran a fix two days late."""

from __future__ import annotations

import os
import time
from pathlib import Path

import stk
from stk.core import version
from stk.core.version import source_fingerprint


def test_it_is_a_positive_number_for_the_real_package():
    assert source_fingerprint() > 0


def test_it_is_not_memoised_and_notices_a_touched_source_file(tmp_path, monkeypatch):
    """The whole point: unlike code_version() it must change inside a running process."""
    pkg = tmp_path / "stk" / "core"
    pkg.mkdir(parents=True)
    fake = pkg / "version.py"
    fake.write_text("x = 1\n")
    monkeypatch.setattr(version, "__file__", str(fake))

    before = source_fingerprint()
    later = time.time() + 5
    os.utime(fake, (later, later))
    assert source_fingerprint() > before


def test_a_new_file_in_the_package_counts(tmp_path, monkeypatch):
    pkg = tmp_path / "stk" / "core"
    pkg.mkdir(parents=True)
    fake = pkg / "version.py"
    fake.write_text("x = 1\n")
    monkeypatch.setattr(version, "__file__", str(fake))
    before = source_fingerprint()

    added = tmp_path / "stk" / "ai" / "new_module.py"
    added.parent.mkdir()
    added.write_text("y = 2\n")
    later = time.time() + 5
    os.utime(added, (later, later))
    assert source_fingerprint() > before


def test_it_never_raises_on_a_missing_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(version, "__file__", str(tmp_path / "gone" / "a" / "version.py"))
    assert source_fingerprint() == 0


def test_it_watches_the_installed_package():
    assert Path(stk.__file__).parent == Path(version.__file__).resolve().parent.parent

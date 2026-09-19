"""Backups: consistent, verified, rotated safely, and restorable without deleting anything."""

from __future__ import annotations

import json
import sqlite3
import tarfile
from datetime import UTC, date, datetime, timedelta

import pytest

import stk.store.backup as backup_mod
from stk.store.backup import (
    MANIFEST,
    PARQUET_ARCHIVE,
    RAW_ARCHIVE,
    SQLITE_NAME,
    BackupError,
    latest_backup_age_days,
    list_backups,
    restore_backup,
    rotate,
    run_backup,
    sha256_of,
    verify_backup,
)
from stk.store.db.engine import connect, migrate


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC)


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    (root / "parquet" / "bars_daily" / "exchange=NSE" / "year=2026").mkdir(parents=True)
    (root / "parquet" / "bars_daily" / "exchange=NSE" / "year=2026" / "data.parquet").write_bytes(
        b"PAR1-fake-but-recorded")
    (root / "parquet" / "half.parquet.tmp").write_bytes(b"interrupted write")
    (root / "raw" / "nse").mkdir(parents=True)
    (root / "raw" / "nse" / "a.csv").write_text("SYMBOL\nX\n")
    db = root / "app.db"
    migrate(db)
    conn = connect(db)
    conn.execute("INSERT INTO portfolios (name, start_capital, created_at) "
                 "VALUES ('Main', '1000000', '2026-01-01')")
    conn.close()
    return root, tmp_path / "backups"


def backup(data, day: date, **kw):
    root, dest = data
    return run_backup(sqlite_path=root / "app.db", parquet_root=root / "parquet", dest=dest,
                      raw_root=root / "raw", now=at(day), **kw)


class TestRun:
    def test_writes_a_verified_backup_with_a_manifest(self, data):
        r = backup(data, date(2026, 9, 19))
        assert r.path.name == "2026-09-19"
        assert {SQLITE_NAME, PARQUET_ARCHIVE, MANIFEST} <= {p.name for p in r.path.iterdir()}
        assert verify_backup(r.path) == []
        m = json.loads((r.path / MANIFEST).read_text())
        assert set(m["files"]) == {SQLITE_NAME, PARQUET_ARCHIVE} and m["created_at"]

    def test_the_snapshot_contains_the_data_including_uncheckpointed_wal_writes(self, data):
        """Copying app.db while the API is writing can miss WAL content or copy a torn page."""
        root, _ = data
        live = connect(root / "app.db")  # WAL mode, held open with a write not yet checkpointed
        live.execute("INSERT INTO portfolios (name, start_capital, created_at) "
                     "VALUES ('Fresh', '5', '2026-09-19')")
        r = backup(data, date(2026, 9, 19))
        snap = sqlite3.connect(r.path / SQLITE_NAME)
        names = {row[0] for row in snap.execute("SELECT name FROM portfolios")}
        snap.close()
        live.close()
        assert names == {"Main", "Fresh"}

    def test_interrupted_temp_files_are_not_archived(self, data):
        r = backup(data, date(2026, 9, 19))
        with tarfile.open(r.path / PARQUET_ARCHIVE) as tar:
            assert not any(n.endswith(".tmp") for n in tar.getnames())
            assert any(n.endswith("data.parquet") for n in tar.getnames())

    def test_raw_bytes_are_only_included_when_asked(self, data):
        assert RAW_ARCHIVE not in {p.name for p in backup(data, date(2026, 9, 19)).path.iterdir()}
        r = backup(data, date(2026, 9, 20), include_raw=True)
        assert RAW_ARCHIVE in {p.name for p in r.path.iterdir()}

    def test_a_second_run_the_same_day_replaces_the_first_atomically(self, data):
        backup(data, date(2026, 9, 19))
        r = backup(data, date(2026, 9, 19))
        assert [p.name for p in list_backups(data[1])] == ["2026-09-19"]
        assert verify_backup(r.path) == []
        assert not [p for p in data[1].iterdir() if p.name.startswith(".")]  # no leftovers

    def test_a_missing_database_is_an_error_not_an_empty_backup(self, data):
        root, dest = data
        with pytest.raises(BackupError, match="nothing to back up"):
            run_backup(sqlite_path=root / "nope.db", parquet_root=root / "parquet", dest=dest)

    @pytest.mark.parametrize("inside", ["data", "data/parquet", "data/sub/dir"])
    def test_a_destination_inside_the_data_is_refused(self, data, inside):
        root, _ = data
        with pytest.raises(BackupError, match="inside"):
            run_backup(sqlite_path=root / "app.db", parquet_root=root / "parquet",
                       dest=root.parent / inside)

    def test_a_failed_backup_leaves_no_half_written_directory(self, data, monkeypatch):
        def broken(*_a):
            raise OSError("disk")

        monkeypatch.setattr(backup_mod, "_tar_directory", broken)
        with pytest.raises(OSError):
            backup(data, date(2026, 9, 19))
        assert list_backups(data[1]) == []
        assert not list(data[1].glob(".*partial")) if data[1].exists() else True


class TestVerify:
    def test_detects_a_changed_file(self, data):
        r = backup(data, date(2026, 9, 19))
        with (r.path / PARQUET_ARCHIVE).open("r+b") as f:
            f.seek(5)
            f.write(b"\xff\xff")
        assert any("checksum mismatch" in p or "size" in p for p in verify_backup(r.path))

    def test_detects_a_missing_file(self, data):
        r = backup(data, date(2026, 9, 19))
        (r.path / PARQUET_ARCHIVE).unlink()
        assert verify_backup(r.path) == [f"{PARQUET_ARCHIVE}: missing"]

    def test_detects_a_corrupt_database_even_with_a_matching_checksum(self, data):
        """The checksum only proves the file is what was WRITTEN; integrity_check proves that
        what was written is a working database."""
        r = backup(data, date(2026, 9, 19))
        (r.path / SQLITE_NAME).write_bytes(b"this is not a sqlite database at all" * 100)
        m = json.loads((r.path / MANIFEST).read_text())
        m["files"][SQLITE_NAME] = {"bytes": (r.path / SQLITE_NAME).stat().st_size,
                                   "sha256": sha256_of(r.path / SQLITE_NAME)}
        (r.path / MANIFEST).write_text(json.dumps(m))
        assert any("not a readable database" in p for p in verify_backup(r.path))

    def test_no_manifest_is_unverifiable(self, data):
        r = backup(data, date(2026, 9, 19))
        (r.path / MANIFEST).unlink()
        assert "no MANIFEST.json" in verify_backup(r.path)[0]


class TestRotation:
    def make(self, tmp_path, days):
        dest = tmp_path / "b"
        for d in days:
            (dest / d.isoformat()).mkdir(parents=True)
            (dest / d.isoformat() / MANIFEST).write_text("{}")
        return dest

    def test_keeps_the_newest_daily_and_the_newest_sundays_beyond_them(self, tmp_path):
        start = date(2026, 8, 1)  # a Saturday
        days = [start + timedelta(days=i) for i in range(45)]
        dest = self.make(tmp_path, days)
        rotate(dest, keep_daily=7, keep_weekly=3)
        kept = sorted(p.name for p in list_backups(dest))
        newest7 = [d.isoformat() for d in sorted(days)[-7:]]
        older_sundays = [d for d in sorted(days)[:-7] if d.weekday() == 6][-3:]
        assert kept == sorted(newest7 + [d.isoformat() for d in older_sundays])

    def test_never_deletes_things_it_did_not_make(self, tmp_path):
        dest = self.make(tmp_path, [date(2026, 1, i) for i in range(1, 12)])
        (dest / "holiday-photos").mkdir()  # not date-named
        (dest / "2020-01-01").mkdir()  # date-named but NO manifest: not ours
        (dest / "notes.txt").write_text("mine")
        rotate(dest, keep_daily=2, keep_weekly=0)
        assert (dest / "holiday-photos").exists() and (dest / "2020-01-01").exists()
        assert (dest / "notes.txt").read_text() == "mine"

    def test_rotation_reports_what_it_removed(self, tmp_path):
        dest = self.make(tmp_path, [date(2026, 1, i) for i in range(1, 5)])
        assert sorted(rotate(dest, keep_daily=2, keep_weekly=0)) == ["2026-01-01", "2026-01-02"]

    def test_run_backup_rotates(self, data):
        for i in range(1, 6):
            backup(data, date(2026, 9, i), keep_daily=2, keep_weekly=0)
        assert [p.name for p in list_backups(data[1])] == ["2026-09-05", "2026-09-04"]


class TestAge:
    def test_age_in_days(self, data):
        backup(data, date(2026, 9, 15))
        assert latest_backup_age_days(data[1], today=date(2026, 9, 19)) == 4

    def test_no_backup_is_none_not_zero(self, tmp_path):
        assert latest_backup_age_days(tmp_path / "none", today=date(2026, 9, 19)) is None


class TestRestore:
    def test_round_trip_into_a_fresh_location(self, data, tmp_path):
        r = backup(data, date(2026, 9, 19))
        fresh = tmp_path / "restored"
        done = restore_backup(r.path, data_root=fresh)
        assert "restored app.db" in done and "restored parquet/" in done
        conn = sqlite3.connect(fresh / "app.db")
        assert conn.execute("SELECT name FROM portfolios").fetchone()[0] == "Main"
        conn.close()
        assert (fresh / "parquet" / "bars_daily" / "exchange=NSE" / "year=2026"
                / "data.parquet").read_bytes() == b"PAR1-fake-but-recorded"

    def test_refuses_to_overwrite_existing_data_by_default(self, data):
        root, _ = data
        r = backup(data, date(2026, 9, 19))
        with pytest.raises(BackupError, match="already holds data"):
            restore_backup(r.path, data_root=root)

    def test_force_moves_aside_and_deletes_nothing(self, data):
        root, _ = data
        r = backup(data, date(2026, 9, 19))
        live = connect(root / "app.db")
        live.execute("INSERT INTO portfolios (name, start_capital, created_at) "
                     "VALUES ('Newer', '9', '2026-09-20')")
        live.close()
        restore_backup(r.path, data_root=root, force=True, now=at(date(2026, 9, 20)))
        aside = [p.name for p in root.iterdir() if "pre-restore" in p.name]
        assert any(n.startswith("app.db.pre-restore-") for n in aside)
        assert any(n.startswith("parquet.pre-restore-") for n in aside)
        old = sqlite3.connect(next(root.glob("app.db.pre-restore-*")))
        assert "Newer" in {row[0] for row in old.execute("SELECT name FROM portfolios")}
        old.close()
        restored = sqlite3.connect(root / "app.db")
        assert "Newer" not in {row[0] for row in restored.execute("SELECT name FROM portfolios")}
        restored.close()

    def test_refuses_a_bad_backup(self, data, tmp_path):
        r = backup(data, date(2026, 9, 19))
        (r.path / PARQUET_ARCHIVE).unlink()
        with pytest.raises(BackupError, match="unverified"):
            restore_backup(r.path, data_root=tmp_path / "x")
        assert not (tmp_path / "x" / "app.db").exists()  # nothing was half-restored




class TestCli:
    """`stk backup ...` end to end, pointed at a temp data root through the env override."""

    @pytest.fixture
    def cli(self, data, monkeypatch):
        from typer.testing import CliRunner  # noqa: PLC0415

        from stk.cli.main import app  # noqa: PLC0415
        from stk.config.settings import get_settings  # noqa: PLC0415

        root, dest = data
        monkeypatch.setenv("STK_PATHS__DATA_ROOT", str(root))
        get_settings(force_reload=True)
        yield lambda *args: CliRunner().invoke(app, ["backup", *args]), root, dest
        monkeypatch.undo()
        get_settings(force_reload=True)

    def test_run_verify_list_restore(self, cli):
        invoke, root, dest = cli
        r = invoke("run", "--dest", str(dest))
        assert r.exit_code == 0 and "OK:" in r.output, r.output
        (made,) = list(dest.iterdir())
        assert invoke("list", "--dest", str(dest)).output.strip() == made.name
        assert invoke("verify", str(made)).exit_code == 0

        # restore refuses without --yes, and refuses to clobber without --force
        assert invoke("restore", str(made)).exit_code == 1
        assert invoke("restore", str(made), "--yes").exit_code == 1
        ok = invoke("restore", str(made), "--yes", "--force")
        assert ok.exit_code == 0, ok.output
        assert list(root.glob("app.db.pre-restore-*"))  # nothing deleted, moved aside

    def test_a_destination_inside_data_is_refused_with_a_nonzero_exit(self, cli):
        invoke, root, _dest = cli
        r = invoke("run", "--dest", str(root / "backups"))
        assert r.exit_code == 1 and "BACKUP FAILED" in r.output

    def test_verify_fails_loudly_on_a_corrupt_backup(self, cli):
        invoke, _root, dest = cli
        invoke("run", "--dest", str(dest))
        (made,) = list(dest.iterdir())
        (made / PARQUET_ARCHIVE).write_bytes(b"garbage")
        r = invoke("verify", str(made))
        assert r.exit_code == 1 and "PROBLEM" in r.output

"""The deploy artifacts, checked against the code they invoke.

Nothing here runs systemd or Caddy (there is no VM in CI). What it does catch is the failure that
otherwise shows up at 20:30 on the first weeknight: a unit that calls a command that was renamed,
a timer pointing at a service that does not exist, an API bound to the wrong port for the proxy.
"""

from __future__ import annotations

import configparser
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stk.cli.main import app

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SYSTEMD = DEPLOY / "systemd"
UNITS = sorted(SYSTEMD.glob("*.service")) + sorted(SYSTEMD.glob("*.timer"))
APP_DIR = "/srv/stockanalyser/app"


def parse(path: Path) -> configparser.ConfigParser:
    # strict=False: a timer legitimately repeats OnCalendar=
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # type: ignore[assignment, method-assign]
    cp.read(path)
    return cp


def values(path: Path, section: str, key: str) -> list[str]:
    """Every value of a possibly repeated key (configparser keeps only the last)."""
    out, current = [], None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("["):
            current = line.strip("[]")
        elif current == section and line.startswith(f"{key}="):
            out.append(line.split("=", 1)[1])
    return out


def services() -> list[Path]:
    return [u for u in UNITS if u.suffix == ".service"]


def timers() -> list[Path]:
    return [u for u in UNITS if u.suffix == ".timer"]


def test_units_exist():
    names = {u.name for u in UNITS}
    assert {"stk-api.service", "stk-poller.service", "stk-nightly.service", "stk-nightly.timer",
            "stk-weekly.timer", "stk-backup.timer", "stk-doctor.timer"} <= names


@pytest.mark.parametrize("unit", services(), ids=lambda p: p.name)
class TestServices:
    def test_reads_the_shared_env_file_and_runs_unprivileged(self, unit):
        (env,) = values(unit, "Service", "EnvironmentFile")
        assert env == "/etc/stockanalyser/env"
        assert values(unit, "Service", "User") == ["stk"]
        assert values(unit, "Service", "NoNewPrivileges") == ["true"]

    def test_execstart_is_a_real_stk_command(self, unit):
        (line,) = values(unit, "Service", "ExecStart")
        argv = shlex.split(line)
        exe = argv[0]
        assert exe.startswith(f"{APP_DIR}/")
        if exe.endswith(".sh"):
            assert (DEPLOY / Path(exe).name).exists(), exe
            return
        assert exe == f"{APP_DIR}/.venv/bin/stk"
        # --help stops before running anything, but an unknown command/option still errors first
        result = CliRunner().invoke(app, [*argv[1:], "--help"])
        assert result.exit_code == 0, f"{line}\n{result.output}"

    def test_may_only_write_under_the_data_tree(self, unit):
        assert values(unit, "Service", "ProtectSystem") == ["strict"]
        assert values(unit, "Service", "ReadWritePaths") == ["/srv/stockanalyser"]


def test_scheduled_jobs_are_oneshot_and_long_running_ones_restart():
    for name in ("nightly", "weekly", "backup", "doctor"):
        assert values(DEPLOY / "systemd" / f"stk-{name}.service", "Service", "Type") == ["oneshot"]
    for name in ("api", "poller"):
        assert values(DEPLOY / "systemd" / f"stk-{name}.service", "Service", "Restart")


def test_api_binds_localhost_on_the_port_the_proxy_targets():
    (line,) = values(DEPLOY / "systemd" / "stk-api.service", "Service", "ExecStart")
    argv = shlex.split(line)
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    port = argv[argv.index("--port") + 1]
    assert f"reverse_proxy 127.0.0.1:{port}" in (DEPLOY / "Caddyfile").read_text()


@pytest.mark.parametrize("timer", timers(), ids=lambda p: p.name)
class TestTimers:
    def test_has_a_matching_service(self, timer):
        assert timer.with_suffix(".service") in services()

    def test_is_installable_persistent_and_in_kolkata_time(self, timer):
        assert values(timer, "Install", "WantedBy") == ["timers.target"]
        assert values(timer, "Timer", "Persistent") == ["true"]
        calendars = values(timer, "Timer", "OnCalendar")
        assert calendars and all(c.endswith("Asia/Kolkata") for c in calendars)

    @pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="needs systemd-analyze")
    def test_calendar_expression_is_valid(self, timer):
        for c in values(timer, "Timer", "OnCalendar"):
            r = subprocess.run(
                ["systemd-analyze", "calendar", c], capture_output=True, text=True, check=False
            )
            assert r.returncode == 0, f"{c}: {r.stderr}"


def test_nightly_runs_after_the_close_and_backup_after_nightly():
    def first_hhmm(name: str) -> str:
        cal = values(DEPLOY / "systemd" / f"stk-{name}.timer", "Timer", "OnCalendar")[0]
        return re.search(r"(\d\d:\d\d)", cal).group(1)  # type: ignore[union-attr]

    assert first_hhmm("nightly") >= "18:30"  # exchanges publish bhavcopy by ~18:30 IST
    assert first_hhmm("backup") > first_hhmm("nightly")
    assert first_hhmm("doctor") < "09:15"  # a problem is reported before the market opens


def test_every_unit_is_enabled_by_the_installer():
    install = (DEPLOY / "install.sh").read_text()
    for unit in ("stk-api.service", "stk-poller.service", "stk-nightly.timer", "stk-weekly.timer",
                 "stk-backup.timer", "stk-doctor.timer"):
        assert unit in install


class TestCaddyfile:
    text = (DEPLOY / "Caddyfile").read_text()

    def test_serves_the_built_app_with_spa_fallback(self):
        assert "try_files {path} /index.html" in self.text
        assert "web/dist" in self.text

    def test_csp_allows_tradingview_and_nothing_broad(self):
        csp = re.search(r'Content-Security-Policy "([^"]+)"', self.text).group(1)  # type: ignore[union-attr]
        assert "https://s3.tradingview.com" in csp and "frame-src https://*.tradingview.com" in csp
        assert "'unsafe-eval'" not in csp and "script-src 'self' https" in csp
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp

    def test_the_csp_matches_what_the_web_app_actually_loads(self):
        widget = (DEPLOY.parent / "web/src/components/TradingViewWidget.tsx").read_text()
        origin = re.search(r'"(https://[^/"]+)/', widget).group(1)  # type: ignore[union-attr]
        assert origin in self.text


class TestScripts:
    @pytest.mark.parametrize("name", ["backup.sh", "restore.sh", "install.sh"])
    def test_are_strict_executable_and_parse(self, name):
        path = DEPLOY / name
        assert path.stat().st_mode & 0o111, f"{name} is not executable"
        assert "set -euo pipefail" in path.read_text()
        assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0

    def test_backup_script_calls_real_commands_and_keeps_backups_out_of_data(self):
        text = (DEPLOY / "backup.sh").read_text()
        assert "backup run --dest" in text
        env = (DEPLOY / "env.example").read_text()
        (dest,) = re.findall(r"^STK_BACKUP_DEST=(.+)$", env, re.M)
        assert not dest.startswith("/srv/stockanalyser/data")

    def test_restore_verifies_before_it_stops_anything(self):
        text = (DEPLOY / "restore.sh").read_text()
        assert text.index("backup verify") < text.index("systemctl stop")
        assert "--force" in text and "rm " not in text  # nothing is deleted

    def test_env_example_selects_prod_and_holds_no_secret(self):
        env = (DEPLOY / "env.example").read_text()
        assert "STK_APP__ENV=prod" in env
        assert re.search(r"^ANTHROPIC_API_KEY=$", env, re.M)  # empty: no key committed

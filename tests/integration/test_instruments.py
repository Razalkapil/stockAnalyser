"""Funds (ETFs) must not be scanned or backtested as stocks -- found in the first live scan."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from integration.lake import write_panel_by_year
from stk.cli.main import app
from stk.config.backtest import load_backtest_config as _load_cfg
from stk.core.errors import DataNotPublished
from stk.domain.dsl.model import StrategySpec
from stk.ingest.health import check_instrument_classes
from stk.ingest.instruments import (
    classes_known,
    classify_isin,
    fund_symbols,
    ingest_instrument_classes,
    require_instrument_classes,
)
from stk.providers.base import RawArtifact
from stk.providers.nse.udiff import NseUdiffProvider
from stk.store.db.engine import connect, migrate
from stk.strategies.repo import register_spec, set_status
from stk.strategies.scan import scan

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "nse" / "udiff_20260917.csv").read_text()
DAY = date(2026, 9, 17)


def _row(symbol: str, isin: str) -> str:
    return (f"2026-09-17,2026-09-17,CM,NSE,STK,999,{isin},{symbol},EQ,,,,,{symbol} FUND,"
            "50.0,51.0,49.0,50.5,50.5,50.0,,50.5,,,1000,50000.0,10,F1,1,,,,,")


def csv_with_funds() -> str:
    return FIXTURE.rstrip("\n") + "\n" + _row("GOLDBEES", "INF204KB17I5") + "\n" + _row(
        "ODDBOND", "IN0020230012") + "\n"


class FakeUdiff(NseUdiffProvider):
    """The real parser over fixture bytes; only the network fetch is replaced."""

    def __init__(self, text: str | None = None, missing: bool = False) -> None:
        self.text, self.missing = text, missing

    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        if self.missing:
            raise DataNotPublished("nothing published")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("bhav.csv", self.text or csv_with_funds())
        return RawArtifact(source="nse_udiff", business_date=business_date, url="u",
                           content=buf.getvalue(), content_type="application/zip",
                           http_status=200, fetched_at=datetime.now(UTC))


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "app.db"
    migrate(db)
    fake = FakeUdiff()
    monkeypatch.setattr("stk.providers.registry.get_price_provider", lambda name: fake)
    return db, tmp_path / "raw", fake


def rows(db):
    conn = connect(db)
    out = {r["symbol"]: dict(r) for r in conn.execute("SELECT * FROM instrument_class")}
    conn.close()
    return out


class TestClassify:
    @pytest.mark.parametrize(("isin", "expected"), [
        ("INF204KB17I5", "fund"), ("INE002A01018", "equity"), ("IN0020230012", "other"),
        (None, None), ("", None)])
    def test_by_isin_prefix(self, isin, expected):
        assert classify_isin(isin) == expected


class TestIngest:
    def test_funds_and_equities_are_told_apart(self, env):
        db, raw, _ = env
        n = ingest_instrument_classes(DAY, sqlite_path=db, raw_root=raw)
        got = rows(db)
        assert n == len(got) and got["GOLDBEES"]["class"] == "fund"
        assert got["ODDBOND"]["class"] == "other" and got["20MICRONS"]["class"] == "equity"
        conn = connect(db)
        # the REAL trimmed fixture already contains fund units (GOLD360, ...), not just my rows
        assert fund_symbols(conn, "NSE") == {
            s for s, r in got.items() if (r["isin"] or "").startswith("INF")}
        assert {"GOLDBEES", "GOLD360"} <= fund_symbols(conn, "NSE")
        assert classes_known(conn, "NSE") and not classes_known(conn, "BSE")

    def test_rerunning_is_idempotent_and_reclassifies(self, env):
        db, raw, fake = env
        ingest_instrument_classes(DAY, sqlite_path=db, raw_root=raw)
        n1 = len(rows(db))
        fake.text = csv_with_funds().replace("INF204KB17I5", "INE204KB17I5")
        ingest_instrument_classes(DAY, sqlite_path=db, raw_root=raw)
        assert len(rows(db)) == n1 and rows(db)["GOLDBEES"]["class"] == "equity"

    def test_a_symbol_that_stops_trading_keeps_its_class(self, env):
        db, raw, fake = env
        ingest_instrument_classes(DAY, sqlite_path=db, raw_root=raw)
        fake.text = FIXTURE  # GOLDBEES absent from the later file
        ingest_instrument_classes(date(2026, 9, 18), sqlite_path=db, raw_root=raw)
        assert rows(db)["GOLDBEES"]["class"] == "fund"

    def test_an_unpublished_day_is_a_recorded_skip_not_an_error(self, env):
        db, raw, fake = env
        fake.missing = True
        assert ingest_instrument_classes(DAY, sqlite_path=db, raw_root=raw) == 0
        conn = connect(db)
        assert conn.execute("SELECT status FROM job_runs WHERE job_name='ingest_instruments'"
                            ).fetchone()["status"] == "skipped_holiday"


def load_backtest_config():
    from decimal import Decimal  # noqa: PLC0415

    return _load_cfg().model_copy(update={"panel_min_peak_turnover_inr": Decimal(0)})


SPEC = StrategySpec.model_validate({
    "slug": "always_on", "name": "Always on", "horizon": "swing",
    "entry": {"left": {"ind": "bar_count"}, "op": ">", "right": 30},
    "exit": {"stop": {"type": "pct", "value": 0.5}, "max_hold_days": 10},
    "rank": {"by": [{"ind": "ret", "period": 20, "dir": "desc"}], "max_new_per_day": 5},
    "sizing": {"max_positions": 8},
})


class TestFundsAreNeverPicked:
    def test_a_scan_skips_funds_but_still_finds_stocks(self, tmp_path):
        days = [d.date() for d in pd.bdate_range("2025-01-01", periods=120)]
        root = tmp_path / "parquet"
        root.mkdir()
        rng = np.random.default_rng(3)
        write_panel_by_year(root, days, {
            s: [float(c) for c in 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 120))]
            for s in ("AAA", "BBB", "GOLDETF", "NIFTYBEES")})
        migrate(tmp_path / "app.db")
        conn = connect(tmp_path / "app.db")
        sid, _, _ = register_spec(conn, SPEC, origin="seed")
        set_status(conn, sid, "live", actor="user", reason="t")
        now = datetime.now(UTC).isoformat()
        conn.executemany(
            "INSERT INTO instrument_class VALUES ('NSE',?,?,?, '2026-09-17', ?)",
            [("GOLDETF", "INF1", "fund", now), ("NIFTYBEES", "INF2", "fund", now),
             ("AAA", "INE1", "equity", now), ("BBB", "INE2", "equity", now)])
        scan(conn, parquet_root=root, cfg=load_backtest_config(), scan_date=days[60])
        picked = {r["symbol"] for r in conn.execute("SELECT symbol FROM picks")}
        assert picked == {"AAA", "BBB"}

    def test_without_the_exclusion_the_funds_would_be_picked(self, tmp_path):
        """The mutation check: proves the test above is really about the exclusion."""
        days = [d.date() for d in pd.bdate_range("2025-01-01", periods=120)]
        root = tmp_path / "parquet"
        root.mkdir()
        rng = np.random.default_rng(3)
        write_panel_by_year(root, days, {
            s: [float(c) for c in 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 120))]
            for s in ("AAA", "BBB", "GOLDETF", "NIFTYBEES")})
        migrate(tmp_path / "app.db")
        conn = connect(tmp_path / "app.db")
        sid, _, _ = register_spec(conn, SPEC, origin="seed")
        set_status(conn, sid, "live", actor="user", reason="t")
        scan(conn, parquet_root=root, cfg=load_backtest_config(), scan_date=days[60])
        assert {r["symbol"] for r in conn.execute("SELECT symbol FROM picks")} >= {
            "GOLDETF", "NIFTYBEES"}


class TestGuards:
    def test_require_refuses_when_classes_were_never_ingested(self, tmp_path):
        migrate(tmp_path / "app.db")
        conn = connect(tmp_path / "app.db")
        with pytest.raises(ValueError, match=r"stk ingest instruments"):
            require_instrument_classes(conn, "NSE")

    def test_doctor_flags_bars_without_classes_but_not_a_fresh_install(self, tmp_path):
        migrate(tmp_path / "app.db")
        conn = connect(tmp_path / "app.db")
        root = tmp_path / "parquet"
        assert check_instrument_classes(conn, root) == []  # nothing ingested yet: nothing to say
        (root / "bars_daily" / "exchange=NSE" / "year=2026").mkdir(parents=True)
        (root / "bars_daily" / "exchange=NSE" / "year=2026" / "data.parquet").write_bytes(b"x")
        (p,) = check_instrument_classes(conn, root)
        assert p.code == "instrument_classes_missing" and p.is_problem
        conn.execute("INSERT INTO instrument_class VALUES ('NSE','A','INE1','equity','d','d')")
        assert check_instrument_classes(conn, root) == []

    def test_the_cli_refuses_to_scan_and_promote_until_classified(self, tmp_path, monkeypatch):
        from stk.config.settings import get_settings  # noqa: PLC0415

        monkeypatch.setenv("STK_PATHS__DATA_ROOT", str(tmp_path))
        get_settings(force_reload=True)
        try:
            migrate(tmp_path / "app.db")
            (tmp_path / "parquet").mkdir()
            days = [d.date() for d in pd.bdate_range("2025-01-01", periods=40)]
            write_panel_by_year(tmp_path / "parquet", days, {"AAA": [100.0 + i for i in range(40)]})
            runner = CliRunner()
            for args in (["scan"], ["strategies", "promote", "--all"]):
                r = runner.invoke(app, args)
                said = r.output.replace("\n", " ")
                assert r.exit_code == 1 and "stk ingest instruments" in said, (args, r.output)
        finally:
            monkeypatch.undo()
            get_settings(force_reload=True)

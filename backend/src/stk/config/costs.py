"""Dated cost-rate schedule loader.

Loads config/costs.yaml -- a history of transaction-cost rates, each
tagged with the date it took effect -- into a typed ``RateSchedule``
that resolves "what rate applied on date X" via ``as_of()``.

``rates_for(date, exchange)`` flattens the schedule into the pure
``stk.domain.costs.CostRates`` that ``compute_costs`` consumes -- the
domain layer never sees YAML or dates.

STATUS: rates in config/costs.yaml are sourced from broker-published
schedules, not verified against primary NSE/SEBI circulars. See the
warning at the top of that file. Do not rely on this for real-money
decisions until that verification pass (a phase-2 open item) is done.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from stk.config.loader import load_named_yaml
from stk.core.errors import ConfigError
from stk.domain.costs import BrokerageRule, CostRates, ProductRates


class _DatedRate(BaseModel):
    """A rate that takes effect from a given date, until superseded."""

    from_: date = Field(alias="from")
    rate: float | None = None
    per_crore_inr: float | None = None
    per_scrip_inr: float | None = None
    gst_applicable: bool | None = None
    delivery: dict[str, Any] | None = None
    intraday: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class _DatedSeries:
    """A chronologically sorted list of ``_DatedRate``, queryable by date."""

    def __init__(self, raw: list[dict]) -> None:
        self._rates = sorted((_DatedRate(**r) for r in raw), key=lambda r: r.from_)
        if not self._rates:
            raise ConfigError("dated rate series must have at least one entry")

    def as_of(self, as_of_date: date) -> _DatedRate:
        """Return the rate in effect on ``as_of_date``.

        If ``as_of_date`` predates the earliest entry, returns the
        earliest entry anyway (with the caller responsible for treating
        very old backtests as approximate) rather than raising, since a
        15-year backfill will routinely ask for dates before some rate's
        recorded introduction.
        """
        applicable = [r for r in self._rates if r.from_ <= as_of_date]
        return applicable[-1] if applicable else self._rates[0]


class RateSchedule:
    """Typed, date-resolvable view over config/costs.yaml."""

    def __init__(self, raw: dict) -> None:
        self.gst_rate: float = raw["gst_rate"]
        self.gst_applies_to: list[str] = raw["gst_applies_to"]

        self._brokerage = _DatedSeries(raw["brokerage"])
        self._stt = _DatedSeries(raw["stt"])
        self._stamp_duty = _DatedSeries(raw["stamp_duty"])
        self._sebi_turnover_fee = _DatedSeries(raw["sebi_turnover_fee"])
        self._dp_charge = _DatedSeries(raw["dp_charge"])

        self._exchange_txn: dict[str, _DatedSeries] = {
            exch: _DatedSeries(rows) for exch, rows in raw["exchange_txn_charge"].items()
        }
        self._ipft: dict[str, _DatedSeries] = {
            exch: _DatedSeries(rows) for exch, rows in raw["ipft"].items()
        }

        self.circuit_bands: dict = raw.get("circuit_bands", {})
        self.settlement: dict = raw.get("settlement", {})

    def brokerage_as_of(self, as_of_date: date) -> _DatedRate:
        return self._brokerage.as_of(as_of_date)

    def stt_as_of(self, as_of_date: date) -> _DatedRate:
        return self._stt.as_of(as_of_date)

    def stamp_duty_as_of(self, as_of_date: date) -> _DatedRate:
        return self._stamp_duty.as_of(as_of_date)

    def sebi_turnover_fee_as_of(self, as_of_date: date) -> _DatedRate:
        return self._sebi_turnover_fee.as_of(as_of_date)

    def dp_charge_as_of(self, as_of_date: date) -> _DatedRate:
        return self._dp_charge.as_of(as_of_date)

    def exchange_txn_as_of(self, exchange: str, as_of_date: date) -> _DatedRate:
        if exchange not in self._exchange_txn:
            raise ConfigError(f"no exchange_txn_charge schedule for exchange={exchange!r}")
        return self._exchange_txn[exchange].as_of(as_of_date)

    def ipft_as_of(self, exchange: str, as_of_date: date) -> _DatedRate | None:
        series = self._ipft.get(exchange)
        return series.as_of(as_of_date) if series else None

    def rates_for(self, exchange: str, as_of_date: date) -> CostRates:
        """Every rate in force for ``exchange`` on ``as_of_date``, as pure domain data."""
        brokerage = self.brokerage_as_of(as_of_date)
        stt = self.stt_as_of(as_of_date)
        stamp = self.stamp_duty_as_of(as_of_date)
        ipft = self.ipft_as_of(exchange, as_of_date)
        dp = self.dp_charge_as_of(as_of_date)
        txn = self.exchange_txn_as_of(exchange, as_of_date)
        sebi = self.sebi_turnover_fee_as_of(as_of_date)

        def product(name: str) -> ProductRates:
            b = getattr(brokerage, name) or {}
            s = getattr(stt, name) or {}
            d = getattr(stamp, name) or {}
            return ProductRates(
                brokerage=BrokerageRule(
                    model=b["model"],
                    pct=_dec(b.get("pct", 0)),
                    flat=_dec(b.get("flat_inr", b.get("amount_inr", 0))),
                ),
                stt_buy=_dec(s.get("buy", 0)),
                stt_sell=_dec(s.get("sell", 0)),
                stamp_buy=_dec(d.get("buy", 0)),
                stamp_sell=_dec(d.get("sell", 0)),
            )

        return CostRates(
            gst_rate=_dec(self.gst_rate),
            gst_applies_to=frozenset(self.gst_applies_to),
            delivery=product("delivery"),
            intraday=product("intraday"),
            exchange_txn_rate=_dec(txn.rate or 0),
            ipft_per_crore=_dec(ipft.per_crore_inr or 0) if ipft else Decimal(0),
            sebi_rate=_dec(sebi.rate or 0),
            dp_charge_inr=_dec(dp.per_scrip_inr or 0),
            dp_gst_applicable=bool(dp.gst_applicable),
        )


def _dec(value: float | int | str) -> Decimal:
    """Decimal from a YAML number without inheriting float noise (0.1 -> Decimal('0.1'))."""
    return Decimal(str(value))


_schedule: RateSchedule | None = None


def get_rate_schedule(
    *, config_dir: Path | None = None, force_reload: bool = False
) -> RateSchedule:
    """Return the process-wide RateSchedule singleton, loading config/costs.yaml on first call."""
    global _schedule  # noqa: PLW0603 -- intentional module-level singleton cache
    if _schedule is None or force_reload:
        raw = load_named_yaml("costs", config_dir=config_dir)
        _schedule = RateSchedule(raw)
    return _schedule

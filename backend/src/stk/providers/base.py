"""Provider adapter interfaces.

Every external data source (NSE, BSE, yfinance, and eventually a paid
broker API) sits behind one of these ABCs. Ingest code (``stk.ingest.*``)
must never import a concrete provider module directly -- it receives a
provider instance via ``stk.providers.registry`` and depends only on
these interfaces. That is what makes a future broker-API swap a
one-adapter, one-config-line change instead of a rewrite: see
``providers/broker/`` (phase 8 placeholder) for how a real-time paid
adapter slots in without touching ingest, domain, or the API layer.

DTOs here are pydantic models, not dicts: this module is the boundary
where garbage from the outside world gets rejected before it enters the
rest of the codebase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from stk.core.errors import NotSupportedError


class Interval(StrEnum):
    DAY_1 = "1d"
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"


class Period(StrEnum):
    QUARTERLY = "Q"
    HALF_YEARLY = "H"
    ANNUAL = "FY"
    TRAILING_TWELVE_MONTHS = "TTM"


class ProviderCapabilities(BaseModel):
    """Declares what a provider can actually do, so callers can degrade
    gracefully instead of discovering a missing feature via an exception
    at the worst possible moment (e.g. mid-backfill)."""

    model_config = ConfigDict(frozen=True)

    name: str
    exchanges: frozenset[str]
    earliest_date: date | None = None
    supports_delivery: bool = False
    supports_intraday: bool = False
    is_approximate: bool = False
    is_realtime: bool = False


class RawArtifact(BaseModel):
    """The verbatim bytes of a fetched response, plus enough provenance
    to write a ``raw_artifacts`` row and to re-parse later without the
    network."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str
    business_date: date | None
    url: str
    content: bytes
    content_type: str | None
    http_status: int
    fetched_at: datetime


class CanonicalBar(BaseModel):
    """One row of the canonical daily-bar schema that NSE UDiFF, BSE
    UDiFF and sec_bhavdata_full all normalise into. See
    ``store/parquet/schema.py`` for the on-disk Arrow schema this
    mirrors field-for-field."""

    date: date
    exchange: str
    symbol: str
    security_id: int | None = None
    isin: str | None = None
    series: str | None = None
    instrument_type: str = "EQ"

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    prev_close: Decimal | None = None
    last: Decimal | None = None
    vwap: Decimal | None = None

    volume: int
    turnover: Decimal  # rupees, always -- never lakhs/crores past this boundary
    trades: int | None = None

    delivery_qty: int | None = None  # None (not 0) when the source reports "-"
    delivery_pct: Decimal | None = None
    settle_price: Decimal | None = None

    source: str


class MasterRecord(BaseModel):
    """One row of a security-master snapshot (NSE EQUITY_L.csv / BSE ListofScripData)."""

    isin: str
    symbol: str
    company_name: str
    exchange: str
    series: str | None = None  # NSE series / BSE group
    exchange_token: str | None = None  # BSE SCRIP_CD / NSE FinInstrmId
    face_value: Decimal | None = None
    lot_size: int | None = None
    listing_date: date | None = None


class PriceBand(BaseModel):
    """A daily price-band record (NSE sec_list.csv)."""

    symbol: str
    series: str | None = None
    band_pct: int | None = None  # None means "no fixed band" (F&O-eligible, dynamic range)


class HolidayRecord(BaseModel):
    """One raw holiday row. Callers MUST intersect with weekdays --
    NSE's holiday-master API includes holidays that fall on a Saturday
    or Sunday, which are not meaningful as trading-calendar gaps."""

    trading_date: date
    description: str
    segment: str = "CBM"


class RawCorporateAction(BaseModel):
    """A corporate-action row with the subject text UNPARSED.

    Parsing free-text subjects ("Bonus 1:1", "Dividend - Rs 17.70 Per
    Share", ...) is deliberately NOT a provider responsibility: it is
    the ingest layer's job (``stk.ingest.corpactions``) so that every
    provider shares exactly one parser and one test suite, rather than
    each adapter growing its own slightly-different regex pile."""

    symbol: str
    exchange: str
    isin: str | None = None
    ex_date: date | None = None
    record_date: date | None = None
    bc_start_date: date | None = None
    bc_end_date: date | None = None
    subject_raw: str
    source: str
    source_hash: str
    captured_at: datetime


class FilingRef(BaseModel):
    """A pointer to a fundamentals filing that exists, before fetching it."""

    security_isin: str
    period_type: Period
    period_end: date
    filing_system: str  # "financial_results" | "integrated_filing"
    broadcast_at: datetime | None = None
    source_url: str | None = None


class SecurityRef(BaseModel):
    isin: str
    symbol: str
    exchange: str


class FundamentalsSnapshotIn(BaseModel):
    """A normalised fundamentals statement, ready for insertion into
    ``fundamentals_snapshots``. Provider-set fields (provider,
    is_approximate, captured_at) are filled in by the adapter, not the
    caller."""

    security_isin: str
    provider: str
    statement_type: str  # income | balance | cashflow | ratios | meta
    period_type: Period
    period_end: date
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    consolidated: bool | None = None
    audited: bool | None = None
    filing_system: str | None = None
    broadcast_at: datetime | None = None
    captured_at: datetime
    is_approximate: bool
    is_restated: bool = False
    currency: str = "INR"
    unit_multiplier: float = 1.0
    data: dict
    source_url: str | None = None
    source_hash: str


class IntradayCandle(BaseModel):
    """One intraday OHLCV candle. ``start`` is timezone-AWARE (IST) -- naive datetimes are
    refused, because comparing an aware order timestamp with a naive candle time is a bug
    waiting to happen."""

    start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0

    @field_validator("start")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("candle start must be timezone-aware")
        return v


class IntradayProvider(ABC):
    """Source of DELAYED intraday candles for the paper-trading poller.

    Deliberately separate from PriceProvider: intraday data is approximate, delayed and
    unofficial, and must never be reachable from the end-of-day price pipeline.
    """

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def fetch_candles_raw(self, symbol: str, exchange: str, interval: str = "5m") -> RawArtifact:
        """Fetch today's candles for one symbol as verbatim bytes, before any parsing."""

    @abstractmethod
    def parse_candles(self, artifact: RawArtifact) -> list[IntradayCandle]:
        """Parse a previously fetched artifact (offline; no network)."""


class PriceProvider(ABC):
    """Source of OHLCV bars for a single trading day (full-market) or,
    optionally, a single symbol's history."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def fetch_eod(self, business_date: date, exchange: str) -> RawArtifact:
        """Download the full-market EOD file for one date.

        Raises:
            ProviderUnavailable: transport failure (timeout, DNS, 5xx).
            DataNotPublished: the exchange has not yet published this date.
            ContentValidationError: response passed HTTP status but the
                body doesn't match the expected content type/magic bytes
                (the BSE "200 with an HTML SPA shell" trap).
        """

    @abstractmethod
    def parse_eod(self, artifact: RawArtifact) -> Iterator[CanonicalBar]:
        """Parse a previously-fetched artifact into canonical bars."""

    def fetch_history(
        self,
        symbol: str,
        exchange: str,
        start: date,
        end: date,
        interval: Interval = Interval.DAY_1,
    ) -> list[CanonicalBar]:
        """Per-symbol history. Optional -- full-market-file providers
        (bhavcopy-based) raise NotSupportedError; per-symbol providers
        (yfinance, future broker APIs) override this."""
        raise NotSupportedError(f"{self.capabilities.name} does not support fetch_history")


class SecurityMasterProvider(ABC):
    """Source of the active-listing snapshot (symbol/ISIN/name/lot size/...)."""

    @abstractmethod
    def fetch_master(self) -> list[MasterRecord]:
        """Full active-listing snapshot for one exchange."""

    def fetch_price_bands(self) -> list[PriceBand]:
        """Daily price-band list, used for circuit-lock detection. Optional."""
        raise NotSupportedError(f"{type(self).__name__} does not support fetch_price_bands")


class CalendarProvider(ABC):
    """Source of the trading-holiday calendar.

    Fetch and parse are separate, exactly as on PriceProvider, so the
    ingest layer can persist the raw response under data/raw/ BEFORE
    anything interprets it (see stk.ingest.raw_store). A provider that
    only exposed a combined fetch_holidays() would make the project's
    "raw bytes are sacred" rule unsatisfiable for calendars.
    """

    @abstractmethod
    def fetch_holidays_artifact(self, year: int) -> RawArtifact:
        """The raw, unparsed holiday response for a calendar year."""

    @abstractmethod
    def parse_holidays(self, artifact: RawArtifact, segment: str = "CM") -> list[HolidayRecord]:
        """Holiday rows for one segment. Callers must intersect with
        weekdays themselves -- see HolidayRecord's docstring."""

    def fetch_holidays(self, year: int, segment: str = "CM") -> list[HolidayRecord]:
        """Convenience composition for callers that do not need the raw
        bytes (interactive probing, tests). The ingest path uses
        fetch_holidays_artifact + parse_holidays so it can persist the
        artifact in between."""
        return self.parse_holidays(self.fetch_holidays_artifact(year), segment)


class CorporateActionsProvider(ABC):
    """Source of corporate-action announcements, subjects unparsed."""

    @abstractmethod
    def fetch_actions(self, since: date | None = None) -> list[RawCorporateAction]:
        """Corporate actions since ``since`` (or all available if None)."""


class FundamentalsProvider(ABC):
    """Source of company fundamentals (income/balance/cashflow statements)."""

    @property
    @abstractmethod
    def is_approximate(self) -> bool:
        """True for providers giving restated-only numbers (e.g. yfinance),
        which cannot give a true point-in-time knowledge date."""

    @abstractmethod
    def fetch_filings_index(self, since: date, period: Period) -> list[FilingRef]:
        """What filings exist -- cheap, used to decide what to fetch."""

    @abstractmethod
    def fetch_statements(
        self,
        security: SecurityRef,
        period_type: Period,
        limit: int = 12,
    ) -> list[FundamentalsSnapshotIn]:
        """Normalised statements ready for fundamentals_snapshots insertion."""

    def fetch_integrated_statements(
        self, security: SecurityRef, limit: int = 40
    ) -> list[FundamentalsSnapshotIn]:
        """Filings from the newer "Integrated Filing" system, which replaced the legacy
        financial-results feed for periods after ~Dec 2024. Optional capability."""
        raise NotSupportedError(f"{type(self).__name__} has no integrated-filing source")

    def fetch_document(self, url: str) -> RawArtifact:
        """The verbatim filing document (e.g. XBRL) behind a ``FilingRef.source_url``.

        Optional capability: providers with no downloadable filing raise
        NotSupportedError. The bytes are returned untouched so the caller can
        persist them before parsing.
        """
        raise NotSupportedError(f"{type(self).__name__} cannot fetch filing documents")

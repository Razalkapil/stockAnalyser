"""Typed application settings.

Loads config/defaults.yaml + config/env/{env}.yaml via
``config.loader``, then lets environment variables (prefix ``STK_``,
nested with ``__``) override anything -- so ``STK_PATHS__DATA_ROOT=...``
overrides ``paths.data_root``. A typo in either the YAML or an env var
name fails at startup via pydantic validation, not silently at 2am
inside a cron job.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from stk.config.loader import load_yaml_config


class AppMeta(BaseModel):
    env: str = "local"
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    log_level: str = "INFO"


class PathsConfig(BaseModel):
    data_root: Path = Path("./data")

    @property
    def raw(self) -> Path:
        return self.data_root / "raw"

    @property
    def parquet(self) -> Path:
        return self.data_root / "parquet"

    @property
    def sqlite(self) -> Path:
        return self.data_root / "app.db"

    @property
    def cache(self) -> Path:
        return self.data_root / "cache"


class IngestConfig(BaseModel):
    backfill_start: date
    udiff_available_from: date
    exchanges: list[str] = Field(default_factory=lambda: ["NSE", "BSE"])
    primary_exchange: str = "NSE"
    max_parallel_downloads: int = 4
    fail_on_unparsed_corp_action: bool = True
    eod_publish_time_ist: time = time(18, 30)


class ProvidersConfig(BaseModel):
    prices: dict[str, str] = Field(default_factory=dict)
    security_master: dict[str, str] = Field(default_factory=dict)
    calendar: str = "nse_holiday_master"
    corp_actions: str = "nse_corp_actions"
    fundamentals: list[str] = Field(default_factory=lambda: ["nse_filings", "yfinance"])
    #: yfinance is approximate, rate-limited, survivorship-biased and
    #: unofficial. It stays unreachable unless someone turns it on
    #: deliberately -- the registry raises ConfigError otherwise, so it
    #: cannot drift onto the critical path by being named in a config
    #: list somewhere.
    enable_yfinance_fallback: bool = False
    #: Delayed intraday candles for the paper-trading poller (see providers/yfinance/intraday.py).
    #: Its own switch, deliberately independent of the one above.
    intraday: str = "yfinance_intraday"
    enable_yfinance_intraday: bool = False


class HttpEndpointConfig(BaseModel):
    base: str = ""
    api_base: str | None = None
    prime_url: str | None = None
    referer: str | None = None
    cookie_ttl_s: int | None = None
    timeout_s: float = 30.0
    retries: int = 3
    backoff_s: list[float] = Field(default_factory=lambda: [2.0, 8.0, 30.0])


class YFinanceHttpConfig(BaseModel):
    impersonate: str = "chrome"
    min_interval_ms: int = 1500


class HttpConfig(BaseModel):
    nse_archives: HttpEndpointConfig = Field(default_factory=HttpEndpointConfig)
    nse_api: HttpEndpointConfig = Field(default_factory=HttpEndpointConfig)
    bse: HttpEndpointConfig = Field(default_factory=HttpEndpointConfig)
    yfinance: YFinanceHttpConfig = Field(default_factory=YFinanceHttpConfig)


class _YamlSettingsSource(PydanticBaseSettingsSource):
    """pydantic-settings source that loads config/defaults.yaml + env overlay."""

    def get_field_value(self, field: Any, field_name: str) -> Any:  # pragma: no cover - unused path
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return load_yaml_config()


class AppSettings(BaseSettings):
    """Root settings object. Construct via ``get_settings()``."""

    model_config = SettingsConfigDict(
        env_prefix="STK_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppMeta = Field(default_factory=AppMeta)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ingest: IngestConfig
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence highest-to-lowest: init kwargs, env vars, .env file,
        # then our YAML layer last (lowest priority = defaults).
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSettingsSource(settings_cls),
        )


_settings: AppSettings | None = None


def get_settings(*, force_reload: bool = False) -> AppSettings:
    """Return the process-wide settings singleton, constructing it on first call."""
    global _settings  # noqa: PLW0603 -- intentional module-level singleton cache
    if _settings is None or force_reload:
        _settings = AppSettings()  # type: ignore[call-arg]
    return _settings

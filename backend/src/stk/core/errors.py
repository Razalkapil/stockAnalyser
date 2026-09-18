"""Exception hierarchy for the ingest/provider stack.

The rule this hierarchy exists to enforce: failures must be loud and
specific. A caller that catches ``StkError`` broadly should still be
able to distinguish "the network is down" from "the data looked wrong"
from "we don't have this yet".
"""

from __future__ import annotations


class StkError(Exception):
    """Base class for all application-raised errors."""


class ProviderError(StkError):
    """Base class for provider-adapter failures."""


class ProviderUnavailable(ProviderError):
    """Transport-level failure: timeout, connection refused, DNS, 5xx."""


class DataNotPublished(ProviderError):
    """The source has not yet published data for the requested date.

    Distinct from ProviderUnavailable: this is an expected, retryable-later
    condition (e.g. asking for today's bhavcopy before ~18:30 IST), not a
    fault.
    """


class ContentValidationError(ProviderError):
    """A response passed HTTP status but failed content-type/magic-byte checks.

    This is the guard against the BSE "200 OK with an HTML SPA shell"
    failure mode: a status-code-only check would silently accept garbage.
    """

    def __init__(self, url: str, message: str, body_excerpt: bytes) -> None:
        excerpt = body_excerpt[:200]
        super().__init__(f"{message} url={url} body[:200]={excerpt!r}")
        self.url = url
        self.body_excerpt = body_excerpt


class NotSupportedError(ProviderError):
    """A provider does not implement an optional capability."""


class ParseError(StkError):
    """A response was structurally valid but semantically un-parseable.

    Used by the corporate-action subject parser to signal a subject
    string that matched no known pattern. This must never be swallowed
    into a default "no-op" action -- see ingest/corpactions.py.
    """


class IngestAssertionError(StkError):
    """A post-ingest sanity check failed (row counts, OHLC invariants, ...)."""


class ConfigError(StkError):
    """Configuration failed to load or validate."""

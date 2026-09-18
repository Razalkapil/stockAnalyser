"""Shared fetch helper for nsearchives.nseindia.com static files.

Verified 2026-09-18: these endpoints need only a non-default
User-Agent -- no cookies, no Referer. This is deliberately a thin
wrapper, not a session manager: unlike www.nseindia.com/api/*, there is
no cookie handshake here to share state for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from stk.core.errors import DataNotPublished, ProviderUnavailable
from stk.core.http import DEFAULT_UA, validate_csv_response, validate_zip_response
from stk.providers.base import RawArtifact


def _do_get(url: str, timeout_s: float) -> httpx.Response:
    try:
        return httpx.get(
            url,
            headers={"User-Agent": DEFAULT_UA},
            timeout=timeout_s,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"transport error fetching {url}: {exc}") from exc


def _to_artifact(
    response: httpx.Response, *, url: str, source: str, business_date: date | None
) -> RawArtifact:
    return RawArtifact(
        source=source,
        business_date=business_date,
        url=url,
        content=response.content,
        content_type=response.headers.get("content-type"),
        http_status=response.status_code,
        fetched_at=datetime.now(UTC),
    )


def fetch_csv_file(
    url: str,
    *,
    source: str,
    business_date: date | None,
    expected_header_token: str,
    timeout_s: float = 30.0,
) -> RawArtifact:
    """GET and content-validate a CSV file from nsearchives.nseindia.com.

    Raises DataNotPublished on 404 (an expected, retryable-later
    condition -- the exchange hasn't published this date yet).
    Raises ContentValidationError if the body doesn't look like the
    expected CSV, even on HTTP 200 -- defence in depth against the
    BSE-style "200 with wrong content" failure mode, applied here too
    even though NSE's archive host has not been observed doing this.
    """
    response = _do_get(url, timeout_s)
    if response.status_code == 404:
        raise DataNotPublished(f"{url} returned 404 -- not yet published or invalid date")

    validate_csv_response(response, url=url, expected_header_token=expected_header_token)
    return _to_artifact(response, url=url, source=source, business_date=business_date)


def fetch_zip_file(
    url: str,
    *,
    source: str,
    business_date: date | None,
    timeout_s: float = 30.0,
) -> RawArtifact:
    """GET and content-validate a zip file from nsearchives.nseindia.com."""
    response = _do_get(url, timeout_s)
    if response.status_code == 404:
        raise DataNotPublished(f"{url} returned 404 -- not yet published or invalid date")

    validate_zip_response(response, url=url)
    return _to_artifact(response, url=url, source=source, business_date=business_date)

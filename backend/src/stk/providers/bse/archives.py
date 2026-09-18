"""Fetch helper for www.bseindia.com CSV downloads.

Verified 2026-09-18 by direct curl: any User-Agent works (no cookie
handshake, unlike www.nseindia.com/api/*). But BSE has its own, more
persistent version of the "silent 200" trap documented in
stk.core.http: a bhavcopy request for a date with no data -- a weekend,
a holiday, or a date past the UDiFF format's start -- returns HTTP 200
with ``content-type: text/html`` and a ~14KB Angular SPA shell, always
the exact same shell, with no distinguishing marker between "ask again
later" and "this will never exist". Confirmed identical response for
both a real weekend date and a nonsense date (2099-12-31).

There is no way to distinguish those cases from content alone, so the
heuristic here is coarse but consistent with the rest of this
codebase's content-type-based validation: **any 200 response with a
text/html content-type is treated as DataNotPublished**, never as a
successful fetch. A genuinely corrupted CSV (truncated, wrong schema)
would not carry text/html and still hits validate_csv_response's
header-token check, which raises ContentValidationError as usual.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from stk.core.errors import DataNotPublished, ProviderUnavailable
from stk.core.http import DEFAULT_UA, validate_csv_response, validate_zip_response
from stk.providers.base import RawArtifact


def _get_and_check_shell(url: str, timeout_s: float) -> httpx.Response:
    """GET the URL and raise DataNotPublished if the response is BSE's
    SPA shell -- shared by both the CSV (UDiFF) and zip (legacy) fetch
    paths, since the shell is served identically for both URL families."""
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": DEFAULT_UA},
            timeout=timeout_s,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"transport error fetching {url}: {exc}") from exc

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if response.status_code == 200 and content_type == "text/html":
        raise DataNotPublished(
            f"{url} returned the BSE SPA shell (text/html) -- no data for this date"
        )
    return response


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


def fetch_bse_csv_file(
    url: str,
    *,
    source: str,
    business_date: date | None,
    expected_header_token: str,
    timeout_s: float = 30.0,
) -> RawArtifact:
    response = _get_and_check_shell(url, timeout_s)
    validate_csv_response(response, url=url, expected_header_token=expected_header_token)
    return _to_artifact(response, url=url, source=source, business_date=business_date)


def fetch_bse_zip_file(
    url: str,
    *,
    source: str,
    business_date: date | None,
    timeout_s: float = 30.0,
) -> RawArtifact:
    """GET and content-validate a zip file from www.bseindia.com.

    Used by the legacy pre-UDiFF bhavcopy (EQ{DDMMYY}_CSV.ZIP), which
    is served over the same URL family and exhibits the identical SPA-
    shell trap for a non-trading or invalid date -- confirmed live by
    direct probe on 2026-09-18 (see docs/adr/0003-historical-price-source.md).
    """
    response = _get_and_check_shell(url, timeout_s)
    validate_zip_response(response, url=url)
    return _to_artifact(response, url=url, source=source, business_date=business_date)

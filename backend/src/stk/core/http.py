"""Shared HTTP client factory and response validation.

This module is the single guard against the BSE "silent 200" failure
mode: legacy BSE bhavcopy URLs return HTTP 200 with content-type
text/html and a ~14KB Angular SPA shell instead of a 404. Any code that
checks only ``status_code == 200`` before unzipping will fail
confusingly downstream. Every fetch in this codebase must go through
``validate_response`` before its body is trusted.

Blocking behaviour (verified 2026-09-18):
- nsearchives.nseindia.com static files: any non-default User-Agent is
  sufficient. No cookies, no Referer needed. A bare ``curl/x.y`` UA is
  blocked; even an empty UA string works.
- www.nseindia.com/api/*: requires a cookie handshake -- GET the HTML
  page with a browser UA and a cookie jar first, then call the API with
  a plausible Referer.
- api.bseindia.com: requires Referer: https://www.bseindia.com/
"""

from __future__ import annotations

import json

import httpx

from stk.core.errors import ContentValidationError

DEFAULT_UA = "stk/0.1 (+personal research tool)"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

ZIP_MAGIC = b"PK\x03\x04"


def build_client(
    *,
    base_url: str = "",
    timeout_s: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    """Construct an httpx.Client with sane defaults for exchange fetches."""
    merged_headers = {"User-Agent": DEFAULT_UA, **(headers or {})}
    return httpx.Client(
        base_url=base_url,
        timeout=timeout_s,
        headers=merged_headers,
        follow_redirects=True,
    )


def validate_zip_response(response: httpx.Response, *, url: str) -> bytes:
    """Validate a response that is expected to be a zip file.

    Checks status, then magic bytes -- content-type headers from these
    exchanges are inconsistent (some correct zips arrive as
    application/octet-stream), so magic bytes are the authoritative check.
    """
    body = response.content
    if response.status_code != 200:
        raise ContentValidationError(url, f"unexpected status {response.status_code}", body)
    if not body:
        raise ContentValidationError(url, "empty response body", body)
    if not body.startswith(ZIP_MAGIC):
        raise ContentValidationError(url, "response is not a zip file (magic bytes mismatch)", body)
    return body


def validate_csv_response(response: httpx.Response, *, url: str, expected_header_token: str) -> str:
    """Validate a response that is expected to be a plain CSV file.

    ``expected_header_token`` is a string that must appear in the first
    line (e.g. "SYMBOL" or "TradDt"). This is what catches the BSE
    Angular-shell trap: the shell's first line contains neither token.
    """
    body = response.content
    if response.status_code != 200:
        raise ContentValidationError(url, f"unexpected status {response.status_code}", body)
    if not body:
        raise ContentValidationError(url, "empty response body", body)

    text = body.decode("utf-8", errors="replace")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if expected_header_token not in first_line:
        raise ContentValidationError(
            url,
            f"response does not look like a CSV (expected {expected_header_token!r} in header)",
            body,
        )
    return text


def validate_json_response(response: httpx.Response, *, url: str) -> dict | list:
    """Validate a response that is expected to be JSON."""
    body = response.content
    if response.status_code != 200:
        raise ContentValidationError(url, f"unexpected status {response.status_code}", body)
    if not body:
        raise ContentValidationError(url, "empty response body", body)
    stripped = body.lstrip()
    if stripped[:1] not in (b"{", b"["):
        raise ContentValidationError(url, "response does not look like JSON", body)

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContentValidationError(url, f"invalid JSON: {exc}", body) from exc


def validate_xml_response(response: httpx.Response, *, url: str) -> bytes:
    """Validate a response that is expected to be an XBRL/XML document.

    Guards the same "HTTP 200 carrying an HTML shell" trap as the BSE
    validators: an error page or SPA shell served as 200 must not reach the
    XML parser looking like a filing.
    """
    body = response.content
    if response.status_code != 200:
        raise ContentValidationError(url, f"unexpected status {response.status_code}", body)
    if not body:
        raise ContentValidationError(url, "empty response body", body)
    head = body.lstrip()[:200].lower()
    if not head.startswith(b"<"):
        raise ContentValidationError(url, "response does not look like XML", body)
    if head.startswith((b"<!doctype html", b"<html")):
        raise ContentValidationError(url, "got an HTML page where XML was expected", body)
    return body

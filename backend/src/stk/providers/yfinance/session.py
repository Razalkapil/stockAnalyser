"""Throttled, browser-impersonating session for Yahoo Finance.

Two defences, both from the build plan's risk register:

  - **curl_cffi with chrome impersonation.** Yahoo's unofficial API
    fingerprints TLS clients; a plain httpx request gets rate-limited
    or refused far sooner.
  - **A client-side minimum interval between requests.** yfinance
    raises YFRateLimitError under load, and the only reliable fix is
    not making the requests that quickly. The interval comes from
    config (`http.yfinance.min_interval_ms`), not a constant here.

This provider is off the critical path by design. Bhavcopy data is
official, free, unlimited and unauthenticated; Yahoo is none of those.
"""

from __future__ import annotations

import threading
import time

from stk.config.settings import get_settings

_lock = threading.Lock()
_last_request_at: float = 0.0


def throttle() -> None:
    """Block until at least min_interval_ms has passed since the last call.

    Process-wide and thread-safe: the rate limit is Yahoo's, not this
    call site's, so two concurrent callers must share one budget.
    """
    global _last_request_at  # noqa: PLW0603 -- shared rate-limit budget
    min_interval_s = get_settings().http.yfinance.min_interval_ms / 1000.0
    with _lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < min_interval_s:
            time.sleep(min_interval_s - elapsed)
        _last_request_at = time.monotonic()


def build_session() -> object:
    """A curl_cffi session impersonating Chrome.

    Returns ``object`` rather than a concrete type so nothing outside
    this module depends on curl_cffi's surface -- if the impersonation
    library has to change, it changes here.
    """
    from curl_cffi import requests as curl_requests  # noqa: PLC0415

    impersonate = get_settings().http.yfinance.impersonate
    return curl_requests.Session(impersonate=impersonate)

"""Tests for the content-type/magic-byte guard against the BSE 'silent
200' failure mode: legacy BSE bhavcopy URLs return HTTP 200 with
content-type text/html and an Angular SPA shell body, not a 404. Any
code trusting status_code alone would silently accept garbage.
"""

from __future__ import annotations

import httpx
import pytest

from stk.core.errors import ContentValidationError
from stk.core.http import validate_csv_response, validate_json_response, validate_zip_response

URL = "https://www.bseindia.com/download/BhavCopy/Equity/fake.CSV"

ANGULAR_SHELL_HTML = b"""<!doctype html><html><head><title>BSE</title></head>
<body><app-root></app-root><script src="runtime.js"></script></body></html>"""

REAL_CSV = (
    "TradDt,BizDt,Sgmt,Src,ISIN,TckrSymb,OpnPric,HghPric,LwPric,ClsPric\n"
    "2026-09-17,2026-09-17,CM,BSE,INE117A01022,ABB,6980.00,7161.10,6950.00,7100.00\n"
)


def _resp(status_code: int, content: bytes, content_type: str | None = None) -> httpx.Response:
    headers = {"content-type": content_type} if content_type else {}
    request = httpx.Request("GET", URL)
    return httpx.Response(status_code, content=content, headers=headers, request=request)


class TestCsvSilent200Trap:
    def test_html_shell_with_200_is_rejected(self):
        """The exact BSE failure: 200 OK, HTML body -- must raise, not parse."""
        resp = _resp(200, ANGULAR_SHELL_HTML, content_type="text/html")
        with pytest.raises(ContentValidationError) as exc_info:
            validate_csv_response(resp, url=URL, expected_header_token="TradDt")
        assert URL in str(exc_info.value)

    def test_nothing_is_accepted_as_ok_from_the_html_shell(self):
        """The trap must not be swallowed anywhere -- calling code should
        never see a return value it could go on to treat as valid."""
        resp = _resp(200, ANGULAR_SHELL_HTML, content_type="text/html")
        with pytest.raises(ContentValidationError):
            validate_csv_response(resp, url=URL, expected_header_token="TradDt")

    def test_correct_csv_with_wrong_content_type_header_is_still_accepted(self):
        """Exchanges do serve real CSVs with inconsistent content-type
        headers (e.g. application/octet-stream) -- the magic-byte /
        header-token check must accept these, not reject on header alone."""
        resp = _resp(200, REAL_CSV.encode(), content_type="application/octet-stream")
        text = validate_csv_response(resp, url=URL, expected_header_token="TradDt")
        assert "ABB" in text

    def test_html_body_with_csv_content_type_header_is_rejected(self):
        """A misleading content-type header must not override the actual body check."""
        resp = _resp(200, ANGULAR_SHELL_HTML, content_type="text/csv")
        with pytest.raises(ContentValidationError):
            validate_csv_response(resp, url=URL, expected_header_token="TradDt")

    def test_empty_body_is_rejected(self):
        resp = _resp(200, b"", content_type="text/csv")
        with pytest.raises(ContentValidationError):
            validate_csv_response(resp, url=URL, expected_header_token="TradDt")

    def test_non_200_status_is_rejected(self):
        resp = _resp(404, b"Not Found")
        with pytest.raises(ContentValidationError):
            validate_csv_response(resp, url=URL, expected_header_token="TradDt")


class TestZipValidation:
    def test_real_zip_magic_bytes_accepted(self):
        resp = _resp(200, b"PK\x03\x04rest-of-zip-bytes")
        body = validate_zip_response(resp, url=URL)
        assert body.startswith(b"PK")

    def test_html_shell_masquerading_as_zip_is_rejected(self):
        """Mirror of the BSE CSV trap for the NSE/BSE zip download path."""
        resp = _resp(200, ANGULAR_SHELL_HTML, content_type="application/zip")
        with pytest.raises(ContentValidationError):
            validate_zip_response(resp, url=URL)

    def test_empty_zip_response_is_rejected(self):
        resp = _resp(200, b"")
        with pytest.raises(ContentValidationError):
            validate_zip_response(resp, url=URL)


class TestJsonValidation:
    def test_valid_json_object_accepted(self):
        resp = _resp(200, b'{"symbol": "INFY"}', content_type="application/json")
        data = validate_json_response(resp, url=URL)
        assert data["symbol"] == "INFY"

    def test_valid_json_array_accepted(self):
        resp = _resp(200, b'[{"a": 1}]', content_type="application/json")
        data = validate_json_response(resp, url=URL)
        assert data[0]["a"] == 1

    def test_html_error_page_rejected(self):
        resp = _resp(200, ANGULAR_SHELL_HTML, content_type="application/json")
        with pytest.raises(ContentValidationError):
            validate_json_response(resp, url=URL)

    def test_malformed_json_rejected(self):
        resp = _resp(200, b'{"broken": ', content_type="application/json")
        with pytest.raises(ContentValidationError):
            validate_json_response(resp, url=URL)

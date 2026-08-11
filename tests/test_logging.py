import logging

import httpx
from pytest import MonkeyPatch

from kra_analytics.logging import (
    REDACTED_SECRET,
    SecretRedactionFilter,
    redact_secrets,
    safe_exception_message,
)


def test_api_key_is_redacted(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("KRA_API_KEY", "do-not-print-this-key")
    record = logging.LogRecord(
        name="kra_analytics",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request key=%s",
        args=("do-not-print-this-key",),
        exc_info=None,
    )

    assert SecretRedactionFilter().filter(record)
    assert record.getMessage() == f"request key={REDACTED_SECRET}"


def test_redact_secrets_handles_service_key_case_and_url_encoding() -> None:
    values = (
        "https://example.test?a=1&serviceKey=SECRET_VALUE&meet=1",
        "https://example.test?ServiceKey=SECRET_VALUE&meet=1",
        "https://example.test?ServiceKey=SECRET%2BVALUE%3D%3D&meet=1",
    )

    for value in values:
        redacted = redact_secrets(value, secrets=("SECRET+VALUE==",))
        assert "SECRET_VALUE" not in redacted
        assert "SECRET%2BVALUE%3D%3D" not in redacted
        assert REDACTED_SECRET in redacted


def test_safe_exception_message_redacts_httpx_request_url() -> None:
    request = httpx.Request(
        "GET", "https://example.test/api?ServiceKey=SECRET_VALUE&meet=1"
    )
    response = httpx.Response(403, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        message = safe_exception_message(error, secrets=("SECRET_VALUE",))
    else:  # pragma: no cover - defensive assertion for httpx behavior
        raise AssertionError("Expected HTTPStatusError")

    assert "SECRET_VALUE" not in message
    assert f"ServiceKey={REDACTED_SECRET}" in message

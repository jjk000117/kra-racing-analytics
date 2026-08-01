import logging

from pytest import MonkeyPatch

from kra_analytics.logging import SecretRedactionFilter


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
    assert record.getMessage() == "request key=REDACTED"

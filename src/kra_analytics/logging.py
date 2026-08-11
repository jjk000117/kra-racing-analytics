from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable
from urllib.parse import quote, quote_plus

REDACTED_SECRET = "***REDACTED***"
_SERVICE_KEY_PATTERN = re.compile(r"(?i)(servicekey\s*=\s*)([^&\s\"'<>]+)")


def redact_secrets(text: object, *, secrets: Iterable[str] = ()) -> str:
    """Redact ServiceKey query values and known raw/URL-encoded secret values."""
    redacted = _SERVICE_KEY_PATTERN.sub(rf"\1{REDACTED_SECRET}", str(text))
    configured = [os.getenv("KRA_API_KEY", ""), *secrets]
    variants: set[str] = set()
    for secret in configured:
        if secret:
            variants.update({secret, quote(secret, safe=""), quote_plus(secret, safe="")})
    for value in sorted(variants, key=len, reverse=True):
        redacted = redacted.replace(value, REDACTED_SECRET)
    return redacted


def safe_exception_message(error: BaseException, *, secrets: Iterable[str] = ()) -> str:
    """Return an exception summary safe for logs, manifests, and user messages."""
    return redact_secrets(f"{type(error).__name__}: {error}", secrets=secrets)


class SecretRedactionFilter(logging.Filter):
    """Prevent a configured KRA API key from appearing in formatted log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def configure_logging(level: str | None = None) -> logging.Logger:
    """Configure a single project logger for CLI and future pipeline stages."""
    logger = logging.getLogger("kra_analytics")
    logger.handlers.clear()
    configured_level = level if level is not None else os.getenv("KRA_LOG_LEVEL", "INFO")
    logger.setLevel(configured_level.upper())
    logger.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)
    return logger

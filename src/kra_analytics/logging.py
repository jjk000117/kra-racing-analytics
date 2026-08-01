from __future__ import annotations

import logging
import os
import sys


class SecretRedactionFilter(logging.Filter):
    """Prevent a configured KRA API key from appearing in formatted log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        secret = os.getenv("KRA_API_KEY", "")
        if secret:
            record.msg = record.getMessage().replace(secret, "REDACTED")
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

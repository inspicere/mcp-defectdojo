import json
import logging
import os
import sys
from datetime import datetime, timezone

# Fields present on every LogRecord — used to filter extra kwargs
_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach any extra fields passed via logger.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_FIELDS:
                data[key] = value
        return json.dumps(data, default=str)


class RedactingFilter(logging.Filter):
    """Replace sensitive credential values in log records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = []
        api_key = os.environ.get("DEFECTDOJO_API_KEY")
        if api_key:
            secrets.append(api_key)
        auth_token = os.environ.get("MCP_AUTH_TOKEN")
        if auth_token:
            secrets.append(auth_token)

        def _redact(value: str) -> str:
            for secret in secrets:
                value = value.replace(secret, "***REDACTED***")
            # Replace Token <value> patterns
            import re
            value = re.sub(r"Token \S+", "Token ***REDACTED***", value)
            return value

        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact(v) if isinstance(v, str) else v
                    for v in record.args
                )

        return True


def configure_logging() -> None:
    """Configure root logger with structured JSON output and sensitive data redaction."""
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    raw_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = raw_level if raw_level in valid_levels else "INFO"

    root_logger = logging.getLogger()

    # Remove all existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(RedactingFilter())

    root_logger.setLevel(level)
    root_logger.addHandler(handler)

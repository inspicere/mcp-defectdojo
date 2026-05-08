import functools
import inspect
import json
import logging
import os
import re
import sys
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Fields present on every LogRecord — used to filter extra kwargs
_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())

current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_FIELDS:
                data[key] = value
        if record.exc_info and record.exc_info[0]:
            data["exception"] = traceback.format_exception(*record.exc_info)
        if record.stack_info:
            data["stack_info"] = record.stack_info
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

        for key in list(record.__dict__):
            if key not in _LOG_RECORD_FIELDS and isinstance(record.__dict__[key], str):
                record.__dict__[key] = _redact(record.__dict__[key])

        return True


def audit_tool(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # 1. Find ctx parameter if present
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        ctx = bound.arguments.get("ctx")

        # 2. Extract request_id from ctx (with fallback)
        request_id = str(uuid.uuid4())
        if ctx is not None:
            try:
                request_id = str(ctx.request_id)
            except (RuntimeError, AttributeError):
                pass

        # 3. Extract caller_id from ctx
        caller_id = "anonymous"
        if ctx is not None:
            try:
                caller_id = ctx.client_id or "anonymous"
            except (RuntimeError, AttributeError):
                pass

        # 4. Set contextvar so client.py can read it
        token = current_request_id.set(request_id)

        # 5. Build request_params from kwargs (exclude ctx)
        request_params = {k: v for k, v in bound.arguments.items() if k != "ctx" and v is not None}

        # 6. Log anonymous access warning
        if caller_id == "anonymous":
            logger.warning("Anonymous tool access", extra={"event_type": "security_warning", "tool_name": func.__name__, "request_id": request_id})

        # 7. Time and execute
        t0 = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.info("Tool call completed", extra={
                "event_type": "audit",
                "tool_name": func.__name__,
                "request_id": request_id,
                "caller_id": caller_id,
                "request_params": request_params,
                "outcome": "success",
                "duration_ms": duration_ms,
            })
            return result
        except Exception as e:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.error("Tool call failed", extra={
                "event_type": "audit",
                "tool_name": func.__name__,
                "request_id": request_id,
                "caller_id": caller_id,
                "request_params": request_params,
                "outcome": "error",
                "duration_ms": duration_ms,
                "error": str(e),
            })
            raise
        finally:
            current_request_id.reset(token)
    return wrapper


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

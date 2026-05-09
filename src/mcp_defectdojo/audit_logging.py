import functools
import hashlib
import hmac as hmac_mod
import inspect
import json
import logging
import logging.handlers
import os
import re
import secrets
import sys
import time
import traceback
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())

current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

_RETENTION_MAP = {
    "audit": "security_audit",
    "security_warning": "security_audit",
    "lifecycle": "operational",
    "api_request": "operational",
    "api_response": "operational",
    "api_error": "operational",
    "connection_error": "operational",
}


class StructuredJsonFormatter(logging.Formatter):
    def _build_data(self, record: logging.LogRecord) -> dict:
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
        return data

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self._build_data(record), default=str)


class IntegrityChainFormatter(StructuredJsonFormatter):
    def __init__(self, hmac_key: bytes):
        super().__init__()
        self._hmac_key = hmac_key
        self._previous_hmac = ""

    def format(self, record: logging.LogRecord) -> str:
        data = self._build_data(record)

        event_type = data.get("event_type", "")
        data["retention_class"] = _RETENTION_MAP.get(event_type, "debug")

        payload = f"{self._previous_hmac}|{json.dumps(data, default=str)}"
        entry_hmac = hmac_mod.new(
            self._hmac_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        data["integrity_hmac"] = entry_hmac
        self._previous_hmac = entry_hmac

        return json.dumps(data, default=str)


class RedactingFilter(logging.Filter):
    _SECRET_ENV_VARS = (
        "DEFECTDOJO_API_KEY", "DEFECTDOJO_READ_API_KEY", "DEFECTDOJO_WRITE_API_KEY",
        "MCP_AUTH_TOKEN", "MCP_READ_TOKEN", "AUDIT_HMAC_KEY",
    )

    def __init__(self, name: str = ""):
        super().__init__(name)
        self.refresh_secrets()

    def refresh_secrets(self) -> None:
        self._secrets = [v for k in self._SECRET_ENV_VARS if (v := os.environ.get(k))]

    def filter(self, record: logging.LogRecord) -> bool:
        secrets_list = self._secrets

        def _redact_str(value: str) -> str:
            for secret in secrets_list:
                value = value.replace(secret, "***REDACTED***")
            value = re.sub(r"Token \S+", "Token ***REDACTED***", value)
            return value

        def _redact(value):
            if isinstance(value, str):
                return _redact_str(value)
            if isinstance(value, dict):
                return {k: _redact(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                redacted = [_redact(v) for v in value]
                return type(value)(redacted)
            return value

        if isinstance(record.msg, str):
            record.msg = _redact_str(record.msg)

        if record.args:
            record.args = _redact(record.args)

        for key in list(record.__dict__):
            if key not in _LOG_RECORD_FIELDS:
                record.__dict__[key] = _redact(record.__dict__[key])

        return True


class SessionCounter:
    def __init__(self):
        self.total_requests = 0
        self.requests_by_tool: dict[str, int] = {}
        self.error_count = 0
        self.start_time = time.monotonic()

    def record(self, tool_name: str, outcome: str) -> None:
        self.total_requests += 1
        self.requests_by_tool[tool_name] = self.requests_by_tool.get(tool_name, 0) + 1
        if outcome == "error":
            self.error_count += 1

    def summary(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "requests_by_tool": dict(self.requests_by_tool),
            "error_count": self.error_count,
            "uptime_seconds": round(time.monotonic() - self.start_time, 2),
        }


_session_counter = SessionCounter()


def audit_tool(func):
    sig = inspect.signature(func)

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        ctx = bound.arguments.get("ctx")

        request_id = str(uuid.uuid4())
        if ctx is not None:
            try:
                request_id = str(ctx.request_id)
            except (RuntimeError, AttributeError):
                pass

        caller_id = "anonymous"
        if ctx is not None:
            try:
                caller_id = ctx.client_id or "anonymous"
            except (RuntimeError, AttributeError):
                pass

        token = current_request_id.set(request_id)

        _TRUNCATE_FIELDS = frozenset({"description", "title"})
        request_params = {}
        for k, v in bound.arguments.items():
            if k == "ctx" or v is None:
                continue
            if k in _TRUNCATE_FIELDS and isinstance(v, str):
                request_params[k] = f"<{len(v)} chars>"
            else:
                request_params[k] = v

        if caller_id == "anonymous":
            logger.warning("Anonymous tool access", extra={"event_type": "security_warning", "tool_name": func.__name__, "request_id": request_id})

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
            _session_counter.record(func.__name__, "success")
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
            _session_counter.record(func.__name__, "error")
            raise
        finally:
            current_request_id.reset(token)
    return wrapper


def configure_logging() -> None:
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    raw_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = raw_level if raw_level in valid_levels else "INFO"

    hmac_key_str = os.environ.get("AUDIT_HMAC_KEY", "")
    if hmac_key_str:
        hmac_key = hmac_key_str.encode()
    else:
        hmac_key = secrets.token_bytes(32)
        logger.critical(
            "AUDIT_HMAC_KEY not set — using ephemeral key. "
            "Log integrity chain will be unverifiable after restart.",
            extra={"event_type": "security_warning"},
        )

    root_logger = logging.getLogger()

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    redacting_filter = RedactingFilter()
    redacting_filter.refresh_secrets()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(IntegrityChainFormatter(hmac_key))
    stderr_handler.addFilter(redacting_filter)

    root_logger.setLevel(level)
    root_logger.addHandler(stderr_handler)

    audit_log_file = os.environ.get("AUDIT_LOG_FILE")
    if audit_log_file:
        file_handler = logging.handlers.WatchedFileHandler(audit_log_file)
        file_handler.setFormatter(IntegrityChainFormatter(hmac_key))
        file_handler.addFilter(redacting_filter)
        root_logger.addHandler(file_handler)
        logger.info("Audit log file enabled", extra={"event_type": "lifecycle", "audit_log_file": audit_log_file})

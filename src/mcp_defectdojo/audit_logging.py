import functools
import hashlib
import hmac as hmac_mod
import inspect
import json
import logging
import logging.handlers
import os
import queue
import re
import secrets
import socket
import ssl
import sys
import threading
import time
import traceback
import uuid
import warnings
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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
        "MCP_AUTH_TOKEN", "MCP_READ_TOKEN", "AUDIT_HMAC_KEY", "AUDIT_LOG_HTTPS_TOKEN",
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


_SYSLOG_SEVERITY = {
    logging.CRITICAL: 2,
    logging.ERROR: 3,
    logging.WARNING: 4,
    logging.INFO: 6,
    logging.DEBUG: 7,
}


class SyslogForwardHandler(logging.Handler):
    """RFC 5424 syslog forwarding over TCP, UDP, or TCP+TLS."""

    FACILITY_LOCAL0 = 16

    def __init__(
        self, host: str, port: int, *,
        transport: str = "tcp+tls",
        ca_cert: str | None = None,
        facility: int = FACILITY_LOCAL0,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.transport = transport
        self.ca_cert = ca_cert
        self.facility = facility
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()

    def _connect(self) -> None:
        if self.transport == "udp":
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((self.host, self.port))
        if self.transport == "tcp+tls":
            ctx = ssl.create_default_context(cafile=self.ca_cert)
            sock = ctx.wrap_socket(sock, server_hostname=self.host)
        self._sock = sock

    def _close_sock(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            severity = _SYSLOG_SEVERITY.get(record.levelno, 6)
            priority = self.facility * 8 + severity
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            hostname = socket.gethostname()
            msg = self.format(record)
            syslog_line = (
                f"<{priority}>1 {ts} {hostname} mcp-defectdojo"
                f" {os.getpid()} - - {msg}"
            )
            data = syslog_line.encode("utf-8")

            with self._sock_lock:
                for attempt in range(2):
                    try:
                        if self._sock is None:
                            self._connect()
                        if self.transport == "udp":
                            self._sock.sendto(data, (self.host, self.port))
                        else:
                            framed = f"{len(data)} ".encode() + data
                            self._sock.sendall(framed)
                        return
                    except (OSError, ssl.SSLError):
                        self._close_sock()
                        if attempt == 1:
                            raise
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._close_sock()
        super().close()


class HTTPSLogHandler(logging.Handler):
    """HTTPS log forwarding with batching and background delivery."""

    def __init__(
        self, url: str, *,
        token: str | None = None,
        batch_size: int = 10,
        flush_interval: float = 5.0,
    ):
        super().__init__()
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"AUDIT_LOG_HTTPS_URL must use https (or http) scheme, got '{parsed.scheme}'")
        if parsed.scheme == "http":
            warnings.warn(
                "AUDIT_LOG_HTTPS_URL uses http:// — log data will be transmitted unencrypted. Use https:// in production.",
                stacklevel=2,
            )
        self.url = url
        self.token = token
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._queue: queue.Queue[str] = queue.Queue(maxsize=10000)
        self._shutdown = threading.Event()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="audit-https-fwd",
        )
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put_nowait(msg)
        except queue.Full:
            self.handleError(record)

    def _worker(self) -> None:
        batch: list[str] = []
        while not self._shutdown.is_set():
            try:
                item = self._queue.get(timeout=self.flush_interval)
                batch.append(item)
                if len(batch) >= self.batch_size:
                    self._flush(batch)
                    batch = []
            except queue.Empty:
                if batch:
                    self._flush(batch)
                    batch = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._flush(batch)

    def _flush(self, batch: list[str]) -> None:
        payload = json.dumps([json.loads(line) for line in batch]).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(self.url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            print(f"AUDIT-LOG-HTTPS-FORWARD-ERROR: {e}", file=sys.stderr)

    def close(self) -> None:
        self._shutdown.set()
        self._thread.join(timeout=10)
        super().close()


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

    syslog_url = os.environ.get("AUDIT_LOG_SYSLOG")
    if syslog_url:
        if "://" not in syslog_url:
            syslog_url = f"tcp+tls://{syslog_url}"
        parsed = urlparse(syslog_url)
        scheme_map = {"tcp": "tcp", "udp": "udp", "tcp+tls": "tcp+tls", "tls": "tcp+tls"}
        transport = scheme_map.get(parsed.scheme or "", "tcp+tls")
        host = parsed.hostname or "localhost"
        default_port = 6514 if "tls" in transport else 514
        port = parsed.port or default_port
        ca_cert = os.environ.get("AUDIT_LOG_SYSLOG_CA")

        syslog_handler = SyslogForwardHandler(
            host, port, transport=transport, ca_cert=ca_cert,
        )
        syslog_handler.setFormatter(IntegrityChainFormatter(hmac_key))
        syslog_handler.addFilter(redacting_filter)
        root_logger.addHandler(syslog_handler)
        logger.info("Syslog forwarding enabled", extra={
            "event_type": "lifecycle",
            "syslog_host": host, "syslog_port": port,
            "syslog_transport": transport,
        })

    https_url = os.environ.get("AUDIT_LOG_HTTPS_URL")
    if https_url:
        https_token = os.environ.get("AUDIT_LOG_HTTPS_TOKEN")
        batch_size = int(os.environ.get("AUDIT_LOG_HTTPS_BATCH_SIZE", "10"))
        flush_secs = float(os.environ.get("AUDIT_LOG_HTTPS_FLUSH_SECS", "5"))

        https_handler = HTTPSLogHandler(
            https_url, token=https_token,
            batch_size=batch_size, flush_interval=flush_secs,
        )
        https_handler.setFormatter(IntegrityChainFormatter(hmac_key))
        https_handler.addFilter(redacting_filter)
        root_logger.addHandler(https_handler)
        logger.info("HTTPS log forwarding enabled", extra={
            "event_type": "lifecycle",
            "https_url": https_url, "https_batch_size": batch_size,
            "https_flush_secs": flush_secs,
        })

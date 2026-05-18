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

from .security import (
    _PLACEHOLDER_GATED_CLASSES,
    _SECRET_PATTERNS,
    is_placeholder_value,
)

logger = logging.getLogger(__name__)

_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())

current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")

# F-002 audit linkage — set of finding IDs the current session has read prior
# to issuing a mutation. Populated by get_finding/list_findings/list_finding_notes
# and emitted as `findings_read_before_mutation` on every mutation audit record
# so cross-finding causality is reconstructable after a stored-prompt-injection
# event. The ContextVar carries the *reference* to a mutable set so all reads
# in the same async task accumulate into one collection (separate sessions
# get their own set via `record_finding_read`'s `set_default` semantics).
_MUTATION_TOOL_NAMES: frozenset[str] = frozenset({
    "create_product", "create_engagement", "create_test",
    "create_finding", "update_finding", "close_finding", "reopen_finding",
    "import_scan", "reimport_scan",
    "add_finding_note", "add_finding_tags", "remove_finding_tags",
})

findings_read_this_session: ContextVar[set[int] | None] = ContextVar(
    "findings_read_this_session", default=None
)


def record_finding_read(finding_id: int | None) -> None:
    """Append a finding ID to the session-local read-history set.

    Called from read tools (`get_finding`, `list_findings`, `list_finding_notes`)
    to leave a trace that downstream mutation audit events can surface for
    cross-finding causality analysis (F-002 mitigation #4).
    """
    if finding_id is None:
        return
    try:
        fid = int(finding_id)
    except (TypeError, ValueError):
        return
    bucket = findings_read_this_session.get()
    if bucket is None:
        bucket = set()
        findings_read_this_session.set(bucket)
    bucket.add(fid)

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
    def __init__(self, hmac_key: bytes, seed_previous_hmac: str = ""):
        super().__init__()
        self._hmac_key = hmac_key
        self._previous_hmac = seed_previous_hmac
        self._lock = threading.RLock()

    def format(self, record: logging.LogRecord) -> str:
        # AUD-01 — share one canonical line across all handlers. When this
        # formatter is attached to multiple handlers, the FIRST handler's
        # format() call computes the HMAC and caches the formatted string
        # on the record; subsequent handlers reuse it. Without this, each
        # handler's chain state would diverge silently when any one sink
        # drops records (queue back-pressure, circuit-breaker open, etc.),
        # destroying the tamper-evident property under partial-failure.
        cached = getattr(record, "_integrity_formatted", None)
        if cached is not None:
            return cached

        with self._lock:
            cached = getattr(record, "_integrity_formatted", None)
            if cached is not None:
                return cached

            data = self._build_data(record)
            event_type = data.get("event_type", "")
            data["retention_class"] = _RETENTION_MAP.get(event_type, "debug")

            serialized = json.dumps(data, default=str)
            payload = f"{self._previous_hmac}|{serialized}"
            entry_hmac = hmac_mod.new(
                self._hmac_key, payload.encode(), hashlib.sha256
            ).hexdigest()
            self._previous_hmac = entry_hmac

            result = f'{serialized[:-1]}, "integrity_hmac": "{entry_hmac}"}}'
            record._integrity_formatted = result
            return result


_TOKEN_PATTERN = re.compile(r"Token \S+")


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
            value = _TOKEN_PATTERN.sub("Token ***REDACTED***", value)
            for cls_name, pattern in _SECRET_PATTERNS:
                if cls_name in _PLACEHOLDER_GATED_CLASSES:
                    def _gated_sub(m: re.Match, _cls=cls_name) -> str:
                        captured = m.group(1) if m.lastindex else m.group(0)
                        if is_placeholder_value(captured):
                            return m.group(0)
                        return f"[REDACTED:{_cls}]"
                    value = pattern.sub(_gated_sub, value)
                else:
                    value = pattern.sub(f"[REDACTED:{cls_name}]", value)
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
    """RFC 5424 syslog forwarding over TCP, UDP, or TCP+TLS with background delivery."""

    FACILITY_LOCAL0 = 16
    _CIRCUIT_BREAKER_THRESHOLD = 3
    _CIRCUIT_BREAKER_RECOVERY_SECS = 30.0

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
        self._queue: queue.Queue[str] = queue.Queue(maxsize=10000)
        self._shutdown = threading.Event()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="audit-syslog-fwd",
        )
        self._thread.start()

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
            self._queue.put_nowait(syslog_line)
        except queue.Full:
            self.handleError(record)

    def _send(self, data: bytes) -> None:
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

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                line = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            now = time.monotonic()
            if now < self._circuit_open_until:
                continue
            try:
                self._send(line.encode("utf-8"))
                self._consecutive_failures = 0
            except Exception:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._CIRCUIT_BREAKER_THRESHOLD:
                    self._circuit_open_until = time.monotonic() + self._CIRCUIT_BREAKER_RECOVERY_SECS
                    logger.error(
                        "Syslog forwarder circuit breaker open",
                        extra={
                            "event_type": "audit_forward_failure",
                            "forwarder": "syslog",
                            "consecutive_failures": self._consecutive_failures,
                            "recovery_seconds": self._CIRCUIT_BREAKER_RECOVERY_SECS,
                            "host": self.host,
                            "port": self.port,
                        },
                    )
        while not self._queue.empty():
            try:
                line = self._queue.get_nowait()
                self._send(line.encode("utf-8"))
            except (queue.Empty, Exception):
                break

    def close(self) -> None:
        self._shutdown.set()
        self._thread.join(timeout=10)
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
            logger.error(
                "HTTPS log forwarder delivery failed",
                extra={
                    "event_type": "audit_forward_failure",
                    "forwarder": "https",
                    "reason": type(e).__name__,
                    "batch_size": len(batch),
                    "url": self.url,
                },
            )

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

_session_shutdown_emitted = False
_session_shutdown_lock = threading.Lock()


def emit_session_shutdown(reason: str = "lifespan_exit") -> None:
    """Emit the canonical session-shutdown record exactly once per process.

    Safe to call from both the FastMCP lifespan `finally:` block and an
    atexit hook — first caller wins (typically lifespan under graceful
    shutdown; atexit fires under SIGTERM when the lifespan is bypassed).
    """
    global _session_shutdown_emitted
    with _session_shutdown_lock:
        if _session_shutdown_emitted:
            return
        _session_shutdown_emitted = True
    try:
        logger.info(
            "Session shutdown",
            extra={
                "event_type": "lifecycle",
                "session_summary": _session_counter.summary(),
                "shutdown_reason": reason,
            },
        )
    except Exception:
        pass

_TRUNCATE_FIELDS = frozenset({"description", "title", "file", "entry"})

OPEN_ACCESS_CALLER_ID = "open-access"


def resolve_identity(ctx) -> tuple[str, str]:
    """Return (authenticated_caller_id, meta_caller_id) for the current request.

    Trust model — see DEC-023 / Phase 9 / T3:
    - authenticated_caller_id: derived from the bearer-token-bound client_id
      (set by build_rbac_auth() via StaticTokenVerifier). This is the trusted
      identity. Falls back to "open-access" when no auth is configured.
      Use this for rate-limit bucketing and access-control decisions.
    - meta_caller_id: derived from ctx.client_id, which FastMCP reads from
      the JSON-RPC request `_meta.client_id` field. This is client-controlled
      and untrusted. Use only for tracing / forensic correlation.
    """
    authenticated = OPEN_ACCESS_CALLER_ID
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        if token is not None and token.client_id:
            authenticated = token.client_id
    except RuntimeError:
        pass

    meta = "anonymous"
    if ctx is not None:
        try:
            meta = ctx.client_id or "anonymous"
        except (RuntimeError, AttributeError):
            pass

    return authenticated, meta


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

        # Identity resolution — see DEC-023.
        # caller_id: the legacy meta-derived field, kept for SIEM backward compat.
        # authenticated_caller_id: the trusted, bearer-token-bound identity.
        authenticated_caller_id, caller_id = resolve_identity(ctx)

        token = current_request_id.set(request_id)
        request_params = {}
        for k, v in bound.arguments.items():
            if k == "ctx" or v is None:
                continue
            if k in _TRUNCATE_FIELDS and isinstance(v, str):
                request_params[k] = f"<{len(v)} chars>"
            else:
                request_params[k] = v

        if authenticated_caller_id == OPEN_ACCESS_CALLER_ID:
            logger.warning(
                "Open-access tool call (no authenticated identity)",
                extra={
                    "event_type": "security_warning",
                    "tool_name": func.__name__,
                    "request_id": request_id,
                    "meta_caller_id": caller_id,
                },
            )

        # F-002 audit linkage — snapshot the read-history at mutation time so the
        # audit event records which findings the session loaded into context
        # before mutating. Only attached for mutation tools to avoid noise.
        is_mutation = func.__name__ in _MUTATION_TOOL_NAMES
        read_history_snapshot: list[int] = []
        if is_mutation:
            current = findings_read_this_session.get()
            if current:
                read_history_snapshot = sorted(current)

        t0 = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            extra = {
                "event_type": "audit",
                "tool_name": func.__name__,
                "request_id": request_id,
                "caller_id": caller_id,
                "authenticated_caller_id": authenticated_caller_id,
                "request_params": request_params,
                "outcome": "success",
                "duration_ms": duration_ms,
            }
            if is_mutation:
                extra["findings_read_before_mutation"] = read_history_snapshot
            logger.info("Tool call completed", extra=extra)
            _session_counter.record(func.__name__, "success")
            return result
        except Exception as e:
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            extra = {
                "event_type": "audit",
                "tool_name": func.__name__,
                "request_id": request_id,
                "caller_id": caller_id,
                "authenticated_caller_id": authenticated_caller_id,
                "request_params": request_params,
                "outcome": "error",
                "duration_ms": duration_ms,
                "error": str(e),
            }
            if is_mutation:
                extra["findings_read_before_mutation"] = read_history_snapshot
            logger.error("Tool call failed", extra=extra)
            _session_counter.record(func.__name__, "error")
            raise
        finally:
            current_request_id.reset(token)
    return wrapper


def _restore_chain_tail(audit_log_file: str) -> tuple[str, str]:
    """Return (previous_hmac, status).

    status ∈ {"resumed", "no_prior_file", "empty_file", "unreadable"}.
    Robust to: missing file, empty file, truncated final line
    (crash mid-write), final line missing the integrity_hmac field.
    Scans only the trailing ≤64 KiB to bound startup cost on huge logs.
    """
    try:
        with open(audit_log_file, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            if size == 0:
                return ("", "empty_file")
            fh.seek(max(0, size - 65536))
            tail = fh.read()
    except FileNotFoundError:
        return ("", "no_prior_file")
    except OSError:
        return ("", "unreadable")

    for candidate in reversed(tail.split(b"\n")):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            hmac_val = parsed.get("integrity_hmac")
            if isinstance(hmac_val, str) and hmac_val:
                return (hmac_val, "resumed")
        except (json.JSONDecodeError, ValueError):
            continue
    return ("", "unreadable")


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

    # AUD-01 — one shared chain formatter across all handlers so the
    # tamper-evident chain has a single canonical sequence regardless of
    # how many sinks consume each record.
    # AUD-02 — seed from prior process's last integrity_hmac when available.
    audit_log_file = os.environ.get("AUDIT_LOG_FILE")
    seed = ""
    status = "no_prior_file"
    if audit_log_file:
        seed, status = _restore_chain_tail(audit_log_file)
    chain_formatter = IntegrityChainFormatter(hmac_key, seed_previous_hmac=seed)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(chain_formatter)
    stderr_handler.addFilter(redacting_filter)

    root_logger.setLevel(level)
    root_logger.addHandler(stderr_handler)

    if audit_log_file:
        file_handler = logging.handlers.WatchedFileHandler(audit_log_file)
        file_handler.setFormatter(chain_formatter)
        file_handler.addFilter(redacting_filter)
        root_logger.addHandler(file_handler)

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
        syslog_handler.setFormatter(chain_formatter)
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
        https_handler.setFormatter(chain_formatter)
        https_handler.addFilter(redacting_filter)
        root_logger.addHandler(https_handler)
        logger.info("HTTPS log forwarding enabled", extra={
            "event_type": "lifecycle",
            "https_url": https_url, "https_batch_size": batch_size,
            "https_flush_secs": flush_secs,
        })

    logger.info(
        "Audit chain start",
        extra={
            "event_type": "lifecycle",
            "chain_event": "chain_start",
            "resumed_from_prior": status == "resumed",
            "prior_chain_tail": seed[:12] if status == "resumed" else None,
            "prior_tail_status": status,
        },
    )
    if status == "unreadable":
        logger.warning(
            "Prior chain tail unreadable — starting fresh chain",
            extra={
                "event_type": "lifecycle",
                "chain_event": "chain_start",
                "prior_tail_status": status,
            },
        )


# ---------------------------------------------------------------------------
# Read-side response redaction (F-005 / F-016)
# ---------------------------------------------------------------------------
#
# The write-side `validate_no_secrets` validator (security.py) blocks new
# secrets from being stored, but legacy data already inside DefectDojo predates
# that guard. `redact_response_text` is applied in the read pipeline (inside
# `_format_response()` before `_apply_untrusted_wrapping`) so that any
# previously-stored secret bytes are replaced with a `[REDACTED:<class>]`
# marker before the value leaves the server. The class name matches the entry
# in security._SECRET_PATTERNS, giving SIEMs a tokenizable provenance string.


def redact_response_text(value, field_name: str):
    """Replace embedded-secret-like substrings with `[REDACTED:<class>]`.

    Accepts `str`, `list[str]`, or `None` (mirroring the wrapped fields in
    server.py: title/description/tags/notes/entry/file_path/component_name).
    `None` passes through; lists are redacted element-wise. The `field_name`
    argument exists for symmetry with the validator API and for future
    field-specific tuning — it is not used today.
    """
    if value is None:
        return value
    if isinstance(value, list):
        return [redact_response_text(v, field_name) for v in value]
    if not isinstance(value, str):
        return value
    if not value:
        return value
    redacted = value
    for cls_name, pattern in _SECRET_PATTERNS:
        if cls_name in _PLACEHOLDER_GATED_CLASSES:
            def _gated_sub(m: re.Match, _cls=cls_name) -> str:
                captured = m.group(1) if m.lastindex else m.group(0)
                if is_placeholder_value(captured):
                    return m.group(0)
                return f"[REDACTED:{_cls}]"
            redacted = pattern.sub(_gated_sub, redacted)
        else:
            redacted = pattern.sub(f"[REDACTED:{cls_name}]", redacted)
    return redacted

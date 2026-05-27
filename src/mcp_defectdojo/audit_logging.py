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

from fastmcp.exceptions import ToolError

from .security import (
    _PLACEHOLDER_GATED_CLASSES,
    _SECRET_ALTERNATION_RE,
    _SECRET_PATTERNS,
    _parse_positive_float,
    _parse_positive_int,
    _placeholder_value_from_match,
    is_placeholder_value,
)

logger = logging.getLogger(__name__)

_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys()) | {"_redacted_exc_text", "_integrity_formatted"}

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
        # SEC-08: prefer the pre-redacted exception text stashed by
        # RedactingFilter if present. Falls back to live `exc_info` formatting
        # for any code path that bypasses the filter (defense-in-depth — the
        # filter is on every handler, but a future regression that drops it
        # should still produce structured output, not silent loss).
        redacted_exc = getattr(record, "_redacted_exc_text", None)
        if redacted_exc is not None:
            data["exception"] = redacted_exc
        elif record.exc_info and record.exc_info[0]:
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


# SEC-09 (Phase 14.2): broadened beyond the original `Token \S+` to cover
# Bearer, API[_-]?Key, and apikey forms with `=`, `:`, or whitespace separators.
# Replacement string is the bare `[REDACTED]` marker (no class) — this is the
# generic auth-keyword redactor, separate from the `_SECRET_ALTERNATION_RE`
# classifier in security.py.
#
# The trailing `(?!\[REDACTED)` negative lookahead prevents a second pass from
# eating an already-classified `[REDACTED:bearer_token]` marker. Without it the
# alternation classifier's specific markers would be silently re-redacted to
# the bare `[REDACTED]` marker, losing the SIEM-correlation class name.
_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:Token|Bearer|API[_-]?Key|apikey)[ =:]\s*(?!\[REDACTED)\S+"
)


def _alternation_redact_callback(m: re.Match) -> str:
    """Substitution callback for `_SECRET_ALTERNATION_RE.sub` (AC-14.3).

    Replaces every secret-pattern match with `[REDACTED:<class>]`, except
    when the Phase 11 / SB-001 placeholder gate (DEC-026) recognises the
    captured value as documentation/example text (e.g. `<value>`, `${VAR}`,
    `YOUR_PASSWORD_HERE`). In that case the original substring is preserved
    so vulnerability prose stays readable.

    `_placeholder_value_from_match` extracts the assignment-value substring
    (the inner `(\\S{12,})` capture) for gated classes, falling back to the
    full named-group match for the non-gated catalog entries.
    """
    cls = m.lastgroup
    if cls is None:
        return m.group(0)
    if cls in _PLACEHOLDER_GATED_CLASSES:
        captured = _placeholder_value_from_match(m)
        if is_placeholder_value(captured):
            return m.group(0)  # placeholder — leave unchanged
    return f"[REDACTED:{cls}]"


class RedactingFilter(logging.Filter):
    _SECRET_ENV_VARS = (
        "DEFECTDOJO_API_KEY", "DEFECTDOJO_READ_API_KEY", "DEFECTDOJO_WRITE_API_KEY",
        "MCP_AUTH_TOKEN", "MCP_READ_TOKEN", "AUDIT_HMAC_KEY", "AUDIT_LOG_HTTPS_TOKEN",
    )

    def __init__(self, name: str = ""):
        super().__init__(name)
        self.refresh_secrets()

    def refresh_secrets(self) -> None:
        # Legacy fixed-name secret env vars (DEFECTDOJO_API_KEY, MCP_AUTH_TOKEN, …).
        secrets: list[str] = [
            v for k in self._SECRET_ENV_VARS if (v := os.environ.get(k))
        ]
        # MCP_ROLE_* dynamic RBAC tokens (Phase 8). Format is `<token>:<role>` per
        # rbac.build_rbac_auth — we extract the token portion via rpartition(":")
        # to mirror that parser exactly (token may contain ':' itself; the role
        # is always after the LAST ':'). Token bytes are added to the literal
        # redaction list so they're masked even when they leak into a log line
        # without a Token/Bearer/APIKey keyword prefix.
        for k, v in os.environ.items():
            if not k.startswith("MCP_ROLE_") or not v or ":" not in v:
                continue
            token_part, _, _ = v.rpartition(":")
            if token_part:
                secrets.append(token_part)
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        secrets_list = self._secrets

        def _redact_str(value: str) -> str:
            # Pass 1: env-var literal redaction (DEFECTDOJO_API_KEY etc.) —
            # handles a different concern than the pattern-based detector and
            # MUST run first so the env-var bytes are gone before any pattern
            # walks the string.
            for secret in secrets_list:
                value = value.replace(secret, "***REDACTED***")
            # Pass 2: secret-pattern alternation (AC-14.3) — single sub-walk
            # replaces the per-pattern loop. Preserves the Phase 11 / SB-001
            # placeholder gate for `_PLACEHOLDER_GATED_CLASSES`. Runs BEFORE
            # the generic SEC-09 token redactor so specific class markers
            # (`[REDACTED:bearer_token]`, `[REDACTED:github_pat]`, etc.)
            # survive — the broader Token/Bearer/APIKey alternation otherwise
            # eats keyword-prefixed bytes before the classifier sees them.
            value = _SECRET_ALTERNATION_RE.sub(_alternation_redact_callback, value)
            # Pass 3: generic auth-keyword fallback (SEC-09 broadened set).
            # Catches Token/Bearer/API-Key/apikey forms whose payload doesn't
            # match any specific secret-pattern class but still merits
            # redaction.
            return _TOKEN_PATTERN.sub("[REDACTED]", value)

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

        # SEC-08 (Phase 14.2): redact exception tracebacks. Formatter renders
        # `record.exc_info` into the JSON `exception` field via
        # `traceback.format_exception(*record.exc_info)`. Without this pass,
        # any secret-shape token inside an exception message bypasses the
        # filter entirely. Pre-format, redact, stash on
        # `record._redacted_exc_text`, and clear `exc_info` so the formatter
        # falls back to `record.exc_text` (Python's documented contract).
        if record.exc_info:
            import traceback as _tb
            formatted = "".join(_tb.format_exception(*record.exc_info))
            record._redacted_exc_text = _redact_str(formatted)
            record.exc_info = None
            record.exc_text = record._redacted_exc_text

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
        self._drain()

    def _drain(self) -> None:
        # DD #3452: previous implementation caught both queue.Empty and the
        # bare Exception superclass with the same break — a single send failure
        # silently dropped the rest of the queue. Now continues past per-line
        # failures and emits a structured event for each.
        while True:
            try:
                line = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._send(line.encode("utf-8"))
            except Exception as e:
                logger.warning(
                    "Syslog forwarder drain send failed",
                    extra={
                        "event_type": "audit_forward_failure",
                        "forwarder": "syslog",
                        "phase": "drain",
                        "reason": type(e).__name__,
                        "host": self.host,
                        "port": self.port,
                    },
                )

    def close(self) -> None:
        self._shutdown.set()
        self._thread.join(timeout=10)
        self._close_sock()
        super().close()


class HTTPSLogHandler(logging.Handler):
    """HTTPS log forwarding with batching and background delivery."""

    _CIRCUIT_BREAKER_THRESHOLD = 3
    _CIRCUIT_BREAKER_RECOVERY_SECS = 30.0
    _RETRY_BACKOFF_SECS = 1.0

    def __init__(
        self, url: str, *,
        token: str | None = None,
        batch_size: int = 10,
        flush_interval: float = 5.0,
        ca_cert: str | None = None,
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
        self.ca_cert = ca_cert
        # DD #3453: build an SSLContext lazily from ca_cert so operators
        # forwarding to an internally PKI-signed SIEM can supply their own CA
        # bundle without provisioning it into the system trust store.
        self._ssl_context = ssl.create_default_context(cafile=ca_cert) if ca_cert else None
        self._queue: queue.Queue[str] = queue.Queue(maxsize=10000)
        self._shutdown = threading.Event()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
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
                    self._flush_with_circuit_breaker(batch)
                    batch = []
            except queue.Empty:
                if batch:
                    self._flush_with_circuit_breaker(batch)
                    batch = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._flush_with_circuit_breaker(batch)

    def _flush_with_circuit_breaker(self, batch: list[str]) -> None:
        # DD #3451: gate flushes on the circuit breaker so a down SIEM doesn't
        # generate one failed delivery per batch. When the circuit is open
        # we drop the batch (matching the syslog forwarder's behavior).
        if time.monotonic() < self._circuit_open_until:
            return
        if self._flush(batch):
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._CIRCUIT_BREAKER_THRESHOLD:
                self._circuit_open_until = time.monotonic() + self._CIRCUIT_BREAKER_RECOVERY_SECS
                logger.error(
                    "HTTPS forwarder circuit breaker open",
                    extra={
                        "event_type": "audit_forward_failure",
                        "forwarder": "https",
                        "reason": "circuit_open",
                        "consecutive_failures": self._consecutive_failures,
                        "recovery_seconds": self._CIRCUIT_BREAKER_RECOVERY_SECS,
                        "url": self.url,
                    },
                )

    def _flush(self, batch: list[str]) -> bool:
        # DD #3451: retry once on transient failure with a short backoff,
        # mirroring the SyslogForwardHandler._send 2-attempt pattern.
        # Returns True on success, False after both attempts fail.
        # DD #3460: each `line` in batch is already a serialized JSON object
        # produced by IntegrityChainFormatter — concatenate them into a JSON
        # array directly instead of round-tripping every line through
        # json.loads+json.dumps. Wire format (application/json array) is
        # unchanged; CPU cost in _flush drops from O(N) parses to O(1).
        payload = ("[" + ",".join(batch) + "]").encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(self.url, data=payload, headers=headers, method="POST")
        urlopen_kwargs: dict = {"timeout": 10}
        if self._ssl_context is not None and self.url.startswith("https://"):
            urlopen_kwargs["context"] = self._ssl_context

        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                # `self.url` is operator-controlled via AUDIT_LOG_HTTPS_URL and is
                # validated at construction time (urlparse scheme+hostname check at
                # __init__). It is never mutated after construction and never
                # attacker-influenced — the dynamic content in the Request is the
                # payload (audit log batch), not the URL. DD #2480 triaged as
                # false-positive 2026-05-22.
                with urlopen(req, **urlopen_kwargs) as resp:
                    resp.read()
                return True
            except Exception as e:
                last_exc = e
                if attempt == 1:
                    time.sleep(self._RETRY_BACKOFF_SECS)
        logger.error(
            "HTTPS log forwarder delivery failed",
            extra={
                "event_type": "audit_forward_failure",
                "forwarder": "https",
                "reason": type(last_exc).__name__ if last_exc else "Unknown",
                "batch_size": len(batch),
                "url": self.url,
            },
        )
        return False

    def close(self) -> None:
        self._shutdown.set()
        self._thread.join(timeout=10)
        super().close()


class _FailFastQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler that fails-fast on a saturated audit queue.

    Drop-newest semantics: when the underlying `queue.Queue.put_nowait` raises
    `queue.Full`, the incoming record is discarded and a single-line structured
    JSON warning is written directly to stderr describing the overflow. The
    sustained-overload behavior is therefore deterministic — newest records are
    the ones dropped, older queued records continue to drain through the
    QueueListener to the file handler.

    AUD-01 invariant: the stderr-write path here intentionally BYPASSES the
    queue (and therefore the IntegrityChainFormatter that runs on the file
    handler). The queue-overflow event is an OPERATIONAL signal about the audit
    pipeline's health, not an audit event in the integrity chain. Routing it
    via `logger.warning(...)` would re-enter this same QueueHandler, risk
    recursive-deadlock under sustained pressure, and pollute the tamper-evident
    chain with infrastructure noise.
    """

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            payload = {
                "event_type": "audit_queue_overflow",
                "queue_size": getattr(self.queue, "maxsize", None),
                "dropped_record_logger": record.name,
                "dropped_record_level": record.levelname,
            }
            try:
                sys.stderr.write(json.dumps(payload, default=str) + "\n")
                sys.stderr.flush()
            except (ValueError, OSError):
                # stderr may be closed during interpreter teardown — swallow
                # so the dropped record doesn't escalate into a crash.
                pass


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

# PERF-03: holds the QueueListener wrapping the audit file handler so the
# main thread can drain it during graceful shutdown. None when no file
# handler was configured (no AUDIT_LOG_FILE) or before configure_logging()
# has run for the first time.
_audit_file_queue_listener: "logging.handlers.QueueListener | None" = None


def _stop_audit_queue_listener() -> None:
    """Stop the file-handler QueueListener and drain queued records.

    Idempotent. Must run BEFORE emit_session_shutdown() in lifespan/atexit
    so the shutdown record reaches disk before the listener stops.

    QueueListener.stop() blocks until the worker thread observes the sentinel
    and exits, which guarantees every record posted via QueueHandler before
    this call is processed by the destination WatchedFileHandler.
    """
    global _audit_file_queue_listener
    if _audit_file_queue_listener is not None:
        try:
            _audit_file_queue_listener.stop()  # blocks until queue drained
        except Exception:
            pass
        _audit_file_queue_listener = None


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
    # Test-teardown safety: pytest closes stderr before atexit runs, so the
    # StreamHandler.emit() inside logger.info() raises ValueError on write.
    # Python's logging framework normally swallows that ValueError and then
    # writes a "--- Logging error ---" traceback to stderr (which also fails,
    # but only after polluting test output). Suppress that path by flipping
    # `logging.raiseExceptions` False around the call AND wrapping in a broad
    # except. Production path is unaffected — the lifespan finally: clause
    # sets _session_shutdown_emitted=True before atexit fires.
    _prev_raise = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        try:
            logger.info(
                "Session shutdown",
                extra={
                    "event_type": "lifecycle",
                    "session_summary": _session_counter.summary(),
                    "shutdown_reason": reason,
                },
            )
        except ValueError:
            pass
    except Exception:
        pass
    finally:
        logging.raiseExceptions = _prev_raise

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


def _translate_client_errors(func):
    """Translate RuntimeError from the client layer into a ToolError for MCP clients.

    The client layer (`DefectDojoClient._request`) raises `RuntimeError` with a
    sanitized message. MCP tools must surface that as `ToolError` so the error
    flows through the FastMCP protocol cleanly. Decorator stacks ABOVE
    `@audit_tool` so the audit-event 'outcome' field is still set to 'error'
    by audit_tool's except clause (it catches ToolError, which inherits Exception).

    ASYNC-ONLY: SB-5 — applied to async MCP tool handlers only. Decoration of
    a sync function fails fast at import time rather than producing the
    confusing `TypeError: object ... is not awaitable` on first call.
    """
    assert inspect.iscoroutinefunction(func), (
        f"_translate_client_errors expects an async function, got {func!r}"
    )
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RuntimeError as e:
            raise ToolError(str(e))
    return wrapper


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

    # DOM-22 (Phase 14.2): fail-CLOSED on missing AUDIT_HMAC_KEY when running
    # on a network transport. Mirrors the REQUIRE_AUTH=false escape hatch in
    # server.lifespan — operators who explicitly opt out get the legacy
    # ephemeral-key behavior with the existing CRITICAL warning above.
    if not hmac_key_str:
        transport = os.environ.get("FASTMCP_TRANSPORT", "")
        require_hmac = os.environ.get("REQUIRE_AUDIT_HMAC_KEY", "").lower()
        if transport in ("sse", "streamable-http", "http") and require_hmac != "false":
            raise ValueError(
                f"AUDIT_HMAC_KEY not set on network transport '{transport}' — "
                "set REQUIRE_AUDIT_HMAC_KEY=false to opt out (not recommended)."
            )

    root_logger = logging.getLogger()

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    redacting_filter = RedactingFilter()
    redacting_filter.refresh_secrets()

    # SB-1 fix (Phase 14 Wave 3): RedactingFilter MUST be attached to each
    # handler, not the root logger. Python's `Logger.callHandlers()` walks
    # the parent chain to dispatch records to ancestor HANDLERS but does
    # NOT invoke `Logger.filter()` on ancestor loggers. With the filter only
    # on root, records propagated from child loggers (e.g. `mcp_defectdojo.server`)
    # would reach root's handlers WITHOUT redaction — silently bypassing the
    # NCUA/FFIEC audit-log redaction guarantee. The perf gain from PERF-09
    # was based on a misreading of those semantics. The alternation regex
    # (PERF-01 / AC-14.3) still gives the per-invocation perf win.

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
        # PERF-03: file_handler runs in a background thread via QueueListener so
        # the asyncio event loop is never blocked on disk I/O. The destination
        # handler retains the IntegrityChainFormatter (AUD-01 single-chain) and
        # RedactingFilter (SB-1 per-handler redaction). The QueueHandler that
        # is attached to root_logger is transport-only — it does not format or
        # filter, just enqueues the LogRecord. The listener thread invokes the
        # destination handler exactly once per record, preserving both the
        # tamper-evident chain order and per-handler redaction semantics.
        file_handler = logging.handlers.WatchedFileHandler(audit_log_file)
        file_handler.setFormatter(chain_formatter)
        file_handler.addFilter(redacting_filter)
        queue_size = _parse_positive_int("AUDIT_LOG_QUEUE_SIZE", 10000)
        file_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        queue_handler = _FailFastQueueHandler(file_queue)
        queue_listener = logging.handlers.QueueListener(
            file_queue, file_handler, respect_handler_level=True,
        )
        queue_listener.start()
        global _audit_file_queue_listener
        _audit_file_queue_listener = queue_listener
        root_logger.addHandler(queue_handler)

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
        batch_size = _parse_positive_int("AUDIT_LOG_HTTPS_BATCH_SIZE", 10)
        flush_secs = _parse_positive_float("AUDIT_LOG_HTTPS_FLUSH_SECS", 5.0)
        https_ca = os.environ.get("AUDIT_LOG_HTTPS_CA")

        https_handler = HTTPSLogHandler(
            https_url, token=https_token,
            batch_size=batch_size, flush_interval=flush_secs,
            ca_cert=https_ca,
        )
        https_handler.setFormatter(chain_formatter)
        https_handler.addFilter(redacting_filter)
        root_logger.addHandler(https_handler)
        logger.info("HTTPS log forwarding enabled", extra={
            "event_type": "lifecycle",
            "https_url": https_url, "https_batch_size": batch_size,
            "https_flush_secs": flush_secs,
            "https_ca": https_ca or None,
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

    PERF-01 / AC-14.3: single `re.sub` walk over the pre-compiled alternation
    regex (`_SECRET_ALTERNATION_RE`) replaces the per-pattern loop. The
    Phase 11 / SB-001 placeholder gate is preserved inside the callback.
    """
    if value is None:
        return value
    if isinstance(value, list):
        return [redact_response_text(v, field_name) for v in value]
    if not isinstance(value, str):
        return value
    if not value:
        return value
    return _SECRET_ALTERNATION_RE.sub(_alternation_redact_callback, value)

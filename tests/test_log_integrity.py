"""Tests for Phase 6 — Log Integrity & Export features."""
import hashlib
import hmac as hmac_mod
import io
import json
import logging
import os
import tempfile

import pytest

from mcp_defectdojo.audit_logging import (
    IntegrityChainFormatter,
    RedactingFilter,
    SessionCounter,
    StructuredJsonFormatter,
    _restore_chain_tail,
    configure_logging,
)


def _make_logger_with_integrity(
    name: str, hmac_key: bytes = b"test-key"
) -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(IntegrityChainFormatter(hmac_key))
    handler.addFilter(RedactingFilter())

    lg = logging.getLogger(name)
    lg.handlers = []
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    return lg, buf


def _parse_lines(buf: io.StringIO) -> list[dict]:
    buf.seek(0)
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# FR-028 — Log export to dedicated file
# ---------------------------------------------------------------------------


def test_audit_log_file_created(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        log_path = f.name

    try:
        monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        configure_logging()

        lg = logging.getLogger("test.file_export")
        lg.info("test entry", extra={"event_type": "audit"})

        _reset_root_handlers()

        with open(log_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert "integrity_hmac" in entry
    finally:
        os.unlink(log_path)


def test_audit_log_no_file_by_default(monkeypatch):
    monkeypatch.delenv("AUDIT_LOG_FILE", raising=False)
    configure_logging()

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 0

    root.handlers = []


def test_audit_log_lines_are_valid_json(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        log_path = f.name

    try:
        monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
        configure_logging()

        lg = logging.getLogger("test.valid_json")
        lg.info("line one", extra={"event_type": "audit"})
        lg.warning("line two", extra={"event_type": "security_warning"})
        lg.debug("line three")

        _reset_root_handlers()

        with open(log_path) as f:
            for line in f:
                if line.strip():
                    json.loads(line)
    finally:
        os.unlink(log_path)


# ---------------------------------------------------------------------------
# FR-029 — Integrity chain (HMAC-SHA256)
# ---------------------------------------------------------------------------


def test_integrity_hmac_present():
    lg, buf = _make_logger_with_integrity("test.hmac_present")
    lg.info("test message", extra={"event_type": "audit"})

    entries = _parse_lines(buf)
    assert len(entries) == 1
    assert "integrity_hmac" in entries[0]
    assert len(entries[0]["integrity_hmac"]) == 64


def test_integrity_chain_verifiable():
    hmac_key = b"verification-key"
    lg, buf = _make_logger_with_integrity("test.chain_verify", hmac_key)

    lg.info("first", extra={"event_type": "audit"})
    lg.info("second", extra={"event_type": "lifecycle"})
    lg.info("third", extra={"event_type": "audit"})

    entries = _parse_lines(buf)
    assert len(entries) == 3

    previous_hmac = ""
    for entry in entries:
        stored_hmac = entry.pop("integrity_hmac")
        payload = f"{previous_hmac}|{json.dumps(entry, default=str)}"
        expected_hmac = hmac_mod.new(
            hmac_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        assert stored_hmac == expected_hmac, f"HMAC mismatch for entry: {entry['message']}"
        previous_hmac = stored_hmac


def test_integrity_chain_shared_across_handlers():
    # AUD-01 regression — when one IntegrityChainFormatter is attached to
    # multiple handlers, every handler must emit the IDENTICAL canonical
    # line for the same record. Before the fix, configure_logging() gave
    # each handler its own formatter with independent _previous_hmac state,
    # so the on-disk and SIEM-forwarded chains diverged silently whenever
    # any one sink dropped records.
    hmac_key = b"shared-chain-key"
    shared_formatter = IntegrityChainFormatter(hmac_key)

    buf_a = io.StringIO()
    buf_b = io.StringIO()
    handler_a = logging.StreamHandler(buf_a)
    handler_b = logging.StreamHandler(buf_b)
    handler_a.setFormatter(shared_formatter)
    handler_b.setFormatter(shared_formatter)

    lg = logging.getLogger("test.chain_shared")
    lg.handlers = []
    lg.addHandler(handler_a)
    lg.addHandler(handler_b)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False

    lg.info("first", extra={"event_type": "audit"})
    lg.info("second", extra={"event_type": "lifecycle"})
    lg.info("third", extra={"event_type": "audit"})

    lines_a = [l for l in buf_a.getvalue().splitlines() if l.strip()]
    lines_b = [l for l in buf_b.getvalue().splitlines() if l.strip()]

    # Both sinks must see byte-identical records for the same emission.
    assert lines_a == lines_b, "handlers diverged — chain is not unified"

    # And the unified chain must still re-verify end-to-end.
    entries = [json.loads(l) for l in lines_a]
    assert len(entries) == 3
    previous_hmac = ""
    for entry in entries:
        stored_hmac = entry.pop("integrity_hmac")
        payload = f"{previous_hmac}|{json.dumps(entry, default=str)}"
        expected_hmac = hmac_mod.new(
            hmac_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        assert stored_hmac == expected_hmac
        previous_hmac = stored_hmac


def test_integrity_chain_detects_tamper():
    hmac_key = b"tamper-key"
    lg, buf = _make_logger_with_integrity("test.chain_tamper", hmac_key)

    lg.info("entry one", extra={"event_type": "audit"})
    lg.info("entry two", extra={"event_type": "audit"})

    entries = _parse_lines(buf)
    assert len(entries) == 2

    entries[0]["message"] = "TAMPERED"

    previous_hmac = ""
    tamper_detected = False
    for entry in entries:
        stored_hmac = entry.pop("integrity_hmac")
        payload = f"{previous_hmac}|{json.dumps(entry, default=str)}"
        expected_hmac = hmac_mod.new(
            hmac_key, payload.encode(), hashlib.sha256
        ).hexdigest()
        if stored_hmac != expected_hmac:
            tamper_detected = True
            break
        previous_hmac = stored_hmac

    assert tamper_detected, "Tamper should have been detected"


# ---------------------------------------------------------------------------
# FR-031 — Retention metadata
# ---------------------------------------------------------------------------


def test_retention_class_security_audit():
    lg, buf = _make_logger_with_integrity("test.retention_sec")
    lg.info("audit event", extra={"event_type": "audit"})
    lg.warning("security warning", extra={"event_type": "security_warning"})

    entries = _parse_lines(buf)
    assert all(e["retention_class"] == "security_audit" for e in entries)


def test_retention_class_operational():
    lg, buf = _make_logger_with_integrity("test.retention_ops")
    lg.info("lifecycle event", extra={"event_type": "lifecycle"})
    lg.debug("api request", extra={"event_type": "api_request"})

    entries = _parse_lines(buf)
    assert all(e["retention_class"] == "operational" for e in entries)


def test_retention_class_debug():
    lg, buf = _make_logger_with_integrity("test.retention_debug")
    lg.info("generic message")

    entries = _parse_lines(buf)
    assert len(entries) == 1
    assert entries[0]["retention_class"] == "debug"


# ---------------------------------------------------------------------------
# FR-030 — Session counter and summary
# ---------------------------------------------------------------------------


def test_session_counter_tracks_calls():
    counter = SessionCounter()
    counter.record("list_products", "success")
    counter.record("list_products", "success")
    counter.record("create_finding", "success")

    assert counter.total_requests == 3
    assert counter.requests_by_tool == {"list_products": 2, "create_finding": 1}


def test_session_counter_tracks_errors():
    counter = SessionCounter()
    counter.record("get_product", "success")
    counter.record("get_product", "error")

    assert counter.total_requests == 2
    assert counter.error_count == 1


def test_session_summary_format():
    counter = SessionCounter()
    counter.record("health_check", "success")
    summary = counter.summary()

    assert "total_requests" in summary
    assert "requests_by_tool" in summary
    assert "error_count" in summary
    assert "uptime_seconds" in summary
    assert summary["total_requests"] == 1
    assert summary["requests_by_tool"]["health_check"] == 1
    assert isinstance(summary["uptime_seconds"], float)


# ---------------------------------------------------------------------------
# AUD-02 — Cross-session HMAC chain continuity (Phase 10 / T1)
# ---------------------------------------------------------------------------


def _reset_root_handlers():
    # PERF-03: file writes go through a QueueListener. Drain the queue and
    # stop the listener BEFORE clearing handlers so all enqueued records
    # have been written to the file on disk by the time tests assert on it.
    from mcp_defectdojo.audit_logging import _stop_audit_queue_listener
    _stop_audit_queue_listener()
    logging.getLogger().handlers = []


def _read_log_lines(path: str) -> list[dict]:
    result = []
    with open(path) as f:
        for l in f:
            if l.strip():
                try:
                    result.append(json.loads(l))
                except json.JSONDecodeError:
                    pass
    return result


def _last_raw_line(path: str) -> str:
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return lines[-1]


def test_chain_tail_restoration_resumes_from_prior_file(monkeypatch, tmp_path):
    log_path = str(tmp_path / "audit.log")
    hmac_key = b"resume-test-key"

    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", hmac_key.decode())
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    lg = logging.getLogger("test.resume.first")
    lg.info("record one", extra={"event_type": "audit"})
    lg.info("record two", extra={"event_type": "audit"})
    lg.info("record three", extra={"event_type": "audit"})
    _reset_root_handlers()

    prior_session_last_hmac = _read_log_lines(log_path)[-1]["integrity_hmac"]

    configure_logging()
    lg2 = logging.getLogger("test.resume.second")
    lg2.info("record four", extra={"event_type": "audit"})
    _reset_root_handlers()

    lines = _read_log_lines(log_path)
    chain_start_record = next(
        (r for r in lines if r.get("chain_event") == "chain_start" and r.get("resumed_from_prior") is True),
        None,
    )
    assert chain_start_record is not None, "Missing resumed chain_start record"
    assert chain_start_record["prior_chain_tail"] == prior_session_last_hmac[:12], (
        "chain_start.prior_chain_tail must match first 12 chars of prior session's last HMAC"
    )

    record_four = lines[-1]
    record_four_raw = _last_raw_line(log_path)
    chain_start_hmac = chain_start_record["integrity_hmac"]

    serialized = record_four_raw[: record_four_raw.rfind(', "integrity_hmac":')] + "}"
    expected = hmac_mod.new(
        hmac_key,
        f"{chain_start_hmac}|{serialized}".encode(),
        hashlib.sha256,
    ).hexdigest()

    assert record_four["integrity_hmac"] == expected, (
        "record four must chain from chain_start's integrity_hmac"
    )

    chain_start_raw = next(
        raw for raw in open(log_path).readlines()
        if "chain_start" in raw and "resumed_from_prior" in raw and '"resumed_from_prior": true' in raw
    )
    cs_serialized = chain_start_raw.rstrip("\n")
    cs_serialized = cs_serialized[: cs_serialized.rfind(', "integrity_hmac":')] + "}"
    expected_cs_hmac = hmac_mod.new(
        hmac_key,
        f"{prior_session_last_hmac}|{cs_serialized}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert chain_start_record["integrity_hmac"] == expected_cs_hmac, (
        "chain_start HMAC must chain from prior session's last integrity_hmac"
    )


def test_chain_start_event_emitted_on_resume(monkeypatch, tmp_path):
    log_path = str(tmp_path / "audit.log")
    hmac_key = b"chain-start-resume-key"

    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", hmac_key.decode())
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    lg = logging.getLogger("test.chain_start_resume.first")
    lg.info("seed record", extra={"event_type": "audit"})
    _reset_root_handlers()

    prior_hmac = _read_log_lines(log_path)[-1]["integrity_hmac"]

    configure_logging()
    _reset_root_handlers()

    lines = _read_log_lines(log_path)
    chain_start_records = [
        r for r in lines
        if r.get("chain_event") == "chain_start" and r.get("resumed_from_prior") is True
    ]
    assert len(chain_start_records) >= 1, "Expected at least one resumed chain_start event"
    cs = chain_start_records[-1]
    assert cs["prior_chain_tail"] == prior_hmac[:12]
    assert cs["prior_tail_status"] == "resumed"


def test_chain_start_event_emitted_on_fresh_start(monkeypatch, tmp_path):
    log_path = str(tmp_path / "fresh.log")
    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", "freshkey123")
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    _reset_root_handlers()

    lines = _read_log_lines(log_path)
    chain_start_records = [
        r for r in lines
        if r.get("chain_event") == "chain_start"
    ]
    assert len(chain_start_records) >= 1
    cs = chain_start_records[0]
    assert cs["resumed_from_prior"] is False
    assert cs["prior_tail_status"] == "no_prior_file"


def test_chain_tail_truncated_starts_fresh(monkeypatch, tmp_path):
    log_path = str(tmp_path / "truncated.log")
    truncated_line = b'{"timestamp": "2026-05-17T00:00:00Z", "message": "trunc\n'
    log_path_obj = tmp_path / "truncated.log"
    log_path_obj.write_bytes(truncated_line)

    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", "trunckey123")
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    _reset_root_handlers()

    lines = _read_log_lines(log_path)
    chain_start_records = [
        r for r in lines
        if r.get("chain_event") == "chain_start" and "resumed_from_prior" in r
    ]
    assert len(chain_start_records) >= 1
    cs = chain_start_records[0]
    assert cs["prior_tail_status"] == "unreadable"
    assert cs["resumed_from_prior"] is False

    warning_records = [
        r for r in lines
        if r.get("level") == "WARNING" and "unreadable" in r.get("message", "")
    ]
    assert len(warning_records) >= 1, "Expected a WARNING about unreadable chain tail"


def test_chain_tail_missing_hmac_field_starts_fresh(monkeypatch, tmp_path):
    log_path = str(tmp_path / "no_hmac.log")
    valid_json_no_hmac = json.dumps({
        "timestamp": "2026-05-17T00:00:00Z",
        "level": "INFO",
        "logger": "test",
        "message": "no integrity_hmac field here",
        "event_type": "audit",
        "retention_class": "security_audit",
    })
    (tmp_path / "no_hmac.log").write_text(valid_json_no_hmac + "\n")

    seed, status = _restore_chain_tail(log_path)
    assert seed == ""
    assert status == "unreadable"

    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", "nohmackey")
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    _reset_root_handlers()

    all_lines = _read_log_lines(log_path)
    cs_records = [r for r in all_lines if r.get("chain_event") == "chain_start"]
    assert len(cs_records) >= 1
    assert cs_records[0]["prior_tail_status"] == "unreadable"


def test_chain_tail_scans_only_trailing_window(monkeypatch, tmp_path):
    log_path = str(tmp_path / "large.log")
    hmac_key = b"large-file-key"

    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", hmac_key.decode())
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    configure_logging()
    lg = logging.getLogger("test.large_file")
    for i in range(5):
        lg.info(f"seed record {i}", extra={"event_type": "audit"})
    _reset_root_handlers()

    with open(log_path, "rb") as f:
        existing = f.read()

    filler = b'{"timestamp":"2026-05-17T00:00:00Z","message":"filler-no-hmac"}\n' * 3500
    big_log_path = str(tmp_path / "big.log")
    with open(big_log_path, "wb") as f:
        f.write(filler)
        f.write(existing)

    seed, status = _restore_chain_tail(big_log_path)
    assert status == "resumed", f"Expected 'resumed', got '{status}'"
    assert len(seed) == 64, "HMAC should be a 64-char hex string"

    last_line = _read_log_lines(log_path)[-1]
    assert seed == last_line["integrity_hmac"]


# ---------------------------------------------------------------------------
# AUD-05 — Session shutdown idempotency + SIGTERM fall-through
# ---------------------------------------------------------------------------


def test_emit_session_shutdown_is_idempotent(monkeypatch, tmp_path):
    """AC-10.8 — emit_session_shutdown() must emit exactly once per process,
    regardless of how many times it's called or what reason argument is
    passed. The first caller wins; subsequent calls are no-ops.
    """
    from mcp_defectdojo import audit_logging

    log_path = str(tmp_path / "shutdown.log")
    hmac_key = b"shutdown-idempotency-key"
    monkeypatch.setenv("AUDIT_LOG_FILE", log_path)
    monkeypatch.setenv("AUDIT_HMAC_KEY", hmac_key.decode())
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    monkeypatch.setattr(audit_logging, "_session_shutdown_emitted", False)
    configure_logging()

    audit_logging.emit_session_shutdown("first")
    audit_logging.emit_session_shutdown("second")
    audit_logging.emit_session_shutdown("third")

    # PERF-03: file writes go through a QueueListener; drain it before
    # reading the file so all enqueued records have reached disk.
    audit_logging._stop_audit_queue_listener()
    logging.getLogger().handlers = []

    with open(log_path) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    shutdowns = [
        l for l in lines
        if l.get("message") == "Session shutdown"
        and l.get("event_type") == "lifecycle"
    ]
    assert len(shutdowns) == 1, f"Expected exactly 1 shutdown record, got {len(shutdowns)}"
    assert shutdowns[0]["shutdown_reason"] == "first"
    assert "session_summary" in shutdowns[0]


def test_sigterm_subprocess_emits_session_shutdown(tmp_path):
    """AC-10.8 — under SIGTERM (which bypasses the FastMCP lifespan
    finally: block), an atexit-registered emit_session_shutdown() still
    writes the canonical shutdown record before the process exits.
    """
    import signal
    import subprocess
    import sys

    if sys.platform == "win32":
        pytest.skip("SIGTERM behavior is POSIX-specific")

    log_path = str(tmp_path / "sigterm.log")
    hmac_key = "sigterm-test-key-0123456789abcdef0123456789abcdef0123"

    # Production servers (uvicorn/FastMCP) install a graceful SIGTERM handler
    # that triggers an orderly shutdown — which causes Python to run atexit.
    # Python's *default* SIGTERM handler skips atexit, so simulate the
    # production behavior with a tiny exit-on-SIGTERM trampoline.
    script = (
        "import atexit, logging, os, signal, sys, time\n"
        "from mcp_defectdojo.audit_logging import configure_logging, emit_session_shutdown, _stop_audit_queue_listener\n"
        "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
        "configure_logging()\n"
        # PERF-03: mirror server.py atexit ordering — register the queue-listener
        # stop FIRST so it runs AFTER emit_session_shutdown (atexit is LIFO).
        # emit_session_shutdown posts the shutdown record to the queue, then
        # _stop_audit_queue_listener drains the queue and stops the listener
        # so the record reaches the file before the process exits.
        "atexit.register(_stop_audit_queue_listener)\n"
        "atexit.register(emit_session_shutdown, 'atexit_fallback')\n"
        "logging.getLogger('sigterm.test').info('alive', extra={'event_type': 'audit'})\n"
        "sys.stdout.write('READY\\n'); sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )

    env = {
        **os.environ,
        "AUDIT_LOG_FILE": log_path,
        "AUDIT_HMAC_KEY": hmac_key,
        "LOG_LEVEL": "INFO",
    }
    env.pop("AUDIT_LOG_SYSLOG", None)
    env.pop("AUDIT_LOG_HTTPS_URL", None)

    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready_line = proc.stdout.readline()
        assert "READY" in ready_line, f"Subprocess didn't reach READY (got: {ready_line!r}, stderr: {proc.stderr.read()!r})"
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()

    with open(log_path) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    shutdowns = [
        l for l in lines
        if l.get("message") == "Session shutdown"
        and l.get("event_type") == "lifecycle"
    ]
    assert shutdowns, f"Expected a Session shutdown record after SIGTERM; got messages: {[l.get('message') for l in lines]}"
    last_shutdown = shutdowns[-1]
    assert last_shutdown["shutdown_reason"] == "atexit_fallback"
    assert "session_summary" in last_shutdown


# ---------------------------------------------------------------------------
# DOM-22 (Phase 14.2) — Fail-CLOSED on missing AUDIT_HMAC_KEY on network transport
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transport", ["sse", "streamable-http", "http"])
def test_audit_hmac_key_required_on_network_transport(monkeypatch, transport):
    """DOM-22: when running on a network transport (sse/streamable-http/http)
    without an AUDIT_HMAC_KEY and without REQUIRE_AUDIT_HMAC_KEY=false, the
    server fails to start. The chain HMAC must be persistent across restarts
    for tamper-evidence to hold; an ephemeral random key silently breaks the
    invariant on every restart.
    """
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("REQUIRE_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("AUDIT_LOG_FILE", raising=False)
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)
    monkeypatch.setenv("FASTMCP_TRANSPORT", transport)

    with pytest.raises(ValueError, match="AUDIT_HMAC_KEY"):
        configure_logging()

    logging.getLogger().handlers = []


def test_audit_hmac_key_opt_out_allows_missing_on_network_transport(monkeypatch):
    """DOM-22: REQUIRE_AUDIT_HMAC_KEY=false reproduces the legacy ephemeral-key
    behavior on a network transport. The explicit opt-out lets test deployments
    that don't care about cross-restart chain continuity continue to run.
    """
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("AUDIT_LOG_FILE", raising=False)
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)
    monkeypatch.setenv("FASTMCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("REQUIRE_AUDIT_HMAC_KEY", "false")

    # Should not raise.
    configure_logging()
    logging.getLogger().handlers = []


def test_audit_hmac_key_not_required_on_stdio_transport(monkeypatch):
    """DOM-22: stdio (and any non-network transport / unset transport) keep
    the legacy behavior — missing AUDIT_HMAC_KEY is a CRITICAL warning, not a
    startup failure."""
    monkeypatch.delenv("AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("REQUIRE_AUDIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("AUDIT_LOG_FILE", raising=False)
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)
    monkeypatch.delenv("FASTMCP_TRANSPORT", raising=False)

    # Should not raise — stdio transport keeps legacy behavior.
    configure_logging()
    logging.getLogger().handlers = []


# ---------------------------------------------------------------------------
# Audit queue overflow — _FailFastQueueHandler stderr fail-fast path
# ---------------------------------------------------------------------------


def test_audit_queue_overflow_emits_warning_to_stderr(monkeypatch, tmp_path, capsys):
    """When the audit file-handler queue is saturated, the
    `_FailFastQueueHandler` drops the newest record and writes a structured
    JSON warning to stderr describing the overflow. The warning bypasses the
    queue (no recursive re-entry) and identifies the dropped record's logger
    + level so operators can correlate it with the upstream cause.
    """
    from mcp_defectdojo.audit_logging import (
        configure_logging,
        _stop_audit_queue_listener,
    )

    log_path = tmp_path / "overflow.log"
    monkeypatch.setenv("AUDIT_LOG_FILE", str(log_path))
    monkeypatch.setenv("AUDIT_HMAC_KEY", "0" * 64)
    monkeypatch.setenv("REQUIRE_AUDIT_HMAC_KEY", "false")
    monkeypatch.setenv("AUDIT_LOG_QUEUE_SIZE", "1")
    monkeypatch.delenv("AUDIT_LOG_SYSLOG", raising=False)
    monkeypatch.delenv("AUDIT_LOG_HTTPS_URL", raising=False)

    try:
        # Stop the listener immediately so it does NOT drain the queue while
        # we are trying to overflow it. The QueueHandler still posts records,
        # but with the consumer halted the maxsize=1 queue saturates after
        # the first put_nowait succeeds.
        configure_logging()
        from mcp_defectdojo import audit_logging as _al
        if _al._audit_file_queue_listener is not None:
            try:
                _al._audit_file_queue_listener.stop()
            except Exception:
                pass

        lg = logging.getLogger("test.queue_overflow")
        for i in range(10):
            lg.info(f"hot loop record {i}", extra={"event_type": "audit"})

        err = capsys.readouterr().err

        overflow_events = []
        for raw in err.splitlines():
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if parsed.get("event_type") == "audit_queue_overflow":
                overflow_events.append(parsed)

        assert overflow_events, (
            f"Expected at least one audit_queue_overflow JSON event on stderr, "
            f"got:\n{err[:1200]}"
        )
        first = overflow_events[0]
        assert first.get("queue_size") == 1
        assert first.get("dropped_record_logger") == "test.queue_overflow"
        assert first.get("dropped_record_level") == "INFO"
    finally:
        _stop_audit_queue_listener()
        logging.getLogger().handlers = []

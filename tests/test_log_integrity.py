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
    _session_counter,
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

        logging.getLogger().handlers = []

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

        logging.getLogger().handlers = []

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

"""Tests for structured audit logging — JSON format, log levels, and sensitive data redaction."""
import io
import json
import logging

import pytest

from mcp_defectdojo.audit_logging import (
    RedactingFilter,
    StructuredJsonFormatter,
    configure_logging,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capturing_logger(name: str = "test") -> tuple[logging.Logger, io.StringIO]:
    """Return a logger wired to an in-memory StringIO stream.

    The root logger is intentionally *not* used here so that tests are
    isolated from each other and from ``configure_logging()`` side effects.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredJsonFormatter())
    handler.addFilter(RedactingFilter())

    logger = logging.getLogger(name)
    # Clear any handlers that a previous test may have attached.
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    return logger, buf


# ---------------------------------------------------------------------------
# AC-4.2 — Structured JSON format
# ---------------------------------------------------------------------------


def test_structured_json_format(monkeypatch, capsys):
    """configure_logging() must emit single-line JSON with the required fields."""
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    configure_logging()

    logging.getLogger("test.json_format").info("hello world")

    captured = capsys.readouterr().err
    # Find the relevant line (filter by logger name to be safe)
    lines = [l for l in captured.splitlines() if l.strip()]
    assert lines, "No log output captured on stderr"

    # The last line should be our message
    record = json.loads(lines[-1])
    assert "timestamp" in record
    assert "level" in record
    assert "logger" in record
    assert "message" in record


# ---------------------------------------------------------------------------
# AC-4.2 — Extra fields
# ---------------------------------------------------------------------------


def test_extra_fields_included():
    """Extra kwargs passed via ``extra=`` must appear as top-level JSON keys."""
    logger, buf = _make_capturing_logger("test.extra_fields")
    logger.info(
        "tool called",
        extra={"event_type": "tool_call", "tool_name": "list_products"},
    )

    record = json.loads(buf.getvalue().strip())
    assert record["event_type"] == "tool_call"
    assert record["tool_name"] == "list_products"


# ---------------------------------------------------------------------------
# AC-4.10 — DEBUG level enabled when LOG_LEVEL=DEBUG
# ---------------------------------------------------------------------------


def test_log_level_debug(monkeypatch, capsys):
    """When LOG_LEVEL=DEBUG, DEBUG-level records must appear in output."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()

    logging.getLogger("test.debug_level").debug("debug message here")

    captured = capsys.readouterr().err
    assert "debug message here" in captured


# ---------------------------------------------------------------------------
# AC-4.11 — WARNING level suppresses INFO
# ---------------------------------------------------------------------------


def test_log_level_warning_suppresses_info(monkeypatch, capsys):
    """When LOG_LEVEL=WARNING, INFO logs must be suppressed; WARNING must pass."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    configure_logging()

    logger = logging.getLogger("test.warning_suppress")
    logger.info("this should be hidden")

    captured_after_info = capsys.readouterr().err
    assert "this should be hidden" not in captured_after_info

    logger.warning("this should appear")
    captured_after_warning = capsys.readouterr().err
    assert "this should appear" in captured_after_warning


# ---------------------------------------------------------------------------
# AC-4.12 — Default level is INFO
# ---------------------------------------------------------------------------


def test_log_level_default_info(monkeypatch, capsys):
    """Without LOG_LEVEL set, DEBUG is suppressed and INFO is emitted."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging()

    logger = logging.getLogger("test.default_info")
    logger.debug("should not appear")
    logger.info("should appear")

    captured = capsys.readouterr().err
    assert "should not appear" not in captured
    assert "should appear" in captured


# ---------------------------------------------------------------------------
# AC-4.12 — Invalid LOG_LEVEL falls back to INFO
# ---------------------------------------------------------------------------


def test_log_level_invalid_falls_back(monkeypatch):
    """An unrecognised LOG_LEVEL value must fall back to INFO."""
    monkeypatch.setenv("LOG_LEVEL", "GARBAGE")
    configure_logging()

    root = logging.getLogger()
    assert root.level == logging.INFO


# ---------------------------------------------------------------------------
# AC-4.14 — DEFECTDOJO_API_KEY is redacted
# ---------------------------------------------------------------------------


def test_redaction_api_key(monkeypatch):
    """A log message containing the raw API key must have it replaced."""
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "secret-key-123")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    logger, buf = _make_capturing_logger("test.redact_api_key")
    logger.info("calling API with key secret-key-123 right now")

    output = buf.getvalue()
    assert "***REDACTED***" in output
    assert "secret-key-123" not in output


# ---------------------------------------------------------------------------
# AC-4.13 — Token auth header pattern is redacted
# ---------------------------------------------------------------------------


def test_redaction_auth_header(monkeypatch):
    """SEC-09 (Phase 14.2): the broadened `_TOKEN_PATTERN` redacts the
    `Token <opaque>` shape to the generic `[REDACTED]` marker. The exact
    marker string changed in Phase 14.2 (was `Token ***REDACTED***`) — the
    invariant the test pins is that the opaque token bytes never survive.
    """
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    logger, buf = _make_capturing_logger("test.redact_auth_header")
    logger.info("Authorization: Token abc123")

    output = buf.getvalue()
    assert "[REDACTED]" in output
    assert "abc123" not in output


# ---------------------------------------------------------------------------
# AC-4.14 — MCP_AUTH_TOKEN is redacted
# ---------------------------------------------------------------------------


def test_redaction_mcp_auth_token(monkeypatch):
    """A log message containing the raw MCP auth token must have it replaced."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "mcp-secret-456")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)

    logger, buf = _make_capturing_logger("test.redact_mcp_token")
    logger.info("token value is mcp-secret-456 in this message")

    output = buf.getvalue()
    assert "***REDACTED***" in output
    assert "mcp-secret-456" not in output


def test_redaction_dual_api_keys(monkeypatch):
    """Phase 5 secrets (dual API keys, read token) must be redacted."""
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-secret-789")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-secret-012")
    monkeypatch.setenv("MCP_READ_TOKEN", "mcp-read-token-345")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    logger, buf = _make_capturing_logger("test.redact_dual_keys")
    logger.info("keys: read-secret-789, write-secret-012, mcp-read-token-345")

    output = buf.getvalue()
    assert "read-secret-789" not in output
    assert "write-secret-012" not in output
    assert "mcp-read-token-345" not in output
    assert "***REDACTED***" in output


# ---------------------------------------------------------------------------
# AC-4.2 — Every output line must be valid JSON
# ---------------------------------------------------------------------------


def test_all_output_is_json(monkeypatch, capsys):
    """All lines emitted by configure_logging() must be parseable as JSON."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()

    logger = logging.getLogger("test.all_json")
    logger.debug("debug line")
    logger.info("info line")
    logger.warning("warning line")
    logger.error("error line")
    logger.critical("critical line")

    captured = capsys.readouterr().err
    non_empty_lines = [line for line in captured.splitlines() if line.strip()]

    assert len(non_empty_lines) >= 5, f"Expected at least 5 log lines, got {len(non_empty_lines)}"

    for line in non_empty_lines:
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Log line is not valid JSON: {line!r} — {exc}")

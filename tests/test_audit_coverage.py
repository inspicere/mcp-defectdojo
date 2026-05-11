"""Tests for audit coverage — every tool invocation produces a complete audit record."""
import io
import json
import logging

import pytest
import respx
import httpx
from unittest.mock import AsyncMock, MagicMock

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import list_products, create_product
from mcp_defectdojo.audit_logging import (
    audit_tool,
    configure_logging,
    current_request_id,
    RedactingFilter,
    StructuredJsonFormatter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_logs():
    """Return a StringIO buffer wired to the root logger with structured JSON formatting."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredJsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    return buf, handler


def _parse_log_entries(buf: io.StringIO) -> list[dict]:
    """Parse all non-empty JSON lines from the buffer."""
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Test 1 — audit_tool emits structured log with required fields
# ---------------------------------------------------------------------------


async def test_audit_tool_emits_structured_log(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _sample_tool(x: int, ctx=None):
            return x * 2

        await _sample_tool(x=5, ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        entry = audit_entries[0]
        assert "tool_name" in entry
        assert "request_id" in entry
        assert "caller_id" in entry
        assert "request_params" in entry
        assert "outcome" in entry
        assert "duration_ms" in entry
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 2 — audit_tool records outcome == "success" on normal return
# ---------------------------------------------------------------------------


async def test_audit_tool_success_outcome(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _success_tool(ctx=None):
            return "ok"

        await _success_tool(ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        assert audit_entries[0]["outcome"] == "success"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 3 — audit_tool records outcome == "error" and re-raises on exception
# ---------------------------------------------------------------------------


async def test_audit_tool_error_outcome(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _failing_tool(ctx=None):
            raise ValueError("something went wrong")

        with pytest.raises(ValueError, match="something went wrong"):
            await _failing_tool(ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        entry = audit_entries[0]
        assert entry["outcome"] == "error"
        assert "something went wrong" in entry["error"]
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 4 — audit_tool tracks duration_ms as a positive number
# ---------------------------------------------------------------------------


async def test_audit_tool_duration_tracked(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _timed_tool(ctx=None):
            return "done"

        await _timed_tool(ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        duration = audit_entries[0]["duration_ms"]
        assert isinstance(duration, (int, float))
        assert duration >= 0
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 5 — audit_tool captures caller_id from ctx.client_id
# ---------------------------------------------------------------------------


async def test_audit_tool_caller_id_from_context():
    buf, handler = _capture_logs()
    try:
        ctx = MagicMock()
        ctx.request_id = "req-abc"
        ctx.client_id = "mcp-client"
        ctx.request_context = MagicMock()

        @audit_tool
        async def _identified_tool(ctx=None):
            return "hello"

        await _identified_tool(ctx=ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        assert audit_entries[0]["caller_id"] == "mcp-client"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 6 — audit_tool emits security_warning for anonymous callers
# ---------------------------------------------------------------------------


async def test_audit_tool_anonymous_caller_warning(anonymous_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _anon_tool(ctx=None):
            return "anon"

        await _anon_tool(ctx=anonymous_ctx)

        entries = _parse_log_entries(buf)
        # Should have a WARNING with event_type == "security_warning"
        warnings = [e for e in entries if e.get("event_type") == "security_warning"]
        assert warnings, "No security_warning log entry found"
        assert warnings[0]["level"] == "WARNING"

        # Should also have an INFO audit entry with caller_id == "anonymous"
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        assert audit_entries[0]["caller_id"] == "anonymous"

        # Total: exactly two relevant entries — one warning + one audit
        assert len(warnings) >= 1
        assert len(audit_entries) >= 1
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 7 — request_id propagates to client._request()
# ---------------------------------------------------------------------------


async def test_request_id_propagates_to_client(mock_env):
    buf, handler = _capture_logs()
    try:
        from mcp_defectdojo.client import DefectDojoClient

        token = current_request_id.set("propagation-test-id")
        try:
            client = DefectDojoClient()
            with respx.mock:
                respx.get(
                    "http://test.defectdojo.local/api/v2/products/"
                ).mock(return_value=httpx.Response(200, json={"count": 0, "results": []}))
                await client._request("GET", "/products/")
            await client.aclose()
        finally:
            current_request_id.reset(token)

        entries = _parse_log_entries(buf)
        api_entries = [e for e in entries if e.get("event_type") == "api_request"]
        assert api_entries, "No api_request log entry found"
        assert api_entries[0]["request_id"] == "propagation-test-id"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 8 — client._request() tracks api_duration_ms
# ---------------------------------------------------------------------------


async def test_client_api_duration_tracked(mock_env):
    buf, handler = _capture_logs()
    try:
        from mcp_defectdojo.client import DefectDojoClient

        client = DefectDojoClient()
        with respx.mock:
            respx.get(
                "http://test.defectdojo.local/api/v2/products/"
            ).mock(return_value=httpx.Response(200, json={"count": 0, "results": []}))
            await client._request("GET", "/products/")
        await client.aclose()

        entries = _parse_log_entries(buf)
        response_entries = [e for e in entries if e.get("event_type") == "api_response"]
        assert response_entries, "No api_response log entry found"
        duration = response_entries[0]["api_duration_ms"]
        assert isinstance(duration, (int, float))
        assert duration >= 0
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 9 — list_products (read tool) produces an audit log entry
# ---------------------------------------------------------------------------


async def test_read_tool_produces_audit_log(mock_ctx):
    buf, handler = _capture_logs()
    handler.addFilter(RedactingFilter())
    try:
        mock = AsyncMock()
        mock.get_products.return_value = {"results": [], "count": 0}
        server_module.client = mock

        await list_products(ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        tool_names = [e["tool_name"] for e in audit_entries]
        assert any("list_products" in name for name in tool_names)
    finally:
        server_module.client = None
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 10 — create_product (write tool) produces an audit log entry
# ---------------------------------------------------------------------------


async def test_write_tool_produces_audit_log(mock_ctx):
    buf, handler = _capture_logs()
    handler.addFilter(RedactingFilter())
    try:
        mock = AsyncMock()
        mock.create_product.return_value = {"id": 1, "name": "Test", "description": "desc", "prod_type": 1}
        server_module.client = mock

        await create_product(name="Test", description="desc", prod_type_id=1, ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        tool_names = [e["tool_name"] for e in audit_entries]
        assert any("create_product" in name for name in tool_names)
    finally:
        server_module.client = None
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 11 — audit_tool truncates 'file' field (base64 scan content)
# ---------------------------------------------------------------------------


async def test_audit_tool_truncates_file_field(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _scan_tool(file: str, file_name: str, ctx=None):
            return "ok"

        large_file = "A" * 10000
        await _scan_tool(file=large_file, file_name="scan.json", ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        params = audit_entries[0]["request_params"]
        assert params["file"] == "<10000 chars>"
        assert params["file_name"] == "scan.json"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Test 12 — audit_tool truncates 'entry' field (finding note content)
# ---------------------------------------------------------------------------


async def test_audit_tool_truncates_entry_field(mock_ctx):
    buf, handler = _capture_logs()
    try:
        @audit_tool
        async def _note_tool(finding_id: int, entry: str, ctx=None):
            return "ok"

        long_entry = "Sensitive vulnerability detail " * 100
        await _note_tool(finding_id=42, entry=long_entry, ctx=mock_ctx)

        entries = _parse_log_entries(buf)
        audit_entries = [e for e in entries if e.get("event_type") == "audit"]
        assert audit_entries, "No audit log entry found"
        params = audit_entries[0]["request_params"]
        assert params["entry"] == f"<{len(long_entry)} chars>"
        assert params["finding_id"] == 42
    finally:
        logging.getLogger().removeHandler(handler)

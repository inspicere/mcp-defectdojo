"""Tests targeting uncovered lines to push coverage to 100%."""
import base64
import json
import logging
import os
import queue
import time
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.audit_logging import (
    StructuredJsonFormatter,
    HTTPSLogHandler,
    SyslogForwardHandler,
    audit_tool,
    configure_logging,
)
from mcp_defectdojo.security import MutationRateLimiter
from mcp_defectdojo.server import (
    _caller_id,
    _validate_scan_params,
    close_finding,
    create_engagement,
    create_product,
    create_test,
    get_engagement,
    get_finding,
    get_test,
    import_scan,
    list_finding_notes,
    reimport_scan,
    update_finding,
)


# ---------------------------------------------------------------------------
# StructuredJsonFormatter — exception and stack_info (lines 56, 58)
# ---------------------------------------------------------------------------


def test_structured_json_formatter_exception():
    formatter = StructuredJsonFormatter()
    logger = logging.getLogger("test.exception")
    logger.handlers = []
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    try:
        raise ValueError("test error")
    except ValueError:
        logger.exception("caught it")
    record = logging.LogRecord(
        "test", logging.ERROR, "", 0, "msg", (), None,
    )
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys
        record.exc_info = sys.exc_info()
    data = formatter._build_data(record)
    assert "exception" in data
    assert any("RuntimeError" in line for line in data["exception"])


def test_structured_json_formatter_stack_info():
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        "test", logging.INFO, "", 0, "msg", (), None,
    )
    record.stack_info = "Stack trace here"
    data = formatter._build_data(record)
    assert data["stack_info"] == "Stack trace here"


# ---------------------------------------------------------------------------
# SyslogForwardHandler — socket close OSError (lines 190-191)
# ---------------------------------------------------------------------------


def test_syslog_handler_close_sock_oserror():
    handler = SyslogForwardHandler.__new__(SyslogForwardHandler)
    mock_sock = MagicMock()
    mock_sock.close.side_effect = OSError("close failed")
    handler._sock = mock_sock
    handler._close_sock()
    assert handler._sock is None
    mock_sock.close.assert_called_once()


# ---------------------------------------------------------------------------
# SyslogForwardHandler — worker drain exception (lines 251-252)
# ---------------------------------------------------------------------------


def test_syslog_worker_drain_exception():
    handler = SyslogForwardHandler.__new__(SyslogForwardHandler)
    handler._shutdown = MagicMock()
    handler._shutdown.is_set.side_effect = [True]
    handler._queue = queue.Queue()
    handler._queue.put("test line")
    handler._send = MagicMock(side_effect=Exception("send failed"))
    handler._worker()


# ---------------------------------------------------------------------------
# HTTPSLogHandler — invalid URL scheme (line 273)
# ---------------------------------------------------------------------------


def test_https_handler_invalid_scheme():
    with pytest.raises(ValueError, match="must use https"):
        HTTPSLogHandler("ftp://example.com/logs")


# ---------------------------------------------------------------------------
# HTTPSLogHandler — http:// warning (line 275)
# ---------------------------------------------------------------------------


def test_https_handler_http_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        handler = HTTPSLogHandler("http://example.com/logs")
        handler._shutdown.set()
        handler._thread.join(timeout=2)
        handler.close()
    assert any("unencrypted" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# HTTPSLogHandler — shutdown drain (lines 311-314)
# ---------------------------------------------------------------------------


def test_https_handler_shutdown_drain():
    handler = HTTPSLogHandler("https://example.com/logs", batch_size=1000, flush_interval=300)
    flushed = []
    handler._flush = lambda batch: flushed.extend(batch)
    for i in range(5):
        handler._queue.put(json.dumps({"msg": f"item-{i}"}))
    handler._shutdown.set()
    handler._thread.join(timeout=5)
    assert len(flushed) == 5


def test_https_handler_drain_race_condition():
    handler = HTTPSLogHandler("https://example.com/logs", batch_size=1000, flush_interval=300)
    handler._shutdown.set()
    handler._thread.join(timeout=5)
    flushed = []
    handler._flush = lambda batch: flushed.extend(batch)
    call_count = [0]
    original_empty = handler._queue.empty
    def fake_empty():
        call_count[0] += 1
        if call_count[0] == 1:
            return False
        return True
    handler._queue.empty = fake_empty
    handler._queue.get_nowait = MagicMock(side_effect=queue.Empty)
    handler._worker()


# ---------------------------------------------------------------------------
# audit_tool — ctx.request_id and ctx.client_id errors (lines 376-377, 383-384)
# ---------------------------------------------------------------------------


async def test_audit_tool_ctx_request_id_error():
    @audit_tool
    async def dummy_tool(ctx=None):
        return "ok"

    class BrokenRequestCtx:
        @property
        def request_id(self):
            raise RuntimeError("no request")
        client_id = "valid-caller"

    result = await dummy_tool(ctx=BrokenRequestCtx())
    assert result == "ok"


async def test_audit_tool_ctx_client_id_error():
    @audit_tool
    async def dummy_tool2(ctx=None):
        return "ok"

    class BrokenClientCtx:
        request_id = "valid-request-id"
        @property
        def client_id(self):
            raise AttributeError("no client")

    result = await dummy_tool2(ctx=BrokenClientCtx())
    assert result == "ok"


# ---------------------------------------------------------------------------
# configure_logging — AUDIT_HMAC_KEY from env (line 441)
# ---------------------------------------------------------------------------


def test_configure_logging_with_hmac_key(monkeypatch):
    monkeypatch.setenv("AUDIT_HMAC_KEY", "a" * 64)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.WARNING


# ---------------------------------------------------------------------------
# client.py — generic httpx.HTTPError in _request and _multipart_request
# (lines 131-133, 332-334)
# ---------------------------------------------------------------------------


async def test_client_request_generic_http_error(mock_env):
    import httpx
    from mcp_defectdojo.client import DefectDojoClient
    from mcp_defectdojo.audit_logging import current_request_id
    current_request_id.set("test-req")
    client = DefectDojoClient()
    with patch.object(client._read_client, "request", side_effect=httpx.HTTPError("generic")):
        with pytest.raises(RuntimeError, match="request failed"):
            await client._request("GET", "/test/")
    await client.aclose()


async def test_client_multipart_generic_http_error(mock_env):
    import httpx
    from mcp_defectdojo.client import DefectDojoClient
    from mcp_defectdojo.audit_logging import current_request_id
    current_request_id.set("test-req")
    client = DefectDojoClient()
    with patch.object(client._write_client, "post", side_effect=httpx.HTTPError("generic")):
        with pytest.raises(RuntimeError, match="request failed"):
            await client._multipart_request("/test/", data={}, files={})
    await client.aclose()


# ---------------------------------------------------------------------------
# security.py — stale caller eviction (line 53)
# ---------------------------------------------------------------------------


async def test_rate_limiter_evicts_stale_callers():
    limiter = MutationRateLimiter(max_mutations=10, window_seconds=1)
    await limiter.check("caller-a")
    await limiter.check("caller-b")
    assert "caller-a" in limiter._windows
    assert "caller-b" in limiter._windows
    limiter._last_cleanup = 0.0
    limiter._windows["caller-a"].clear()
    limiter._windows["caller-b"].clear()
    await limiter.check("caller-c")
    assert "caller-a" not in limiter._windows
    assert "caller-b" not in limiter._windows
    assert "caller-c" in limiter._windows


# ---------------------------------------------------------------------------
# server.py — _caller_id RuntimeError fallback (lines 138-139)
# ---------------------------------------------------------------------------


def test_caller_id_runtime_error():
    class BrokenCtx:
        @property
        def client_id(self):
            raise RuntimeError("no context")
    assert _caller_id(BrokenCtx()) == "anonymous"


def test_caller_id_attribute_error():
    class NoClientId:
        pass
    assert _caller_id(NoClientId()) == "anonymous"


# ---------------------------------------------------------------------------
# server.py — validation edge cases
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


async def test_create_product_invalid_prod_type(patched_client):
    with pytest.raises(ToolError, match="prod_type_id must be > 0"):
        await create_product(name="X", description="Y", prod_type_id=0)


async def test_create_test_invalid_engagement_id(patched_client):
    with pytest.raises(ToolError, match="engagement_id must be > 0"):
        await create_test(engagement_id=0, test_type_id=1, target_start="2026-01-01", target_end="2026-12-31")


async def test_update_finding_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await update_finding(finding_id=0, title="X")


async def test_get_engagement_invalid_id(patched_client):
    with pytest.raises(ToolError, match="engagement_id must be > 0"):
        await get_engagement(engagement_id=-1)


async def test_create_engagement_invalid_product_id(patched_client):
    with pytest.raises(ToolError, match="product_id must be > 0"):
        await create_engagement(product_id=0, name="X", target_start="2026-01-01", target_end="2026-12-31")


async def test_get_test_invalid_id(patched_client):
    with pytest.raises(ToolError, match="test_id must be > 0"):
        await get_test(test_id=-5)


async def test_create_test_invalid_test_type(patched_client):
    with pytest.raises(ToolError, match="test_type_id must be > 0"):
        await create_test(engagement_id=1, test_type_id=0, target_start="2026-01-01", target_end="2026-12-31")


async def test_get_finding_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await get_finding(finding_id=0)


async def test_update_finding_invalid_severity(patched_client):
    with pytest.raises(ToolError, match="severity must be one of"):
        await update_finding(finding_id=1, severity="Bogus")


async def test_update_finding_long_description(patched_client):
    with pytest.raises(ToolError, match="description"):
        await update_finding(finding_id=1, description="x" * 50000)


# ---------------------------------------------------------------------------
# server.py — _validate_scan_params edges (lines 458, 460)
# ---------------------------------------------------------------------------


def test_decode_file_empty_after_decode():
    from mcp_defectdojo.server import _decode_file
    with pytest.raises(ToolError, match="decoded to empty content"):
        # Patch b64decode to return empty bytes after passing the "not empty" input check
        with patch("mcp_defectdojo.server.base64.b64decode", return_value=b""):
            _decode_file("notempty")


def test_decode_file_exceeds_max_size():
    from mcp_defectdojo.server import _decode_file, MAX_FILE_SIZE
    big_content = base64.b64encode(b"x" * (MAX_FILE_SIZE + 1)).decode()
    with pytest.raises(ToolError, match="exceeds maximum size"):
        _decode_file(big_content)


def test_validate_scan_params_invalid_severity():
    with pytest.raises(ToolError, match="minimum_severity must be one of"):
        _validate_scan_params(
            scan_type="Test", file_name="f.json", minimum_severity="Bogus",
            version=None, branch_tag=None, commit_hash=None, build_id=None,
            group_by=None, product_name=None, engagement_name=None,
            product_type_name=None,
        )


def test_validate_scan_params_long_version():
    with pytest.raises(ToolError, match="version"):
        _validate_scan_params(
            scan_type="Test", file_name="f.json", minimum_severity=None,
            version="x" * 200, branch_tag=None, commit_hash=None, build_id=None,
            group_by=None, product_name=None, engagement_name=None,
            product_type_name=None,
        )


# ---------------------------------------------------------------------------
# server.py — close_finding note failure path (lines 526-529)
# ---------------------------------------------------------------------------


async def test_close_finding_note_failure(patched_client, sample_finding):
    closed = dict(sample_finding, active=False, is_mitigated=True)
    patched_client.close_finding.return_value = closed
    patched_client.add_finding_note.side_effect = RuntimeError("note failed")
    result = await close_finding(finding_id=1, reason="mitigated", note="closure note")
    data = json.loads(result)
    assert "_warning" in data
    assert "note failed" in data["_warning"]


# ---------------------------------------------------------------------------
# server.py — list_finding_notes ValidationError (lines 644-645)
# ---------------------------------------------------------------------------


async def test_list_finding_notes_validation_error(patched_client):
    patched_client.get_finding_notes.return_value = [{"bad": "data"}]
    with pytest.raises(ToolError, match="Invalid API response"):
        await list_finding_notes(finding_id=1)


# ---------------------------------------------------------------------------
# server.py — reimport_scan test_id validation (line 785)
# ---------------------------------------------------------------------------


async def test_reimport_scan_invalid_test_id(patched_client):
    file_b64 = base64.b64encode(b"test content").decode()
    with pytest.raises(ToolError, match="test_id must be > 0"):
        await reimport_scan(
            scan_type="Test", file=file_b64, file_name="f.json", test_id=-1,
        )

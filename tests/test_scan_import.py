"""Tests for import_scan and reimport_scan tools."""
import base64
import json
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import import_scan, reimport_scan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SCAN_CONTENT = b'{"results": [], "version": "1.0"}'
SAMPLE_SCAN_B64 = base64.b64encode(SAMPLE_SCAN_CONTENT).decode()

SAMPLE_IMPORT_RESPONSE = {
    "test": 42,
    "test_id": 42,
    "findings_affected": 5,
    "scan_type": "Semgrep JSON Report",
}


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


# ---------------------------------------------------------------------------
# Null guard tests
# ---------------------------------------------------------------------------


async def test_import_scan_null_guard():
    """import_scan raises ToolError when client is None."""
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


async def test_reimport_scan_null_guard():
    """reimport_scan raises ToolError when client is None."""
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


# ---------------------------------------------------------------------------
# Validation tests — scan_type
# ---------------------------------------------------------------------------


async def test_import_scan_empty_scan_type(patched_client):
    with pytest.raises(ToolError, match="scan_type"):
        await import_scan(
            scan_type="",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


async def test_import_scan_whitespace_scan_type(patched_client):
    with pytest.raises(ToolError, match="scan_type must not be empty"):
        await import_scan(
            scan_type="   ",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


async def test_reimport_scan_empty_scan_type(patched_client):
    with pytest.raises(ToolError, match="scan_type"):
        await reimport_scan(
            scan_type="",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


# ---------------------------------------------------------------------------
# Validation tests — file
# ---------------------------------------------------------------------------


async def test_import_scan_empty_file(patched_client):
    with pytest.raises(ToolError, match="file must not be empty"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file="",
            file_name="report.json",
        )


async def test_import_scan_invalid_base64(patched_client):
    with pytest.raises(ToolError, match="valid base64"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file="not-valid-base64!!!",
            file_name="report.json",
        )


async def test_reimport_scan_empty_file(patched_client):
    with pytest.raises(ToolError, match="file must not be empty"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file="",
            file_name="report.json",
        )


async def test_reimport_scan_invalid_base64(patched_client):
    with pytest.raises(ToolError, match="valid base64"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file="not-valid-base64!!!",
            file_name="report.json",
        )


# ---------------------------------------------------------------------------
# Validation tests — file_name
# ---------------------------------------------------------------------------


async def test_import_scan_empty_file_name(patched_client):
    with pytest.raises(ToolError, match="file_name must not be empty"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="",
        )


# ---------------------------------------------------------------------------
# Validation tests — minimum_severity
# ---------------------------------------------------------------------------


async def test_import_scan_invalid_minimum_severity(patched_client):
    with pytest.raises(ToolError, match="minimum_severity"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
            minimum_severity="NotASeverity",
        )


async def test_reimport_scan_invalid_minimum_severity(patched_client):
    with pytest.raises(ToolError, match="minimum_severity"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
            minimum_severity="NotASeverity",
        )


# ---------------------------------------------------------------------------
# Validation tests — test_id (reimport only)
# ---------------------------------------------------------------------------


async def test_reimport_scan_zero_test_id(patched_client):
    with pytest.raises(ToolError, match="test_id must be > 0"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
            test_id=0,
        )


async def test_reimport_scan_negative_test_id(patched_client):
    with pytest.raises(ToolError, match="test_id must be > 0"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
            test_id=-1,
        )


# ---------------------------------------------------------------------------
# RuntimeError propagation
# ---------------------------------------------------------------------------


async def test_import_scan_catches_runtime_error(patched_client):
    patched_client.import_scan.side_effect = RuntimeError("DefectDojo API Error 400: bad request")
    with pytest.raises(ToolError, match="400"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


async def test_reimport_scan_catches_runtime_error(patched_client):
    patched_client.reimport_scan.side_effect = RuntimeError("DefectDojo API Error 400: bad request")
    with pytest.raises(ToolError, match="400"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_import_scan_rate_limited(patched_client):
    """import_scan enforces mutation rate limiting (open-access tier under test)."""
    from mcp_defectdojo.security import MutationRateLimiter
    server_module._open_access_limiter = MutationRateLimiter(max_mutations=1, window_seconds=60)

    patched_client.import_scan.return_value = SAMPLE_IMPORT_RESPONSE

    # First call succeeds
    await import_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
    )

    # Second call hits rate limit
    with pytest.raises(ToolError, match="Rate limit"):
        await import_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


async def test_reimport_scan_rate_limited(patched_client):
    """reimport_scan enforces mutation rate limiting (open-access tier under test)."""
    from mcp_defectdojo.security import MutationRateLimiter
    server_module._open_access_limiter = MutationRateLimiter(max_mutations=1, window_seconds=60)

    patched_client.reimport_scan.return_value = SAMPLE_IMPORT_RESPONSE

    # First call succeeds
    await reimport_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
    )

    # Second call hits rate limit
    with pytest.raises(ToolError, match="Rate limit"):
        await reimport_scan(
            scan_type="Semgrep JSON Report",
            file=SAMPLE_SCAN_B64,
            file_name="report.json",
        )


# ---------------------------------------------------------------------------
# Happy path — import_scan with minimal params
# ---------------------------------------------------------------------------


async def test_import_scan_minimal(patched_client):
    """import_scan with only required params succeeds."""
    patched_client.import_scan.return_value = SAMPLE_IMPORT_RESPONSE

    result = await import_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
    )

    data = json.loads(result)
    assert data["test"] == 42
    assert data["findings_affected"] == 5
    assert data["scan_type"] == "Semgrep JSON Report"

    # Verify client was called with correct args
    call_kwargs = patched_client.import_scan.call_args.kwargs
    assert call_kwargs["scan_type"] == "Semgrep JSON Report"
    assert call_kwargs["file"] == SAMPLE_SCAN_CONTENT
    assert call_kwargs["file_name"] == "report.json"
    assert call_kwargs["auto_create_context"] is True
    assert call_kwargs["close_old_findings"] is True
    assert call_kwargs["active"] is True
    assert call_kwargs["verified"] is False


# ---------------------------------------------------------------------------
# Happy path — import_scan with optional params
# ---------------------------------------------------------------------------


async def test_import_scan_with_optional_params(patched_client):
    """import_scan passes optional params through to client."""
    patched_client.import_scan.return_value = SAMPLE_IMPORT_RESPONSE

    result = await import_scan(
        scan_type="Trivy Scan",
        file=SAMPLE_SCAN_B64,
        file_name="trivy-results.json",
        product_name="My Product",
        engagement_name="CI Scan",
        version="1.2.3",
        branch_tag="main",
        commit_hash="abc123def456",
        build_id="build-42",
        tags=["ci", "nightly"],
        minimum_severity="Medium",
        group_by="component_name+component_version",
    )

    data = json.loads(result)
    assert data["test"] == 42

    call_kwargs = patched_client.import_scan.call_args.kwargs
    assert call_kwargs["product_name"] == "My Product"
    assert call_kwargs["engagement_name"] == "CI Scan"
    assert call_kwargs["version"] == "1.2.3"
    assert call_kwargs["branch_tag"] == "main"
    assert call_kwargs["commit_hash"] == "abc123def456"
    assert call_kwargs["build_id"] == "build-42"
    assert call_kwargs["tags"] == ["ci", "nightly"]
    assert call_kwargs["minimum_severity"] == "Medium"
    assert call_kwargs["group_by"] == "component_name+component_version"


# ---------------------------------------------------------------------------
# Happy path — reimport_scan with test_id
# ---------------------------------------------------------------------------


async def test_reimport_scan_with_test_id(patched_client):
    """reimport_scan with test_id passes it through."""
    patched_client.reimport_scan.return_value = SAMPLE_IMPORT_RESPONSE

    result = await reimport_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
        test_id=42,
        do_not_reactivate=True,
    )

    data = json.loads(result)
    assert data["test"] == 42

    call_kwargs = patched_client.reimport_scan.call_args.kwargs
    assert call_kwargs["test_id"] == 42
    assert call_kwargs["do_not_reactivate"] is True


async def test_reimport_scan_minimal(patched_client):
    """reimport_scan with only required params succeeds."""
    patched_client.reimport_scan.return_value = SAMPLE_IMPORT_RESPONSE

    result = await reimport_scan(
        scan_type="ZAP Scan",
        file=SAMPLE_SCAN_B64,
        file_name="zap-report.xml",
    )

    data = json.loads(result)
    assert data["test"] == 42
    assert data["scan_type"] == "Semgrep JSON Report"  # from mock response

    call_kwargs = patched_client.reimport_scan.call_args.kwargs
    assert call_kwargs["scan_type"] == "ZAP Scan"
    assert call_kwargs["file"] == SAMPLE_SCAN_CONTENT
    assert call_kwargs["file_name"] == "zap-report.xml"
    assert call_kwargs["test_id"] is None
    assert call_kwargs["do_not_reactivate"] is False


# ---------------------------------------------------------------------------
# Multipart form data construction (client level)
# ---------------------------------------------------------------------------


async def test_import_scan_client_calls_multipart(patched_client):
    """import_scan tool decodes base64 and passes bytes to client."""
    patched_client.import_scan.return_value = SAMPLE_IMPORT_RESPONSE

    await import_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
    )

    call_kwargs = patched_client.import_scan.call_args.kwargs
    # file should be bytes, not base64 string
    assert isinstance(call_kwargs["file"], bytes)
    assert call_kwargs["file"] == SAMPLE_SCAN_CONTENT


async def test_reimport_scan_client_calls_multipart(patched_client):
    """reimport_scan tool decodes base64 and passes bytes to client."""
    patched_client.reimport_scan.return_value = SAMPLE_IMPORT_RESPONSE

    await reimport_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
    )

    call_kwargs = patched_client.reimport_scan.call_args.kwargs
    assert isinstance(call_kwargs["file"], bytes)
    assert call_kwargs["file"] == SAMPLE_SCAN_CONTENT


# ---------------------------------------------------------------------------
# Valid minimum_severity values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["Critical", "High", "Medium", "Low", "Info"])
async def test_import_scan_valid_minimum_severities(patched_client, severity):
    """All valid severity values are accepted for minimum_severity."""
    patched_client.import_scan.return_value = SAMPLE_IMPORT_RESPONSE

    result = await import_scan(
        scan_type="Semgrep JSON Report",
        file=SAMPLE_SCAN_B64,
        file_name="report.json",
        minimum_severity=severity,
    )

    data = json.loads(result)
    assert data["test"] == 42
    call_kwargs = patched_client.import_scan.call_args.kwargs
    assert call_kwargs["minimum_severity"] == severity

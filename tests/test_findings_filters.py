"""Tests for list_findings rich filtering — product, engagement, severity, boolean flags, tags, and text search."""
import json
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import list_findings
from tests.conftest import paginated_response


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


@pytest.fixture
def sample_finding():
    return {
        "id": 1,
        "test": 4,
        "title": "XSS Vuln",
        "severity": "High",
        "description": "Found XSS",
        "active": True,
        "verified": False,
        "mitigated": None,
        "is_mitigated": False,
        "out_of_scope": False,
        "false_p": False,
        "duplicate": False,
    }


# ---------------------------------------------------------------------------
# Filter tests — verify correct query params are forwarded
# ---------------------------------------------------------------------------


async def test_list_findings_by_product(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(product_id=5)
    data = json.loads(result)
    assert len(data["items"]) == 1
    patched_client.get_findings.assert_called_once()
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["product_id"] == 5
    assert call_kwargs["test_id"] is None


async def test_list_findings_by_engagement(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(engagement_id=10)
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["engagement_id"] == 10


async def test_list_findings_by_severity(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(severity="Critical")
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["severity"] == "Critical"


async def test_list_findings_active_only(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(active=True)
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["active"] is True


async def test_list_findings_inactive(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(active=False)
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["active"] is False


async def test_list_findings_by_tags(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(tags=["web", "critical"])
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["tags"] == ["web", "critical"]


async def test_list_findings_sla_breach(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(outside_of_sla=True)
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["outside_of_sla"] is True


async def test_list_findings_by_component(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(component_name="openssl")
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["component_name"] == "openssl"


async def test_list_findings_by_title(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(title="XSS")
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["title"] == "XSS"


async def test_list_findings_combined_filters(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(
        product_id=3,
        severity="High",
        active=True,
        verified=False,
        tags=["web"],
        limit=10,
        offset=5,
    )
    data = json.loads(result)
    assert len(data["items"]) == 1
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["product_id"] == 3
    assert call_kwargs["severity"] == "High"
    assert call_kwargs["active"] is True
    assert call_kwargs["verified"] is False
    assert call_kwargs["tags"] == ["web"]
    assert call_kwargs["limit"] == 10
    assert call_kwargs["offset"] == 5


# ---------------------------------------------------------------------------
# Validation error tests
# ---------------------------------------------------------------------------


async def test_list_findings_invalid_severity(patched_client):
    with pytest.raises(ToolError, match="severity"):
        await list_findings(severity="SuperBad")


async def test_list_findings_invalid_product_id(patched_client):
    with pytest.raises(ToolError, match="product_id must be > 0"):
        await list_findings(product_id=0)


async def test_list_findings_invalid_engagement_id(patched_client):
    with pytest.raises(ToolError, match="engagement_id must be > 0"):
        await list_findings(engagement_id=-1)


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


async def test_list_findings_backwards_compatible(patched_client, sample_finding):
    """Existing call pattern with just test_id still works."""
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(test_id=4, limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert "pagination" in data
    call_kwargs = patched_client.get_findings.call_args.kwargs
    assert call_kwargs["test_id"] == 4
    assert call_kwargs["limit"] == 20
    assert call_kwargs["offset"] == 0
    # All other filters should be None
    assert call_kwargs["product_id"] is None
    assert call_kwargs["severity"] is None
    assert call_kwargs["active"] is None

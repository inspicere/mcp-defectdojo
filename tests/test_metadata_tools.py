"""Tests for metadata lookup tools — list_product_types and list_test_types."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import list_product_types, list_test_types
from tests.conftest import paginated_response

BASE = "http://test.defectdojo.local/api/v2"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


@pytest.fixture
def sample_product_type():
    return {
        "id": 1,
        "name": "Research and Development",
        "description": "R&D products",
        "critical_product": False,
        "key_product": True,
    }


@pytest.fixture
def sample_test_type():
    return {"id": 1, "name": "Semgrep JSON Report", "tags": []}


# ---------------------------------------------------------------------------
# list_product_types tests
# ---------------------------------------------------------------------------


async def test_list_product_types_default(patched_client, sample_product_type):
    """Default call returns paginated list of product types."""
    patched_client.get_product_types.return_value = paginated_response(
        [sample_product_type]
    )
    result = await list_product_types(limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == 1
    assert data["items"][0]["name"] == "Research and Development"
    assert data["items"][0]["key_product"] is True
    assert "pagination" in data
    assert data["pagination"]["count"] == 1
    patched_client.get_product_types.assert_called_once_with(limit=20, offset=0)


async def test_list_product_types_pagination(patched_client, sample_product_type):
    """Custom limit and offset are forwarded to the client."""
    patched_client.get_product_types.return_value = paginated_response(
        [sample_product_type], count=50
    )
    result = await list_product_types(limit=5, offset=10)
    data = json.loads(result)
    assert data["pagination"]["offset"] == 10
    assert data["pagination"]["limit"] == 5
    assert data["pagination"]["has_next"] is True
    patched_client.get_product_types.assert_called_once_with(limit=5, offset=10)


async def test_list_product_types_invalid_limit(patched_client):
    """Limit out of range raises ToolError."""
    with pytest.raises(ToolError, match="limit"):
        await list_product_types(limit=200)


async def test_list_product_types_invalid_limit_zero(patched_client):
    """Limit of zero raises ToolError."""
    with pytest.raises(ToolError, match="limit"):
        await list_product_types(limit=0)


async def test_list_product_types_negative_offset(patched_client):
    """Negative offset raises ToolError."""
    with pytest.raises(ToolError, match="offset"):
        await list_product_types(offset=-1)


async def test_list_product_types_runtime_error(patched_client):
    """RuntimeError from client is caught and raised as ToolError."""
    patched_client.get_product_types.side_effect = RuntimeError(
        "DefectDojo API Error 500: internal"
    )
    with pytest.raises(ToolError, match="500"):
        await list_product_types()


async def test_list_product_types_null_guard():
    """Raises ToolError when client is None."""
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await list_product_types()


# ---------------------------------------------------------------------------
# list_test_types tests
# ---------------------------------------------------------------------------


async def test_list_test_types_default(patched_client, sample_test_type):
    """Default call returns paginated list of test types."""
    patched_client.get_test_types.return_value = paginated_response(
        [sample_test_type]
    )
    result = await list_test_types(limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == 1
    assert data["items"][0]["name"] == "Semgrep JSON Report"
    # F-002: tags returned on the read path are wrapped in the envelope.
    assert data["items"][0]["tags"]["value"] == []
    assert "pagination" in data
    assert data["pagination"]["count"] == 1
    patched_client.get_test_types.assert_called_once_with(limit=20, offset=0)


async def test_list_test_types_pagination(patched_client, sample_test_type):
    """Custom limit and offset are forwarded to the client."""
    patched_client.get_test_types.return_value = paginated_response(
        [sample_test_type], count=100
    )
    result = await list_test_types(limit=10, offset=20)
    data = json.loads(result)
    assert data["pagination"]["offset"] == 20
    assert data["pagination"]["limit"] == 10
    assert data["pagination"]["has_next"] is True
    patched_client.get_test_types.assert_called_once_with(limit=10, offset=20)


async def test_list_test_types_invalid_limit(patched_client):
    """Limit out of range raises ToolError."""
    with pytest.raises(ToolError, match="limit"):
        await list_test_types(limit=101)


async def test_list_test_types_invalid_limit_zero(patched_client):
    """Limit of zero raises ToolError."""
    with pytest.raises(ToolError, match="limit"):
        await list_test_types(limit=0)


async def test_list_test_types_negative_offset(patched_client):
    """Negative offset raises ToolError."""
    with pytest.raises(ToolError, match="offset"):
        await list_test_types(offset=-5)


async def test_list_test_types_runtime_error(patched_client):
    """RuntimeError from client is caught and raised as ToolError."""
    patched_client.get_test_types.side_effect = RuntimeError(
        "DefectDojo API Error 404: not found"
    )
    with pytest.raises(ToolError, match="404"):
        await list_test_types()


async def test_list_test_types_null_guard():
    """Raises ToolError when client is None."""
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await list_test_types()


# ---------------------------------------------------------------------------
# Client tests (via respx HTTP mocking)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_get_product_types(mock_client):
    expected = {
        "count": 1,
        "results": [
            {
                "id": 1,
                "name": "Research and Development",
                "description": "R&D",
                "critical_product": False,
                "key_product": True,
            }
        ],
    }
    route = respx.get(f"{BASE}/product_types/").mock(
        return_value=httpx.Response(200, json=expected)
    )
    result = await mock_client.get_product_types()
    assert route.called
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_client_get_product_types_pagination(mock_client):
    expected = {"count": 50, "results": []}
    route = respx.get(f"{BASE}/product_types/").mock(
        return_value=httpx.Response(200, json=expected)
    )
    result = await mock_client.get_product_types(limit=5, offset=10)
    assert route.called
    request = route.calls.last.request
    assert "limit=5" in str(request.url)
    assert "offset=10" in str(request.url)
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_client_get_test_types(mock_client):
    expected = {
        "count": 1,
        "results": [{"id": 1, "name": "Semgrep JSON Report", "tags": []}],
    }
    route = respx.get(f"{BASE}/test_types/").mock(
        return_value=httpx.Response(200, json=expected)
    )
    result = await mock_client.get_test_types()
    assert route.called
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_client_get_test_types_pagination(mock_client):
    expected = {"count": 100, "results": []}
    route = respx.get(f"{BASE}/test_types/").mock(
        return_value=httpx.Response(200, json=expected)
    )
    result = await mock_client.get_test_types(limit=10, offset=20)
    assert route.called
    request = route.calls.last.request
    assert "limit=10" in str(request.url)
    assert "offset=20" in str(request.url)
    assert result == expected

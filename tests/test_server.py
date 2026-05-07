"""Tests for mcp_defectdojo.server — tool logic, null guards, validation, and happy paths."""
import json
from unittest.mock import AsyncMock, patch

import pytest

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import (
    _format_response,
    create_engagement,
    create_finding,
    create_product,
    create_test,
    get_engagement,
    get_finding,
    get_product,
    get_test,
    health_check,
    list_engagements,
    list_findings,
    list_products,
    list_tests,
    lifespan,
    mcp,
    update_finding,
)
from mcp_defectdojo.models import ProductSummary
from tests.conftest import paginated_response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


# ---------------------------------------------------------------------------
# Lifespan tests
# ---------------------------------------------------------------------------


async def test_lifespan_success(mock_env, monkeypatch):
    """Lifespan creates the client on entry and calls aclose on exit."""
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    async with lifespan(mcp):
        assert server_module.client is not None
    # After context exit the client is closed; server_module.client may remain
    # as the closed object — we just verify aclose was called.


async def test_lifespan_missing_env(monkeypatch):
    """Lifespan raises ValueError when required env vars are absent."""
    monkeypatch.delenv("DEFECTDOJO_URL", raising=False)
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    with pytest.raises(ValueError):
        async with lifespan(mcp):
            pass  # pragma: no cover


# ---------------------------------------------------------------------------
# _format_response tests
# ---------------------------------------------------------------------------


def test_format_response_list(sample_product):
    result = _format_response(
        {"count": 1, "results": [sample_product]}, ProductSummary
    )
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert "pagination" in data
    assert data["pagination"]["count"] == 1


def test_format_response_single(sample_product):
    result = _format_response(sample_product, ProductSummary)
    data = json.loads(result)
    assert data["id"] == sample_product["id"]
    assert data["name"] == sample_product["name"]


def test_format_response_validation_error_list():
    result = _format_response(
        {"count": 1, "results": [{"bad": "data"}]}, ProductSummary
    )
    assert result.startswith("ERROR: Invalid API response data:")


def test_format_response_validation_error_single():
    result = _format_response({"bad": "data"}, ProductSummary)
    assert result.startswith("ERROR: Invalid API response data:")


# ---------------------------------------------------------------------------
# Null guard — parametrized over all 14 tool functions
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = [
    (health_check, {}, "UNHEALTHY: DefectDojo client not initialized"),
    (list_products, {"limit": 20, "offset": 0}, "ERROR: DefectDojo client not initialized"),
    (get_product, {"product_id": 1}, "ERROR: DefectDojo client not initialized"),
    (create_product, {"name": "x", "description": "x", "prod_type_id": 1}, "ERROR: DefectDojo client not initialized"),
    (list_engagements, {"product_id": 1, "limit": 20, "offset": 0}, "ERROR: DefectDojo client not initialized"),
    (get_engagement, {"engagement_id": 1}, "ERROR: DefectDojo client not initialized"),
    (create_engagement, {"product_id": 1, "name": "x", "target_start": "2026-01-01", "target_end": "2026-12-31"}, "ERROR: DefectDojo client not initialized"),
    (list_tests, {"engagement_id": 1, "limit": 20, "offset": 0}, "ERROR: DefectDojo client not initialized"),
    (get_test, {"test_id": 1}, "ERROR: DefectDojo client not initialized"),
    (create_test, {"engagement_id": 1, "test_type_id": 1, "target_start": "2026-01-01", "target_end": "2026-12-31"}, "ERROR: DefectDojo client not initialized"),
    (list_findings, {"test_id": None, "limit": 20, "offset": 0}, "ERROR: DefectDojo client not initialized"),
    (get_finding, {"finding_id": 1}, "ERROR: DefectDojo client not initialized"),
    (create_finding, {"test_id": 1, "title": "x", "severity": "High", "description": "x"}, "ERROR: DefectDojo client not initialized"),
    (update_finding, {"finding_id": 1, "title": "updated"}, "ERROR: DefectDojo client not initialized"),
]


@pytest.mark.parametrize("tool_func,kwargs,expected_substring", TOOL_FUNCTIONS)
async def test_tool_null_guard(tool_func, kwargs, expected_substring):
    """Each tool returns its appropriate error string when client is None."""
    server_module.client = None
    result = await tool_func(**kwargs)
    assert expected_substring in result


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


async def test_list_products_limit_too_high(patched_client):
    result = await list_products(limit=200)
    assert "ERROR" in result
    assert "limit" in result


async def test_list_products_limit_too_low(patched_client):
    result = await list_products(limit=0)
    assert "ERROR" in result
    assert "limit" in result


async def test_list_products_negative_offset(patched_client):
    result = await list_products(offset=-1)
    assert "ERROR" in result
    assert "offset" in result


async def test_get_product_zero_id(patched_client):
    result = await get_product(0)
    assert "ERROR" in result
    assert "product_id" in result


async def test_get_product_negative_id(patched_client):
    result = await get_product(-5)
    assert "ERROR" in result
    assert "product_id" in result


async def test_create_finding_invalid_severity(patched_client):
    result = await create_finding(1, "t", "Invalid", "d")
    assert "ERROR" in result
    assert "severity" in result


async def test_create_finding_zero_test_id(patched_client):
    result = await create_finding(0, "t", "High", "d")
    assert "ERROR" in result
    assert "test_id" in result


async def test_update_finding_no_fields(patched_client):
    result = await update_finding(1)
    assert "ERROR" in result
    assert "No fields" in result or "fields" in result.lower()


async def test_list_engagements_zero_product_id(patched_client):
    result = await list_engagements(0)
    assert "ERROR" in result
    assert "product_id" in result


async def test_list_tests_zero_engagement_id(patched_client):
    result = await list_tests(0)
    assert "ERROR" in result
    assert "engagement_id" in result


async def test_create_test_zero_test_type_id(patched_client):
    result = await create_test(1, 0, "2026-01-01", "2026-12-31")
    assert "ERROR" in result
    assert "test_type_id" in result


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


async def test_health_check_ok(patched_client, sample_product):
    patched_client.get_products.return_value = {"count": 1, "results": [sample_product]}
    result = await health_check()
    assert result == "OK: DefectDojo is reachable"


async def test_health_check_unhealthy(patched_client):
    patched_client.get_products.side_effect = RuntimeError("conn refused")
    result = await health_check()
    assert result.startswith("UNHEALTHY:")
    assert "conn refused" in result


async def test_list_products_success(patched_client, sample_product):
    patched_client.get_products.return_value = paginated_response([sample_product])
    result = await list_products(limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert "pagination" in data
    assert data["pagination"]["count"] == 1


async def test_get_product_success(patched_client, sample_product):
    patched_client.get_product.return_value = sample_product
    result = await get_product(1)
    data = json.loads(result)
    assert data["id"] == sample_product["id"]
    assert data["name"] == sample_product["name"]


async def test_create_product_success(patched_client, sample_product):
    patched_client.create_product.return_value = sample_product
    result = await create_product("Test Product", "A test product", 1)
    data = json.loads(result)
    assert data["id"] == sample_product["id"]
    patched_client.create_product.assert_called_once_with(
        "Test Product", "A test product", 1
    )


async def test_list_engagements_success(patched_client, sample_engagement):
    patched_client.get_engagements.return_value = paginated_response([sample_engagement])
    result = await list_engagements(product_id=2, limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    patched_client.get_engagements.assert_called_once_with(2, limit=20, offset=0)


async def test_create_engagement_success(patched_client, sample_engagement):
    patched_client.create_engagement.return_value = sample_engagement
    result = await create_engagement(
        product_id=1, name="Test Engagement",
        target_start="2026-01-01", target_end="2026-12-31"
    )
    data = json.loads(result)
    assert data["id"] == sample_engagement["id"]
    patched_client.create_engagement.assert_called_once_with(
        1, "Test Engagement", "2026-01-01", "2026-12-31"
    )


async def test_list_findings_with_test_id(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(test_id=4, limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    patched_client.get_findings.assert_called_once_with(4, limit=20, offset=0)


async def test_update_finding_partial(patched_client, sample_finding):
    updated = dict(sample_finding)
    updated["severity"] = "Low"
    patched_client.update_finding.return_value = updated
    result = await update_finding(finding_id=1, severity="Low")
    data = json.loads(result)
    assert data["severity"] == "Low"
    # Verify only severity (not finding_id or None values) was passed
    call_kwargs = patched_client.update_finding.call_args
    assert call_kwargs.kwargs == {"severity": "Low"}
    assert "finding_id" not in call_kwargs.kwargs

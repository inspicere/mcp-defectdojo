"""Tests for mcp_defectdojo.server — tool logic, null guards, validation, and happy paths."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.rbac import build_rbac_auth
from mcp_defectdojo.server import (
    _format_response,
    _require_client,
    _validate_pagination,
    _validate_date,
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
    assert server_module.client is None


async def test_lifespan_missing_env(monkeypatch):
    """Lifespan raises ValueError when required env vars are absent."""
    monkeypatch.delenv("DEFECTDOJO_URL", raising=False)
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    with pytest.raises(ValueError):
        async with lifespan(mcp):
            pass  # pragma: no cover


async def test_lifespan_session_summary_logged(mock_env, monkeypatch, capsys):
    """Lifespan emits session shutdown summary with tool call counts on exit."""
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    async with lifespan(mcp):
        pass
    captured = capsys.readouterr()
    assert "Session shutdown" in captured.err, "Expected 'Session shutdown' in stderr log output"
    assert "session_summary" in captured.err, "Expected 'session_summary' field in shutdown log"


# ---------------------------------------------------------------------------
# Auth builder tests
# ---------------------------------------------------------------------------


def test_build_auth_no_token(monkeypatch):
    """Without any auth env vars, build_rbac_auth returns None (auth disabled)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    assert build_rbac_auth() is None


def test_build_auth_with_token(monkeypatch):
    """With MCP_AUTH_TOKEN set, build_rbac_auth returns a StaticTokenVerifier."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-secret-token")
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    auth = build_rbac_auth()
    assert auth is not None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_validate_pagination_valid():
    _validate_pagination(50, 0)


def test_validate_pagination_limit_too_high():
    with pytest.raises(ToolError, match="limit"):
        _validate_pagination(200, 0)


def test_validate_pagination_negative_offset():
    with pytest.raises(ToolError, match="offset"):
        _validate_pagination(20, -1)


def test_validate_date_valid():
    _validate_date("2026-01-01", "target_start")


def test_validate_date_invalid():
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        _validate_date("not-a-date", "target_start")


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
    with pytest.raises(ToolError, match="Invalid API response data"):
        _format_response({"count": 1, "results": [{"bad": "data"}]}, ProductSummary)


def test_format_response_validation_error_single():
    with pytest.raises(ToolError, match="Invalid API response data"):
        _format_response({"bad": "data"}, ProductSummary)


# ---------------------------------------------------------------------------
# Null guard — all 13 tools (except health_check) raise ToolError via decorator
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = [
    (list_products, {"limit": 20, "offset": 0}),
    (get_product, {"product_id": 1}),
    (create_product, {"name": "x", "description": "x", "prod_type_id": 1}),
    (list_engagements, {"product_id": 1, "limit": 20, "offset": 0}),
    (get_engagement, {"engagement_id": 1}),
    (create_engagement, {"product_id": 1, "name": "x", "target_start": "2026-01-01", "target_end": "2026-12-31"}),
    (list_tests, {"engagement_id": 1, "limit": 20, "offset": 0}),
    (get_test, {"test_id": 1}),
    (create_test, {"engagement_id": 1, "test_type_id": 1, "target_start": "2026-01-01", "target_end": "2026-12-31"}),
    (list_findings, {"test_id": None, "limit": 20, "offset": 0}),
    (get_finding, {"finding_id": 1}),
    (create_finding, {"test_id": 1, "title": "x", "severity": "High", "description": "x"}),
    (update_finding, {"finding_id": 1, "title": "updated"}),
]


@pytest.mark.parametrize("tool_func,kwargs", TOOL_FUNCTIONS)
async def test_tool_null_guard(tool_func, kwargs):
    """Each tool raises ToolError when client is None."""
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await tool_func(**kwargs)


async def test_health_check_null_guard():
    """health_check returns a string (not ToolError) when client is None."""
    server_module.client = None
    result = await health_check()
    assert "UNHEALTHY" in result


# ---------------------------------------------------------------------------
# Input validation tests — all raise ToolError
# ---------------------------------------------------------------------------


async def test_list_products_limit_too_high(patched_client):
    with pytest.raises(ToolError, match="limit"):
        await list_products(limit=200)


async def test_list_products_limit_too_low(patched_client):
    with pytest.raises(ToolError, match="limit"):
        await list_products(limit=0)


async def test_list_products_negative_offset(patched_client):
    with pytest.raises(ToolError, match="offset"):
        await list_products(offset=-1)


async def test_get_product_zero_id(patched_client):
    with pytest.raises(ToolError, match="product_id"):
        await get_product(0)


async def test_get_product_negative_id(patched_client):
    with pytest.raises(ToolError, match="product_id"):
        await get_product(-5)


async def test_create_finding_invalid_severity(patched_client):
    with pytest.raises(ToolError, match="severity"):
        await create_finding(1, "t", "Invalid", "d")


async def test_create_finding_zero_test_id(patched_client):
    with pytest.raises(ToolError, match="test_id"):
        await create_finding(0, "t", "High", "d")


async def test_update_finding_no_fields(patched_client):
    with pytest.raises(ToolError, match="No fields"):
        await update_finding(1)


async def test_list_engagements_zero_product_id(patched_client):
    with pytest.raises(ToolError, match="product_id"):
        await list_engagements(0)


async def test_list_tests_zero_engagement_id(patched_client):
    with pytest.raises(ToolError, match="engagement_id"):
        await list_tests(0)


async def test_create_test_zero_test_type_id(patched_client):
    with pytest.raises(ToolError, match="test_type_id"):
        await create_test(1, 0, "2026-01-01", "2026-12-31")


async def test_create_engagement_invalid_date(patched_client):
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        await create_engagement(1, "eng", "not-a-date", "2026-12-31")


async def test_create_test_invalid_date(patched_client):
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        await create_test(1, 1, "2026-01-01", "bad-date")


async def test_update_finding_invalid_severity(patched_client):
    with pytest.raises(ToolError, match="severity"):
        await update_finding(1, severity="NotReal")


# ---------------------------------------------------------------------------
# RuntimeError propagation — all tools catch client errors as ToolError
# ---------------------------------------------------------------------------

TOOLS_WITH_CLIENT_CALLS = [
    (list_products, {"limit": 20, "offset": 0}, "get_products"),
    (get_product, {"product_id": 1}, "get_product"),
    (create_product, {"name": "x", "description": "x", "prod_type_id": 1}, "create_product"),
    (list_engagements, {"product_id": 1, "limit": 20, "offset": 0}, "get_engagements"),
    (get_engagement, {"engagement_id": 1}, "get_engagement"),
    (create_engagement, {"product_id": 1, "name": "x", "target_start": "2026-01-01", "target_end": "2026-12-31"}, "create_engagement"),
    (list_tests, {"engagement_id": 1, "limit": 20, "offset": 0}, "get_tests"),
    (get_test, {"test_id": 1}, "get_test"),
    (create_test, {"engagement_id": 1, "test_type_id": 1, "target_start": "2026-01-01", "target_end": "2026-12-31"}, "create_test"),
    (list_findings, {"test_id": None, "limit": 20, "offset": 0}, "get_findings"),
    (get_finding, {"finding_id": 1}, "get_finding"),
    (create_finding, {"test_id": 1, "title": "x", "severity": "High", "description": "x"}, "create_finding"),
    (update_finding, {"finding_id": 1, "title": "updated"}, "update_finding"),
]


@pytest.mark.parametrize("tool_func,kwargs,client_method", TOOLS_WITH_CLIENT_CALLS)
async def test_tool_catches_runtime_error(patched_client, tool_func, kwargs, client_method):
    """Each tool catches RuntimeError from the client and raises ToolError."""
    getattr(patched_client, client_method).side_effect = RuntimeError("DefectDojo API Error 404: not found")
    with pytest.raises(ToolError, match="404"):
        await tool_func(**kwargs)


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
    assert result == "UNHEALTHY: Unable to connect to DefectDojo"


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


async def test_get_engagement_success(patched_client, sample_engagement):
    patched_client.get_engagement.return_value = sample_engagement
    result = await get_engagement(1)
    data = json.loads(result)
    assert data["id"] == sample_engagement["id"]
    assert data["product_id"] == sample_engagement["product"]
    patched_client.get_engagement.assert_called_once_with(1)


async def test_list_tests_success(patched_client, sample_test_obj):
    patched_client.get_tests.return_value = paginated_response([sample_test_obj])
    result = await list_tests(engagement_id=3, limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == sample_test_obj["id"]
    patched_client.get_tests.assert_called_once_with(3, limit=20, offset=0)


async def test_get_test_success(patched_client, sample_test_obj):
    patched_client.get_test.return_value = sample_test_obj
    result = await get_test(1)
    data = json.loads(result)
    assert data["id"] == sample_test_obj["id"]
    assert data["engagement_id"] == sample_test_obj["engagement"]
    patched_client.get_test.assert_called_once_with(1)


async def test_create_test_success(patched_client, sample_test_obj):
    patched_client.create_test.return_value = sample_test_obj
    result = await create_test(
        engagement_id=3, test_type_id=1,
        target_start="2026-01-01", target_end="2026-12-31"
    )
    data = json.loads(result)
    assert data["id"] == sample_test_obj["id"]
    patched_client.create_test.assert_called_once_with(3, 1, "2026-01-01", "2026-12-31")


async def test_get_finding_success(patched_client, sample_finding):
    patched_client.get_finding.return_value = sample_finding
    result = await get_finding(1)
    data = json.loads(result)
    assert data["id"] == sample_finding["id"]
    assert data["title"] == sample_finding["title"]
    assert data["severity"] == sample_finding["severity"]
    patched_client.get_finding.assert_called_once_with(1)


async def test_create_finding_success(patched_client, sample_finding):
    patched_client.create_finding.return_value = sample_finding
    result = await create_finding(
        test_id=4, title="XSS Vuln", severity="High", description="Found XSS"
    )
    data = json.loads(result)
    assert data["id"] == sample_finding["id"]
    assert data["title"] == "XSS Vuln"
    patched_client.create_finding.assert_called_once_with(
        4, "XSS Vuln", "High", "Found XSS", True, False
    )


async def test_list_findings_with_test_id(patched_client, sample_finding):
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(test_id=4, limit=20, offset=0)
    data = json.loads(result)
    assert "items" in data
    assert len(data["items"]) == 1
    patched_client.get_findings.assert_called_once_with(
        test_id=4, product_id=None, engagement_id=None,
        severity=None, active=None, verified=None, duplicate=None,
        false_p=None, out_of_scope=None, is_mitigated=None,
        risk_accepted=None, has_jira=None, tags=None,
        outside_of_sla=None, component_name=None, title=None,
        limit=20, offset=0,
    )


async def test_update_finding_partial(patched_client, sample_finding):
    updated = dict(sample_finding)
    updated["severity"] = "Low"
    patched_client.update_finding.return_value = updated
    result = await update_finding(finding_id=1, severity="Low")
    data = json.loads(result)
    assert data["severity"] == "Low"
    call_kwargs = patched_client.update_finding.call_args
    assert call_kwargs.kwargs == {"severity": "Low"}
    assert "finding_id" not in call_kwargs.kwargs

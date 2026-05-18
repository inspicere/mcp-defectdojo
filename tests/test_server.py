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
    main,
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
    """health_check returns JSON with unhealthy status when client is None."""
    server_module.client = None
    result = await health_check()
    data = json.loads(result)
    assert data["status"] == "unhealthy"


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


async def test_create_finding_rejects_secret_in_title(patched_client):
    """F-005: title with embedded credentials must be rejected at the write boundary."""
    with pytest.raises(ToolError, match="embedded secret"):
        await create_finding(1, "leak: AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7", "High", "desc")
    patched_client.create_finding.assert_not_called()


async def test_create_finding_rejects_secret_in_description(patched_client):
    """F-005: description with embedded credentials must be rejected."""
    with pytest.raises(ToolError, match="embedded secret"):
        await create_finding(1, "t", "High", "found token AKIAIOSFODNN7EXAMPLE in source")
    patched_client.create_finding.assert_not_called()


async def test_update_finding_rejects_secret_in_title(patched_client):
    with pytest.raises(ToolError, match="embedded secret"):
        await update_finding(1, title="ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    patched_client.update_finding.assert_not_called()


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
    data = json.loads(result)
    assert data["status"] == "ok"
    assert data["message"] == "DefectDojo is reachable"


async def test_health_check_unhealthy(patched_client):
    patched_client.get_products.side_effect = RuntimeError("conn refused")
    result = await health_check()
    data = json.loads(result)
    assert data["status"] == "unhealthy"


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
    # F-002: title/description/tags are wrapped in the untrusted-content envelope.
    assert data["title"]["value"] == sample_finding["title"]
    assert data["severity"] == sample_finding["severity"]
    patched_client.get_finding.assert_called_once_with(1)


async def test_create_finding_success(patched_client, sample_finding):
    patched_client.create_finding.return_value = sample_finding
    result = await create_finding(
        test_id=4, title="XSS Vuln", severity="High", description="Found XSS"
    )
    data = json.loads(result)
    assert data["id"] == sample_finding["id"]
    # F-002: title is wrapped in the untrusted-content envelope on the read path.
    assert data["title"]["value"] == "XSS Vuln"
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


# ---------------------------------------------------------------------------
# Lifespan — network transport without auth warns
# ---------------------------------------------------------------------------


async def test_lifespan_network_no_auth_requires_opt_out(mock_env, monkeypatch):
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("FASTMCP_TRANSPORT", "sse")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="MCP auth is not configured"):
        async with lifespan(mcp):
            pass


@pytest.mark.asyncio
async def test_lifespan_network_no_auth_warns(mock_env, monkeypatch, capsys):
    monkeypatch.setattr(server_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("FASTMCP_TRANSPORT", "sse")
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    async with lifespan(mcp):
        pass
    captured = capsys.readouterr()
    assert "auth is disabled" in captured.err


# ---------------------------------------------------------------------------
# main() — transport dispatch
# ---------------------------------------------------------------------------


def test_main_stdio(monkeypatch):
    monkeypatch.delenv("FASTMCP_TRANSPORT", raising=False)
    with patch.object(mcp, "run") as mock_run:
        main()
        mock_run.assert_called_once_with()


def test_main_network_transport(monkeypatch):
    monkeypatch.setenv("FASTMCP_TRANSPORT", "sse")
    monkeypatch.setenv("FASTMCP_HOST", "127.0.0.1")
    monkeypatch.setenv("FASTMCP_PORT", "9000")
    with patch.object(mcp, "run") as mock_run:
        main()
        mock_run.assert_called_once_with(transport="sse", host="127.0.0.1", port=9000)


# ---------------------------------------------------------------------------
# F-008 / F-018 — state-transition gate in update_finding
# ---------------------------------------------------------------------------


def _patch_access_token(monkeypatch, role: str | None, client_id: str = "test-client"):
    """Patch fastmcp.server.dependencies.get_access_token to return a fake token.

    Pass role=None to simulate open-access mode (no token).
    """
    if role is None:
        token = None
    else:
        from unittest.mock import MagicMock as _MM
        token = _MM()
        token.claims = {"role": role, "client_id": client_id}
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: token)


@pytest.fixture
def mitigated_finding(sample_finding):
    """A finding dict representing a currently-mitigated finding."""
    f = dict(sample_finding)
    f["active"] = False
    f["is_mitigated"] = True
    f["mitigated"] = "2026-05-15T00:00:00Z"
    return f


async def test_update_finding_active_true_rejects_on_mitigated_with_finding_mgmt(
    patched_client, mitigated_finding, monkeypatch
):
    """F-008/F-018: active=true cascade on a mitigated finding is rejected when caller lacks engagement_mgmt.

    DefectDojo's known cascade: active=true forces is_mitigated=false. The
    update_finding gate must catch this side-effect path even though the
    caller never passed is_mitigated explicitly.

    Open-access mode (no role token) is the regression vector: in this state
    `permission_check_now` is a no-op (matching AC-8.11), so the only thing
    standing between an unauthenticated caller and a silent reopen-via-update
    is the cascade gate itself. The gate fails closed without an
    engagement_mgmt role.
    """
    _patch_access_token(monkeypatch, role=None)  # open-access — no role
    patched_client.get_finding.return_value = mitigated_finding
    with pytest.raises(ToolError, match="reopen_finding"):
        await update_finding(finding_id=1, active=True)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_active_true_allowed_with_engagement_mgmt(
    patched_client, mitigated_finding, monkeypatch
):
    """F-008/F-018: writer role (has engagement_mgmt) may transition the finding via update_finding."""
    _patch_access_token(monkeypatch, role="writer")
    patched_client.get_finding.return_value = mitigated_finding
    # Echo back a reopened-looking finding
    reopened = dict(mitigated_finding)
    reopened["active"] = True
    reopened["is_mitigated"] = False
    reopened["mitigated"] = None
    patched_client.update_finding.return_value = reopened
    result = await update_finding(finding_id=1, active=True)
    data = json.loads(result)
    assert data["active"] is True
    # Backend was called (not blocked) — writer has engagement_mgmt
    patched_client.update_finding.assert_called_once_with(1, active=True)


async def test_update_finding_verified_true_active_false_rejected(patched_client):
    """F-008 secondary: verified=true combined with active=false is logically inconsistent."""
    with pytest.raises(ToolError, match="verified=true on an inactive"):
        await update_finding(finding_id=1, verified=True, active=False)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_is_mitigated_false_explicit_rejected_without_engagement_mgmt(
    patched_client, mitigated_finding, monkeypatch
):
    """F-008: explicit is_mitigated=false on a mitigated finding requires engagement_mgmt.

    Same open-access regression vector as the active-cascade case — the
    handler permission gate is a no-op in open-access, so the explicit
    is_mitigated=false gate is the only line of defense.
    """
    _patch_access_token(monkeypatch, role=None)  # open-access
    patched_client.get_finding.return_value = mitigated_finding
    with pytest.raises(ToolError, match="reopen_finding"):
        await update_finding(finding_id=1, is_mitigated=False)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_active_true_allows_on_unmitigated(
    patched_client, sample_finding, monkeypatch
):
    """If the finding is not currently mitigated, active=true is just a normal update —
    no cascade gate fires, no role check, no audit transition event."""
    _patch_access_token(monkeypatch, role=None)
    patched_client.get_finding.return_value = sample_finding  # is_mitigated=False
    patched_client.update_finding.return_value = sample_finding
    await update_finding(finding_id=1, active=True)
    patched_client.update_finding.assert_called_once_with(1, active=True)


async def test_update_finding_emits_transition_cause_active_side_effect(
    patched_client, mitigated_finding, monkeypatch, caplog
):
    """Successful active=true cascade by an engagement_mgmt-bearing caller emits
    a structured audit event with transition_cause='active_side_effect'."""
    import logging
    _patch_access_token(monkeypatch, role="writer")
    patched_client.get_finding.return_value = mitigated_finding
    reopened = dict(mitigated_finding)
    reopened["active"] = True
    reopened["is_mitigated"] = False
    patched_client.update_finding.return_value = reopened
    with caplog.at_level(logging.INFO, logger="mcp_defectdojo.server"):
        await update_finding(finding_id=1, active=True)
    # Find the transition audit event
    matches = [r for r in caplog.records if getattr(r, "transition_cause", None) == "active_side_effect"]
    assert matches, "Expected at least one audit record with transition_cause='active_side_effect'"
    assert matches[0].outcome == "success"
    assert matches[0].tool_name == "update_finding"


async def test_update_finding_emits_transition_cause_explicit_field(
    patched_client, mitigated_finding, monkeypatch, caplog
):
    """Successful explicit is_mitigated=false by engagement_mgmt emits transition_cause='explicit_field'."""
    import logging
    _patch_access_token(monkeypatch, role="admin")
    patched_client.get_finding.return_value = mitigated_finding
    reopened = dict(mitigated_finding)
    reopened["is_mitigated"] = False
    patched_client.update_finding.return_value = reopened
    with caplog.at_level(logging.INFO, logger="mcp_defectdojo.server"):
        await update_finding(finding_id=1, is_mitigated=False)
    matches = [r for r in caplog.records if getattr(r, "transition_cause", None) == "explicit_field"]
    assert matches, "Expected at least one audit record with transition_cause='explicit_field'"
    assert matches[0].outcome == "success"


# ---------------------------------------------------------------------------
# F-007 — has_jira filter rejection
# ---------------------------------------------------------------------------


async def test_list_findings_has_jira_filter_rejected_with_clear_error(patched_client):
    """F-007: has_jira filter is silently ignored by DefectDojo — reject at runtime."""
    with pytest.raises(ToolError, match="has_jira filter is unsupported"):
        await list_findings(has_jira=True)
    patched_client.get_findings.assert_not_called()


async def test_list_findings_has_jira_false_also_rejected(patched_client):
    """F-007: rejection applies to both has_jira=true and has_jira=false."""
    with pytest.raises(ToolError, match="has_jira filter is unsupported"):
        await list_findings(has_jira=False)
    patched_client.get_findings.assert_not_called()


async def test_list_findings_has_jira_none_does_not_reject(patched_client, sample_finding):
    """F-007: only an explicit has_jira value triggers the rejection — None is fine."""
    from tests.conftest import paginated_response
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(test_id=4)  # has_jira defaults to None
    data = json.loads(result)
    assert "items" in data
    patched_client.get_findings.assert_called_once()


# ---------------------------------------------------------------------------
# Boolean filter partition test — true ∪ false == unfiltered
# ---------------------------------------------------------------------------


async def test_list_findings_boolean_filter_partition(patched_client, sample_finding):
    """For boolean filters list_findings exposes (e.g., active), true + false results
    should equal the unfiltered total. Confirms the filter actually partitions the
    underlying dataset (F-007 generalization: catch silently-ignored boolean filters)."""
    from tests.conftest import paginated_response
    # Simulate a 10-finding dataset that splits 6 active / 4 inactive.
    active_subset = [dict(sample_finding, id=i, active=True) for i in range(1, 7)]
    inactive_subset = [dict(sample_finding, id=i, active=False) for i in range(7, 11)]
    full_set = active_subset + inactive_subset

    def _select(**kwargs):
        if kwargs.get("active") is True:
            return paginated_response(active_subset)
        if kwargs.get("active") is False:
            return paginated_response(inactive_subset)
        return paginated_response(full_set)

    patched_client.get_findings.side_effect = lambda **kw: _select(**kw)

    true_res = json.loads(await list_findings(active=True))
    false_res = json.loads(await list_findings(active=False))
    full_res = json.loads(await list_findings())

    assert len(true_res["items"]) + len(false_res["items"]) == len(full_res["items"]), (
        "boolean filter must partition: true ∪ false == unfiltered"
    )
    # Cross-check disjoint
    true_ids = {item["id"] for item in true_res["items"]}
    false_ids = {item["id"] for item in false_res["items"]}
    assert true_ids.isdisjoint(false_ids), "true and false result sets must be disjoint"


# ---------------------------------------------------------------------------
# OP-02 — HTTP /health route (container HEALTHCHECK target)
# ---------------------------------------------------------------------------


def test_http_health_route_returns_200(mock_env):
    """The `/health` HTTP route returns 200 + {"status": "ok"} so the
    Dockerfile HEALTHCHECK probe succeeds. Distinct from the `health_check`
    MCP tool which probes upstream DefectDojo connectivity.
    mock_env fixture is required because mounting mcp.http_app() triggers the
    lifespan, which constructs a DefectDojoClient (needs URL + key env vars)."""
    from starlette.testclient import TestClient

    with TestClient(mcp.http_app()) as http_client:
        response = http_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

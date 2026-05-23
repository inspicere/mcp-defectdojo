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
    _wrap_untrusted,
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
# T1 / Phase 14 — @_translate_client_errors decorator behavior
# ---------------------------------------------------------------------------


async def test_translate_client_errors_translates_runtime_error_to_tool_error(patched_client):
    """The decorator wraps RuntimeError from the client layer as ToolError."""
    patched_client.get_products.side_effect = RuntimeError("boom from client")
    with pytest.raises(ToolError, match="boom from client"):
        await list_products(limit=20, offset=0)


async def test_translate_client_errors_passes_through_value_error(patched_client):
    """Non-RuntimeError exceptions are not wrapped — they propagate as-is."""
    patched_client.get_products.side_effect = ValueError("not a runtime error")
    with pytest.raises(ValueError, match="not a runtime error"):
        await list_products(limit=20, offset=0)


async def test_translate_client_errors_passes_through_tool_error(patched_client):
    """A ToolError raised explicitly inside the body is NOT re-wrapped — it propagates as-is.
    (Verifies the except clause catches ONLY RuntimeError, not ToolError.)"""
    patched_client.get_products.side_effect = ToolError("explicit tool error")
    with pytest.raises(ToolError, match="explicit tool error"):
        await list_products(limit=20, offset=0)


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
    # DOM-22 (Phase 14.2): the AUDIT_HMAC_KEY fail-CLOSED guard now also
    # fires on network transport. Opt out via REQUIRE_AUDIT_HMAC_KEY=false
    # so this test continues to exercise the MCP_AUTH guard specifically.
    monkeypatch.setenv("REQUIRE_AUDIT_HMAC_KEY", "false")
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
    # DOM-22 (Phase 14.2): same as above — opt out of the new fail-CLOSED guard.
    monkeypatch.setenv("REQUIRE_AUDIT_HMAC_KEY", "false")
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


def test_main_bad_fastmcp_port_fails_loudly(monkeypatch):
    """DD #3456: FASTMCP_PORT must validate at startup with a clear message
    instead of a bare int() ValueError traceback."""
    monkeypatch.setenv("FASTMCP_TRANSPORT", "sse")
    monkeypatch.setenv("FASTMCP_PORT", "not-a-number")
    with patch.object(mcp, "run"):
        with pytest.raises(ValueError, match=r"FASTMCP_PORT.*not-a-number"):
            main()


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


async def test_update_finding_emits_multi_cause_when_multiple_cascade_fields_set(
    patched_client, mitigated_finding, monkeypatch, caplog
):
    """SEC-10 (Phase 14.2): when a single update_finding call carries multiple
    cascade-triggering fields (e.g. explicit `is_mitigated=False` AND
    `active=True`), the audit event's `transition_cause` enumerates every
    cause as a comma-separated string instead of collapsing to the first
    branch matched. SIEM rules that join on the field can now distinguish
    "operator deliberately unmitigated + reactivated in one PATCH" from
    "operator only unmitigated, backend cascade may reactivate" — which
    materially changes the suspicion ranking.
    """
    import logging
    _patch_access_token(monkeypatch, role="writer")
    patched_client.get_finding.return_value = mitigated_finding
    reopened = dict(mitigated_finding)
    reopened["is_mitigated"] = False
    reopened["active"] = True
    patched_client.update_finding.return_value = reopened
    with caplog.at_level(logging.INFO, logger="mcp_defectdojo.server"):
        await update_finding(finding_id=1, is_mitigated=False, active=True)
    matches = [
        r for r in caplog.records
        if getattr(r, "transition_cause", None) == "explicit_field,active_side_effect"
    ]
    assert matches, (
        "Expected at least one audit record with "
        "transition_cause='explicit_field,active_side_effect'; got: "
        f"{[getattr(r, 'transition_cause', None) for r in caplog.records]}"
    )
    assert matches[0].outcome == "success"
    assert matches[0].tool_name == "update_finding"


# ---------------------------------------------------------------------------
# AC-13.1 — two-call verified+inactive mutex via state-transition gate
# ---------------------------------------------------------------------------


async def test_update_finding_rejects_verified_true_when_currently_inactive(
    patched_client, sample_finding, monkeypatch
):
    """AC-13.1: setting verified=true on a finding whose current state is
    active=false must be rejected via the post-state mutex inside the gate,
    even though the same call does not pass active=false."""
    _patch_access_token(monkeypatch, role=None)
    current = dict(sample_finding)
    current["active"] = False
    current["is_mitigated"] = False
    current["verified"] = False
    patched_client.get_finding.return_value = current
    with pytest.raises(ToolError, match="Cannot set verified=true on an inactive finding"):
        await update_finding(finding_id=1, verified=True)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_rejects_active_false_when_currently_verified(
    patched_client, sample_finding, monkeypatch
):
    """AC-13.1: setting active=false on a finding whose current state is
    verified=true must be rejected via the post-state mutex inside the gate,
    even though the same call does not pass verified=true."""
    _patch_access_token(monkeypatch, role=None)
    current = dict(sample_finding)
    current["active"] = True
    current["is_mitigated"] = False
    current["verified"] = True
    patched_client.get_finding.return_value = current
    with pytest.raises(ToolError, match="Cannot set verified=true on an inactive finding"):
        await update_finding(finding_id=1, active=False)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_allows_verified_true_when_currently_active(
    patched_client, sample_finding, monkeypatch
):
    """AC-13.1: setting verified=true on a finding whose current state is
    active=true is allowed — the post-state is verified=true + active=true,
    which is a consistent combination."""
    _patch_access_token(monkeypatch, role=None)
    current = dict(sample_finding)
    current["active"] = True
    current["is_mitigated"] = False
    current["verified"] = False
    patched_client.get_finding.return_value = current
    updated = dict(current)
    updated["verified"] = True
    patched_client.update_finding.return_value = updated
    result = await update_finding(finding_id=1, verified=True)
    data = json.loads(result)
    assert data["verified"] is True
    patched_client.update_finding.assert_called_once_with(1, verified=True)


# ---------------------------------------------------------------------------
# AC-13.2 — _wrap_untrusted idempotency guard
# ---------------------------------------------------------------------------


def test_wrap_untrusted_idempotent():
    """AC-13.2: applying _wrap_untrusted twice yields the same single envelope —
    no nested {"value": {"value": ..., "_warning": ...}, "_warning": ...}."""
    once = _wrap_untrusted("x")
    twice = _wrap_untrusted(_wrap_untrusted("x"))
    assert twice == once
    assert isinstance(once, dict)
    assert set(once.keys()) == {"value", "_warning"}
    assert once["value"] == "x"
    # Confirm the inner "value" was NOT re-wrapped on the second pass.
    assert twice["value"] == "x"


def test_wrap_untrusted_three_key_dict_wraps_normally():
    """SB-006: idempotency guard fires ONLY on exactly-2-key dicts with the
    {"value", "_warning"} key set. A 3-key dict is not the envelope shape and
    must be wrapped normally."""
    three_key = {"value": "v", "_warning": "w", "extra": "e"}
    wrapped = _wrap_untrusted(three_key)
    assert wrapped["value"] is three_key
    assert wrapped["_warning"].startswith("untrusted-content")


def test_wrap_untrusted_list_wraps_normally():
    """SB-006: lists are not dicts; idempotency guard does NOT fire — wrap
    happens as for any non-dict value."""
    payload = ["a", "b", "c"]
    wrapped = _wrap_untrusted(payload)
    assert wrapped["value"] == payload
    assert wrapped["_warning"].startswith("untrusted-content")


def test_wrap_untrusted_documented_false_positive_corner():
    """SB-006: an API dict that happens to have exactly the {"value", "_warning"}
    key set is indistinguishable from an envelope and gets silently skipped.
    This is the documented residual risk of the idempotency guard — currently
    theoretical because wrap-target fields (`_UNTRUSTED_FIELDS`) are strings or
    lists, never dicts with this exact shape. This test pins the documented
    behavior so a future widening of `_UNTRUSTED_FIELDS` is forced to consider
    the corner."""
    envelope_lookalike = {"value": "real-data", "_warning": "real-warning"}
    out = _wrap_untrusted(envelope_lookalike)
    assert out is envelope_lookalike  # NOT re-wrapped — guard fires


# ---------------------------------------------------------------------------
# AC-13.3 — rate-limit fires before the gate's pre-flight GET
# ---------------------------------------------------------------------------


async def test_update_finding_rate_limit_blocks_before_gate_get(
    patched_client, monkeypatch
):
    """AC-13.3: a rate-limit rejection from the limiter must short-circuit
    BEFORE the gate's pre-flight client.get_finding call — otherwise a
    burst of update_finding attempts amplifies into a burst of GETs."""
    _patch_access_token(monkeypatch, role=None)

    async def _deny(_ctx):
        raise ToolError("Rate limit exceeded: simulated test denial.")

    monkeypatch.setattr(server_module, "_check_mutation_rate_limit", _deny)
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        await update_finding(finding_id=1, is_mitigated=True)
    assert patched_client.get_finding.await_count == 0
    patched_client.update_finding.assert_not_called()


# ---------------------------------------------------------------------------
# AC-13.4 — caller-role probe handles AttributeError (and friends)
# ---------------------------------------------------------------------------


async def test_update_finding_caller_role_probe_handles_attribute_error(
    patched_client, mitigated_finding, monkeypatch
):
    """AC-13.4: when the caller-role probe inside the gate hits an
    AttributeError (a plausible future FastMCP regression where token.claims
    is reshaped or unexpectedly None), the broadened except must catch it
    and fail closed — caller treated as having no engagement_mgmt — instead
    of crashing update_finding with an uncaught AttributeError.

    Setup: a token whose .claims supports the first two ``.get(...)`` calls
    (so audit_logging.resolve_identity and permission_check_now both pass with
    a valid writer role), then raises AttributeError on subsequent accesses
    inside the gate. Without the broadened except clause, this would surface
    as a 500-equivalent crash rather than a structured ToolError.

    With the broadened except, the gate falls through with
    ``caller_has_engagement_mgmt=False`` (fail closed); the mitigation-clear
    rejection then takes over, producing the expected reopen_finding redirect.
    """
    class _DegradingClaims:
        def __init__(self):
            self._calls = 0
            self._data = {"role": "writer", "client_id": "test-client"}

        def get(self, key, default=None):
            self._calls += 1
            # First 2 calls (permission_check_now's role + client_id lookups)
            # behave normally; subsequent calls (the gate's) raise.
            if self._calls > 2:
                raise AttributeError("claims dict no longer supports .get()")
            return self._data.get(key, default)

    class _DegradingToken:
        client_id = "test-client"
        claims = _DegradingClaims()

    import fastmcp.server.dependencies as deps
    bad_token = _DegradingToken()
    monkeypatch.setattr(deps, "get_access_token", lambda: bad_token)
    patched_client.get_finding.return_value = mitigated_finding
    # is_mitigated=False is a cascade-triggering field; the gate fires, the
    # role probe raises AttributeError (caught), and the fail-closed default
    # of caller_has_engagement_mgmt=False produces the reopen_finding redirect
    # — NOT an uncaught AttributeError.
    with pytest.raises(ToolError, match="reopen_finding"):
        await update_finding(finding_id=1, is_mitigated=False)
    patched_client.update_finding.assert_not_called()


@pytest.mark.parametrize("exc_class,exc_message", [
    (TypeError, "claims is None — cannot subscript"),
    (KeyError, "role"),
])
async def test_update_finding_caller_role_probe_handles_other_exception_classes(
    patched_client, mitigated_finding, monkeypatch, exc_class, exc_message,
):
    """SA-001 / AC-13.4: the broadened except `(RuntimeError, AttributeError,
    TypeError, KeyError)` must fail-close on every class in the tuple. The
    AttributeError variant is covered above; this parametrized test exercises
    TypeError and KeyError so a future tightening of the except clause that
    accidentally drops one of them would surface as a test regression rather
    than a 500 in production.
    """
    class _DegradingClaims:
        def __init__(self, exc, msg):
            self._calls = 0
            self._exc = exc
            self._msg = msg
            self._data = {"role": "writer", "client_id": "test-client"}

        def get(self, key, default=None):
            self._calls += 1
            if self._calls > 2:
                raise self._exc(self._msg)
            return self._data.get(key, default)

    class _DegradingToken:
        client_id = "test-client"
        claims = _DegradingClaims(exc_class, exc_message)

    import fastmcp.server.dependencies as deps
    bad_token = _DegradingToken()
    monkeypatch.setattr(deps, "get_access_token", lambda: bad_token)
    patched_client.get_finding.return_value = mitigated_finding
    with pytest.raises(ToolError, match="reopen_finding"):
        await update_finding(finding_id=1, is_mitigated=False)
    patched_client.update_finding.assert_not_called()


# ---------------------------------------------------------------------------
# DOM-19 (Phase 14.2) — has_jira removed from list_findings signature
# ---------------------------------------------------------------------------


def test_list_findings_has_jira_not_in_signature():
    """DOM-19: the `has_jira` parameter was removed entirely from
    `list_findings`'s signature in Phase 14.2. Prior to v3.2.6 it was
    accepted-then-rejected at runtime; now it's gone from the schema so
    LLM clients cannot select it from the tool catalogue at all.
    """
    import inspect
    sig = inspect.signature(list_findings)
    assert "has_jira" not in sig.parameters, (
        f"has_jira must not appear in list_findings signature; "
        f"parameters: {list(sig.parameters)}"
    )


async def test_list_findings_has_jira_none_does_not_reject(patched_client, sample_finding):
    """DOM-19: clean calls (no has_jira) continue to work — sanity check that
    the parameter removal did not break the happy path."""
    from tests.conftest import paginated_response
    patched_client.get_findings.return_value = paginated_response([sample_finding])
    result = await list_findings(test_id=4)
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


def test_http_health_route_unauthenticated_even_with_auth_configured(mock_env, monkeypatch):
    """SB-2: orchestrator HEALTHCHECK probes do NOT carry the MCP bearer token.
    The /health route MUST stay unauthenticated even when MCP_AUTH_TOKEN is set
    (production posture — Docker, Kubernetes, systemd cannot inject the bearer
    into the urllib.request.urlopen() call in the Dockerfile HEALTHCHECK). The
    default test (above) runs in open-access mode; this test sets MCP_AUTH_TOKEN
    so FastMCP would normally require auth on tool calls, and proves /health
    still returns 200 without an Authorization header."""
    from starlette.testclient import TestClient

    monkeypatch.setenv("MCP_AUTH_TOKEN", "any-secret-token")

    with TestClient(mcp.http_app()) as http_client:
        response = http_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# QLT-03 — _validate_tag_list helper (Phase 14 / T3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_tag_list_invalid_tag_raises():
    """QLT-03: helper raises ToolError when any tag is invalid (e.g., newline)."""
    from mcp_defectdojo.server import _validate_tag_list
    with pytest.raises(ToolError):
        _validate_tag_list(["clean-tag", "bad\ntag"])


def test_validate_tag_list_none_and_empty_are_noop():
    """QLT-03: helper accepts None / empty list as no-op."""
    from mcp_defectdojo.server import _validate_tag_list
    _validate_tag_list(None)  # must not raise
    _validate_tag_list([])    # must not raise


# ---------------------------------------------------------------------------
# QLT-01 / AC-14.2.1 — update_finding helper decomposition (Phase 14.2 / T1)
# ---------------------------------------------------------------------------


def test_resolve_caller_role_for_gate_with_writer_token(monkeypatch):
    """T1: writer token resolves to (engagement_mgmt=True, role='writer', ...).

    The role-resolution helper is the gate's pivot: when it returns
    engagement_mgmt=True the mitigation-clear branch is bypassed. Pin the
    happy path so a future Role/ROLE_PERMISSIONS change that drops
    engagement_mgmt from writer surfaces here, not as a silent regression
    of `test_update_finding_active_true_allowed_with_engagement_mgmt`.
    """
    from mcp_defectdojo.server import _resolve_caller_role_for_gate
    from unittest.mock import MagicMock as _MM
    import fastmcp.server.dependencies as deps
    # Token with real string client_id so resolve_identity returns a str.
    token = _MM()
    token.client_id = "writer-client"
    token.claims = {"role": "writer", "client_id": "writer-client"}
    monkeypatch.setattr(deps, "get_access_token", lambda: token)
    eng_mgmt, role_name, auth_id, meta_id = _resolve_caller_role_for_gate(None)
    assert eng_mgmt is True
    assert role_name == "writer"
    # authenticated_caller_id is sourced from token.client_id; meta is "anonymous"
    # when ctx is None (resolve_identity contract).
    assert auth_id == "writer-client"
    assert meta_id == "anonymous"


def test_resolve_caller_role_for_gate_handles_missing_token(monkeypatch):
    """T1 / AC-13.4: fail-closed when get_access_token() raises RuntimeError.

    RuntimeError is the FastMCP-emitted variant for "no current request
    context" (open-access / background-task). The broadened-except set must
    catch it and return (engagement_mgmt=False, role=None, ...) so the gate
    falls through to the mitigation-clear rejection branch instead of
    crashing update_finding.
    """
    from mcp_defectdojo.server import _resolve_caller_role_for_gate
    import fastmcp.server.dependencies as deps

    def _raise_runtime():
        raise RuntimeError("no current request context")

    monkeypatch.setattr(deps, "get_access_token", _raise_runtime)
    eng_mgmt, role_name, auth_id, meta_id = _resolve_caller_role_for_gate(None)
    assert eng_mgmt is False  # fail-closed
    assert role_name is None
    assert isinstance(auth_id, str)
    assert isinstance(meta_id, str)


def test_compute_cascade_post_state_active_explicit():
    """T1: explicit active in kwargs overrides current snapshot; verified
    falls back to current. Pins the post-state math that AC-13.1's two-call
    mutex relies on."""
    from mcp_defectdojo.server import _compute_cascade_post_state
    current = {"active": True, "verified": True}
    # kwargs flips active to False; verified is absent → falls back to current
    post_active, post_verified = _compute_cascade_post_state({"active": False}, current)
    assert post_active is False
    assert post_verified is True
    # Both absent → both fall back to current (bool-coerced)
    post_active2, post_verified2 = _compute_cascade_post_state({}, {"active": 0, "verified": 1})
    assert post_active2 is False
    assert post_verified2 is True


def test_compute_cascade_cause_explicit_is_mitigated_false():
    """T1 + SEC-10 (Phase 14.2 / T3 merge resolution): with multi-cause
    attribution, explicit_field is the FIRST cause but no longer EXCLUSIVE —
    concurrent cascade triggers are also reported, comma-joined. Pins the
    declaration-order ordering of the cause list.
    """
    from mcp_defectdojo.server import _compute_cascade_cause
    # is_mitigated=False present alongside active=True and false_p=True;
    # all three fire — explicit_field listed first per declaration order.
    cause = _compute_cascade_cause(
        {"is_mitigated": False, "active": True, "false_p": True},
        currently_mitigated=True,
    )
    assert cause == "explicit_field,active_side_effect,false_p_side_effect"
    # is_mitigated=False alone still attributes to explicit_field only.
    assert _compute_cascade_cause(
        {"is_mitigated": False}, currently_mitigated=True
    ) == "explicit_field"
    # currently_mitigated=False short-circuits regardless of cascade fields.
    assert _compute_cascade_cause({"is_mitigated": False}, currently_mitigated=False) is None


def test_compute_cascade_cause_active_side_effect():
    """T1: active=True on a mitigated finding (without explicit is_mitigated)
    attributes to ``active_side_effect`` — DefectDojo's known cascade rule
    (DEC-024). false_p/duplicate/out_of_scope follow in elif order."""
    from mcp_defectdojo.server import _compute_cascade_cause
    assert _compute_cascade_cause({"active": True}, currently_mitigated=True) == "active_side_effect"
    assert _compute_cascade_cause({"false_p": True}, currently_mitigated=True) == "false_p_side_effect"
    assert _compute_cascade_cause({"duplicate": True}, currently_mitigated=True) == "duplicate_side_effect"
    assert _compute_cascade_cause({"out_of_scope": True}, currently_mitigated=True) == "out_of_scope_side_effect"
    # No cascade fields → None even when mitigated
    assert _compute_cascade_cause({"title": "x"}, currently_mitigated=True) is None


def test_compute_cascade_cause_multi_cause_attribution():
    """T1 + SEC-10 (Phase 14.2 / T3 merge resolution): _compute_cascade_cause
    now returns a comma-separated list of ALL causes that fired, not just the
    first. Previously a first-match-wins elif chain attributed only one cause
    per call; now SIEM correlation sees the complete set."""
    from mcp_defectdojo.server import _compute_cascade_cause
    # is_mitigated=False + active=True both fire — both reported in order
    cause = _compute_cascade_cause(
        {"is_mitigated": False, "active": True},
        currently_mitigated=True,
    )
    assert cause == "explicit_field,active_side_effect"
    # All 5 cascade-fields together — all 5 in declaration order
    full = _compute_cascade_cause(
        {"is_mitigated": False, "active": True, "false_p": True,
         "duplicate": True, "out_of_scope": True},
        currently_mitigated=True,
    )
    assert full == "explicit_field,active_side_effect,false_p_side_effect,duplicate_side_effect,out_of_scope_side_effect"


# ---------------------------------------------------------------------------
# DOM-21 (Phase 14.2) — structured `_warning` shape and `note_attach_failure`
# audit event on close_finding / reopen_finding note-attach failure
# ---------------------------------------------------------------------------


async def test_close_finding_note_attach_failure_emits_structured_warning(
    patched_client, sample_finding, caplog
):
    """DOM-21: close_finding's inner note-attach failure produces a structured
    `_warning` dict in the response AND emits a `note_attach_failure` audit
    event whose `tool_name` is `close_finding`. The close itself succeeded —
    only the note attachment failed.
    """
    import logging as _logging
    from mcp_defectdojo.server import close_finding

    closed = dict(sample_finding, active=False, is_mitigated=True)
    patched_client.close_finding.return_value = closed
    patched_client.add_finding_note.side_effect = RuntimeError("note service down")

    with caplog.at_level(_logging.WARNING, logger="mcp_defectdojo.server"):
        result = await close_finding(
            finding_id=1, reason="mitigated", note="closure note"
        )

    data = json.loads(result)
    warning = data["_warning"]
    assert isinstance(warning, dict)
    assert warning == {
        "message": warning["message"],
        "note_attach_failed": True,
        "finding_id": 1,
    }
    assert "note failed" in warning["message"]
    assert "note service down" in warning["message"]

    audit = [
        r for r in caplog.records
        if getattr(r, "event_type", None) == "note_attach_failure"
        and getattr(r, "tool_name", None) == "close_finding"
    ]
    assert audit, "Expected a note_attach_failure audit event for close_finding"
    assert audit[0].finding_id == 1
    assert "note service down" in audit[0].reason


async def test_reopen_finding_note_attach_failure_emits_structured_warning(
    patched_client, sample_finding, caplog
):
    """DOM-21: reopen_finding's inner note-attach failure mirrors close_finding —
    structured `_warning` dict + `note_attach_failure` audit event whose
    `tool_name` is `reopen_finding`.
    """
    import logging as _logging
    from mcp_defectdojo.server import reopen_finding

    patched_client.update_finding.return_value = sample_finding
    patched_client.add_finding_note.side_effect = RuntimeError("note backend 503")

    with caplog.at_level(_logging.WARNING, logger="mcp_defectdojo.server"):
        result = await reopen_finding(finding_id=42, note="regressed")

    data = json.loads(result)
    warning = data["_warning"]
    assert isinstance(warning, dict)
    assert warning["note_attach_failed"] is True
    assert warning["finding_id"] == 42
    assert "note failed" in warning["message"]

    audit = [
        r for r in caplog.records
        if getattr(r, "event_type", None) == "note_attach_failure"
        and getattr(r, "tool_name", None) == "reopen_finding"
    ]
    assert audit, "Expected a note_attach_failure audit event for reopen_finding"
    assert audit[0].finding_id == 42
    assert "503" in audit[0].reason

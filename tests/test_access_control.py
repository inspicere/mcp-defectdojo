"""Tests for Phase 5 — Access Control & Hardening features.

Updated in Phase 8 to reflect RBAC role-based access control model.
"""
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import httpx
import pytest
import respx

from fastmcp.server.auth.authorization import AuthContext
from mcp_defectdojo.client import DefectDojoClient
from mcp_defectdojo.rbac import (
    Role,
    ROLE_PERMISSIONS,
    TOOL_PERMISSIONS,
    permission_check,
    build_rbac_auth,
)
from mcp_defectdojo.security import (
    MutationRateLimiter,
    validate_field_length,
    MAX_TITLE_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
)
from mcp_defectdojo.server import mcp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(role: str):
    """Create a mock AccessToken with a role stored in claims."""
    token = MagicMock()
    token.claims = {"role": role, "client_id": "test-client"}
    token.scopes = []
    return token


# ---------------------------------------------------------------------------
# permission_check — RBAC enforcement
# ---------------------------------------------------------------------------


def test_permission_check_allows_when_no_token():
    """No token → open access (AC-8.11)."""
    check = permission_check("finding_mgmt")
    ctx = AuthContext(token=None, component=MagicMock())
    assert check(ctx) is True


def test_permission_check_admin_can_do_everything():
    """Admin role has all permission groups."""
    ctx = AuthContext(token=_make_token("admin"), component=MagicMock())
    for group in ("system", "metadata_read", "product_mgmt", "engagement_mgmt", "finding_mgmt", "scan_mgmt"):
        assert permission_check(group)(ctx) is True, f"admin should have {group}"


def test_permission_check_reader_only_has_system_and_metadata():
    """Reader role has only system and metadata_read."""
    ctx = AuthContext(token=_make_token("reader"), component=MagicMock())
    assert permission_check("system")(ctx) is True
    assert permission_check("metadata_read")(ctx) is True
    assert permission_check("product_mgmt")(ctx) is False
    assert permission_check("engagement_mgmt")(ctx) is False
    assert permission_check("finding_mgmt")(ctx) is False
    assert permission_check("scan_mgmt")(ctx) is False


def test_permission_check_scanner_has_scan_mgmt():
    """Scanner role has scan_mgmt and metadata_read (AC-8.10)."""
    ctx = AuthContext(token=_make_token("scanner"), component=MagicMock())
    assert permission_check("scan_mgmt")(ctx) is True
    assert permission_check("metadata_read")(ctx) is True
    assert permission_check("finding_mgmt")(ctx) is False
    assert permission_check("product_mgmt")(ctx) is False


def test_permission_check_writer_lacks_product_mgmt():
    """Writer role has engagement/finding/scan_mgmt but NOT product_mgmt."""
    ctx = AuthContext(token=_make_token("writer"), component=MagicMock())
    assert permission_check("engagement_mgmt")(ctx) is True
    assert permission_check("finding_mgmt")(ctx) is True
    assert permission_check("scan_mgmt")(ctx) is True
    assert permission_check("product_mgmt")(ctx) is False


def test_permission_check_unknown_role_denies():
    """Unknown role in token claims → deny (AC-8.8 fail-safe)."""
    ctx = AuthContext(token=_make_token("superuser"), component=MagicMock())
    assert permission_check("metadata_read")(ctx) is False


# ---------------------------------------------------------------------------
# Scope enforcement — tool registration verification
# ---------------------------------------------------------------------------

READ_TOOLS = [
    "health_check", "list_products", "get_product",
    "list_engagements", "get_engagement",
    "list_tests", "get_test",
    "list_findings", "get_finding",
]

WRITE_TOOLS = [
    "create_product", "create_engagement", "create_test",
    "create_finding", "update_finding",
]


@pytest.mark.parametrize("tool_name", READ_TOOLS)
@pytest.mark.asyncio
async def test_read_tools_have_auth_set(tool_name):
    tools = await mcp.list_tools(run_middleware=False)
    tool_map = {t.name: t for t in tools}
    assert tool_name in tool_map, f"{tool_name} not found"
    assert tool_map[tool_name].auth is not None, f"{tool_name} should have auth set"


@pytest.mark.parametrize("tool_name", WRITE_TOOLS)
@pytest.mark.asyncio
async def test_write_tools_have_auth_set(tool_name):
    tools = await mcp.list_tools(run_middleware=False)
    tool_map = {t.name: t for t in tools}
    assert tool_name in tool_map, f"{tool_name} not found"
    assert tool_map[tool_name].auth is not None, f"{tool_name} should have auth set"


# ---------------------------------------------------------------------------
# build_rbac_auth — multi-token support (RBAC env vars)
# ---------------------------------------------------------------------------


def test_build_rbac_auth_single_legacy_token(monkeypatch):
    """MCP_AUTH_TOKEN → admin role token registered."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "full-access-token")
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in list(k for k in __import__("os").environ if k.startswith("MCP_ROLE_")):
        monkeypatch.delenv(key, raising=False)
    auth = build_rbac_auth()
    assert auth is not None
    assert "full-access-token" in auth.tokens
    assert auth.tokens["full-access-token"]["role"] == "admin"


def test_build_rbac_auth_dual_legacy_tokens(monkeypatch):
    """MCP_AUTH_TOKEN → admin, MCP_READ_TOKEN → reader."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "rw-token")
    monkeypatch.setenv("MCP_READ_TOKEN", "ro-token")
    for key in list(k for k in __import__("os").environ if k.startswith("MCP_ROLE_")):
        monkeypatch.delenv(key, raising=False)
    auth = build_rbac_auth()
    assert "rw-token" in auth.tokens
    assert "ro-token" in auth.tokens
    assert auth.tokens["rw-token"]["role"] == "admin"
    assert auth.tokens["ro-token"]["role"] == "reader"


def test_build_rbac_auth_role_env_var(monkeypatch):
    """MCP_ROLE_* env vars create tokens with specified roles."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ROLE_CI", "scan-token:scanner")
    monkeypatch.setenv("MCP_ROLE_ANALYST", "write-token:writer")
    auth = build_rbac_auth()
    assert auth is not None
    assert "scan-token" in auth.tokens
    assert auth.tokens["scan-token"]["role"] == "scanner"
    assert "write-token" in auth.tokens
    assert auth.tokens["write-token"]["role"] == "writer"


def test_build_rbac_auth_unknown_role_skipped(monkeypatch, caplog):
    """Unknown role in MCP_ROLE_* is skipped with WARNING (AC-8.8)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    monkeypatch.setenv("MCP_ROLE_BAD", "bad-token:superuser")
    import logging
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        auth = build_rbac_auth()
    assert auth is None or "bad-token" not in auth.tokens


def test_build_rbac_auth_no_tokens(monkeypatch):
    """No env vars → None (open-access mode)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in list(k for k in __import__("os").environ if k.startswith("MCP_ROLE_")):
        monkeypatch.delenv(key, raising=False)
    auth = build_rbac_auth()
    assert auth is None


# ---------------------------------------------------------------------------
# _build_auth backward-compat alias (T2 removed the alias; test uses build_rbac_auth directly)
# ---------------------------------------------------------------------------


def test_build_auth_compat_alias(monkeypatch):
    """build_rbac_auth() with MCP_AUTH_TOKEN returns a valid StaticTokenVerifier."""
    monkeypatch.setenv("MCP_AUTH_TOKEN", "alias-token")
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    auth = build_rbac_auth()
    assert auth is not None
    assert "alias-token" in auth.tokens


# ---------------------------------------------------------------------------
# TLS enforcement — client.py
# ---------------------------------------------------------------------------


def test_http_url_rejected_by_default(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "key")
    monkeypatch.delenv("ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(ValueError, match="TLS is required"):
        DefectDojoClient()


def test_http_url_allowed_with_env_override(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "key")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    client = DefectDojoClient()
    assert client.base_url == "http://dojo.local"


def test_https_url_accepted(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "key")
    client = DefectDojoClient()
    assert client.base_url == "https://dojo.local"


# ---------------------------------------------------------------------------
# Rate limiting — MutationRateLimiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    limiter = MutationRateLimiter(max_mutations=5, window_seconds=60)
    for _ in range(5):
        await limiter.check("caller-a")


@pytest.mark.asyncio
async def test_rate_limiter_rejects_over_limit():
    from fastmcp.exceptions import ToolError
    limiter = MutationRateLimiter(max_mutations=3, window_seconds=60)
    for _ in range(3):
        await limiter.check("caller-a")
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        await limiter.check("caller-a")


@pytest.mark.asyncio
async def test_rate_limiter_per_caller_isolation():
    limiter = MutationRateLimiter(max_mutations=2, window_seconds=60)
    await limiter.check("caller-a")
    await limiter.check("caller-a")
    await limiter.check("caller-b")
    await limiter.check("caller-b")


@pytest.mark.asyncio
async def test_rate_limiter_window_expiry():
    from fastmcp.exceptions import ToolError
    limiter = MutationRateLimiter(max_mutations=2, window_seconds=1)
    await limiter.check("caller-a")
    await limiter.check("caller-a")
    with pytest.raises(ToolError):
        await limiter.check("caller-a")
    await asyncio.sleep(1.1)
    await limiter.check("caller-a")


# ---------------------------------------------------------------------------
# Request size limits — validate_field_length
# ---------------------------------------------------------------------------


def test_field_length_validation_passes():
    validate_field_length("short", "title", MAX_TITLE_LENGTH)


def test_field_length_validation_rejects():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="exceeds maximum length"):
        validate_field_length("x" * 201, "title", MAX_TITLE_LENGTH)


def test_field_length_at_exact_boundary():
    validate_field_length("x" * MAX_TITLE_LENGTH, "title", MAX_TITLE_LENGTH)


def test_max_constants():
    assert MAX_TITLE_LENGTH == 200
    assert MAX_DESCRIPTION_LENGTH == 10000
    assert MAX_NAME_LENGTH == 200


# ---------------------------------------------------------------------------
# Dual API keys — client routing
# ---------------------------------------------------------------------------


def test_single_api_key_mode(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "single-key")
    monkeypatch.delenv("DEFECTDOJO_READ_API_KEY", raising=False)
    monkeypatch.delenv("DEFECTDOJO_WRITE_API_KEY", raising=False)
    client = DefectDojoClient()
    assert client._dual_key_mode is False
    assert client._read_client is client._write_client


def test_dual_api_key_mode(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    client = DefectDojoClient()
    assert client._dual_key_mode is True
    assert client._read_client is not client._write_client


def test_read_operations_use_read_client(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    client = DefectDojoClient()
    assert client._select_client("GET") is client._read_client
    assert client._select_client("HEAD") is client._read_client


def test_write_operations_use_write_client(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    client = DefectDojoClient()
    assert client._select_client("POST") is client._write_client
    assert client._select_client("PATCH") is client._write_client


@pytest.mark.asyncio
async def test_dual_key_aclose(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    client = DefectDojoClient()
    await client.aclose()


# ---------------------------------------------------------------------------
# Mutation rate limit env var validation
# ---------------------------------------------------------------------------


def test_parse_positive_int_valid(monkeypatch):
    from mcp_defectdojo.server import _parse_positive_int
    monkeypatch.setenv("TEST_VAR", "42")
    assert _parse_positive_int("TEST_VAR", 10) == 42


def test_parse_positive_int_default(monkeypatch):
    from mcp_defectdojo.server import _parse_positive_int
    monkeypatch.delenv("TEST_VAR", raising=False)
    assert _parse_positive_int("TEST_VAR", 99) == 99


def test_parse_positive_int_non_numeric(monkeypatch):
    from mcp_defectdojo.server import _parse_positive_int
    monkeypatch.setenv("TEST_VAR", "abc")
    with pytest.raises(ValueError, match="positive integer"):
        _parse_positive_int("TEST_VAR", 10)


def test_parse_positive_int_zero(monkeypatch):
    from mcp_defectdojo.server import _parse_positive_int
    monkeypatch.setenv("TEST_VAR", "0")
    with pytest.raises(ValueError, match="positive integer"):
        _parse_positive_int("TEST_VAR", 10)


def test_parse_positive_int_negative(monkeypatch):
    from mcp_defectdojo.server import _parse_positive_int
    monkeypatch.setenv("TEST_VAR", "-5")
    with pytest.raises(ValueError, match="positive integer"):
        _parse_positive_int("TEST_VAR", 10)

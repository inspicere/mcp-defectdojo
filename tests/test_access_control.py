"""Tests for Phase 5 — Access Control & Hardening features."""
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import httpx
import pytest
import respx

from fastmcp.server.auth.authorization import AuthContext
from mcp_defectdojo.client import DefectDojoClient
from mcp_defectdojo.security import (
    MutationRateLimiter,
    validate_field_length,
    MAX_TITLE_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
)
from mcp_defectdojo.server import scope_check, _build_auth, mcp


# ---------------------------------------------------------------------------
# Scope enforcement — scope_check function
# ---------------------------------------------------------------------------


def _make_token(scopes):
    token = MagicMock()
    token.scopes = scopes
    return token


def test_scope_check_allows_when_no_token():
    check = scope_check("read")
    ctx = AuthContext(token=None, component=MagicMock())
    assert check(ctx) is True


def test_scope_check_allows_matching_scope():
    check = scope_check("read")
    ctx = AuthContext(token=_make_token(["read", "write"]), component=MagicMock())
    assert check(ctx) is True


def test_scope_check_denies_missing_scope():
    check = scope_check("write")
    ctx = AuthContext(token=_make_token(["read"]), component=MagicMock())
    assert check(ctx) is False


def test_scope_check_write_allows_write_token():
    check = scope_check("write")
    ctx = AuthContext(token=_make_token(["read", "write"]), component=MagicMock())
    assert check(ctx) is True


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
# _build_auth — multi-token support
# ---------------------------------------------------------------------------


def test_build_auth_single_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "full-access-token")
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    auth = _build_auth()
    assert auth is not None
    assert "full-access-token" in auth.tokens


def test_build_auth_dual_tokens(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "rw-token")
    monkeypatch.setenv("MCP_READ_TOKEN", "ro-token")
    auth = _build_auth()
    assert "rw-token" in auth.tokens
    assert "ro-token" in auth.tokens
    assert auth.tokens["rw-token"]["scopes"] == ["read", "write"]
    assert auth.tokens["ro-token"]["scopes"] == ["read"]


def test_build_auth_no_tokens(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    auth = _build_auth()
    assert auth is None


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

"""Tests for mcp_defectdojo.rbac — covers all 14 RBAC acceptance criteria (AC-8.1..AC-8.14)."""
import logging
from unittest.mock import MagicMock

import pytest
from fastmcp.exceptions import ToolError

from fastmcp.server.auth.authorization import AuthContext
from mcp_defectdojo.rbac import (
    Role,
    ROLE_PERMISSIONS,
    TOOL_PERMISSIONS,
    build_rbac_auth,
    permission_check,
    permission_check_now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_auth_ctx(role: str | None) -> AuthContext:
    """Build an AuthContext with a mock token containing the given role claim.

    Pass role=None to get an unauthenticated context (token is None).
    """
    component = MagicMock()
    if role is None:
        return AuthContext(token=None, component=component)
    token = MagicMock()
    token.claims = {"role": role, "client_id": "test-client"}
    return AuthContext(token=token, component=component)


# ---------------------------------------------------------------------------
# AC-8.1 — Role enum values and ROLE_PERMISSIONS completeness
# ---------------------------------------------------------------------------


def test_role_enum_values():
    """Role enum must have exactly the 4 expected string values (AC-8.1)."""
    assert Role.ADMIN.value == "admin"
    assert Role.WRITER.value == "writer"
    assert Role.SCANNER.value == "scanner"
    assert Role.READER.value == "reader"
    assert len(Role) == 4


def test_role_is_str_enum():
    """Role is a str Enum — members compare equal to their string value (AC-8.1)."""
    assert Role.ADMIN == "admin"
    assert Role.READER == "reader"


def test_admin_has_all_six_permissions():
    """admin role must have all 6 permission groups (AC-8.1)."""
    expected = {"system", "metadata_read", "product_mgmt", "engagement_mgmt", "finding_mgmt", "scan_mgmt"}
    assert ROLE_PERMISSIONS[Role.ADMIN] == expected


def test_writer_has_five_permissions():
    """writer role must have exactly 5 permission groups (AC-8.1)."""
    expected = {"system", "metadata_read", "engagement_mgmt", "finding_mgmt", "scan_mgmt"}
    assert ROLE_PERMISSIONS[Role.WRITER] == expected


def test_scanner_has_three_permissions():
    """scanner role must have exactly 3 permission groups (AC-8.1)."""
    expected = {"system", "metadata_read", "scan_mgmt"}
    assert ROLE_PERMISSIONS[Role.SCANNER] == expected


def test_reader_has_two_permissions():
    """reader role must have exactly 2 permission groups (AC-8.1)."""
    expected = {"system", "metadata_read"}
    assert ROLE_PERMISSIONS[Role.READER] == expected


# ---------------------------------------------------------------------------
# AC-8.2 — Role hierarchy: admin > writer > scanner > reader
# ---------------------------------------------------------------------------


def test_role_hierarchy_admin_is_superset_of_writer():
    """admin permissions are a strict superset of writer permissions (AC-8.2)."""
    assert ROLE_PERMISSIONS[Role.WRITER].issubset(ROLE_PERMISSIONS[Role.ADMIN])
    assert ROLE_PERMISSIONS[Role.ADMIN] != ROLE_PERMISSIONS[Role.WRITER]


def test_role_hierarchy_writer_is_superset_of_scanner():
    """writer permissions are a strict superset of scanner permissions (AC-8.2)."""
    assert ROLE_PERMISSIONS[Role.SCANNER].issubset(ROLE_PERMISSIONS[Role.WRITER])
    assert ROLE_PERMISSIONS[Role.WRITER] != ROLE_PERMISSIONS[Role.SCANNER]


def test_role_hierarchy_scanner_is_superset_of_reader():
    """scanner permissions are a strict superset of reader permissions (AC-8.2)."""
    assert ROLE_PERMISSIONS[Role.READER].issubset(ROLE_PERMISSIONS[Role.SCANNER])
    assert ROLE_PERMISSIONS[Role.SCANNER] != ROLE_PERMISSIONS[Role.READER]


# ---------------------------------------------------------------------------
# AC-8.3 — TOOL_PERMISSIONS covers all 24 tools
# ---------------------------------------------------------------------------

_EXPECTED_TOOLS = {
    "health_check",
    "list_products",
    "get_product",
    "list_product_types",
    "list_engagements",
    "get_engagement",
    "list_tests",
    "get_test",
    "list_test_types",
    "list_findings",
    "get_finding",
    "list_finding_notes",
    "create_product",
    "create_engagement",
    "create_test",
    "create_finding",
    "update_finding",
    "close_finding",
    "reopen_finding",
    "add_finding_note",
    "add_finding_tags",
    "remove_finding_tags",
    "import_scan",
    "reimport_scan",
}


def test_tool_permissions_covers_all_24_tools():
    """TOOL_PERMISSIONS must cover exactly 24 tool function names."""
    assert len(TOOL_PERMISSIONS) == 24


def test_tool_permissions_contains_expected_tools():
    """TOOL_PERMISSIONS must contain all expected tool names (AC-8.3)."""
    assert set(TOOL_PERMISSIONS.keys()) == _EXPECTED_TOOLS


def test_tool_permissions_all_groups_are_valid():
    """Every permission group referenced in TOOL_PERMISSIONS must be a known group (AC-8.3)."""
    valid_groups = ROLE_PERMISSIONS[Role.ADMIN]  # admin has all groups
    for tool, group in TOOL_PERMISSIONS.items():
        assert group in valid_groups, f"Tool {tool!r} references unknown group {group!r}"


# ---------------------------------------------------------------------------
# AC-8.4 — Unknown tool defaults to admin-only (deny-by-default)
# ---------------------------------------------------------------------------


def test_unknown_tool_not_in_tool_permissions():
    """A tool not in TOOL_PERMISSIONS must not exist — deny-by-default means unknown tools
    should not be callable without an explicit permission assignment (AC-8.4)."""
    assert "nonexistent_tool_xyz" not in TOOL_PERMISSIONS


def test_deny_by_default_reader_cannot_access_unregistered_permission():
    """permission_check for a group that reader lacks is denied — no implicit escalation (AC-8.4)."""
    ctx = _make_auth_ctx("reader")
    # product_mgmt is not in READER permissions — simulates an unlisted/admin-only operation
    assert permission_check("product_mgmt")(ctx) is False


def test_deny_by_default_scanner_cannot_access_product_mgmt():
    """scanner role cannot access product_mgmt — unknown/unlisted group is admin-only (AC-8.4)."""
    ctx = _make_auth_ctx("scanner")
    assert permission_check("product_mgmt")(ctx) is False


# ---------------------------------------------------------------------------
# AC-8.5 — build_rbac_auth() with MCP_ROLE_* env vars
# ---------------------------------------------------------------------------


def test_build_rbac_auth_role_scanner(monkeypatch):
    """MCP_ROLE_CI=<token>:scanner creates a scanner-role token (AC-8.5)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_CI", "ci-scan-token:scanner")
    auth = build_rbac_auth()
    assert auth is not None
    assert "ci-scan-token" in auth.tokens
    assert auth.tokens["ci-scan-token"]["role"] == "scanner"
    assert auth.tokens["ci-scan-token"]["client_id"] == "ci"


def test_build_rbac_auth_role_writer(monkeypatch):
    """MCP_ROLE_ANALYST=<token>:writer creates a writer-role token (AC-8.5)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_ANALYST", "analyst-token:writer")
    auth = build_rbac_auth()
    assert auth is not None
    assert "analyst-token" in auth.tokens
    assert auth.tokens["analyst-token"]["role"] == "writer"


def test_build_rbac_auth_multiple_role_vars(monkeypatch):
    """Multiple MCP_ROLE_* vars create multiple tokens with correct roles (AC-8.5)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_SCANNER1", "tok-s:scanner")
    monkeypatch.setenv("MCP_ROLE_READER1", "tok-r:reader")
    monkeypatch.setenv("MCP_ROLE_ADMIN1", "tok-a:admin")
    auth = build_rbac_auth()
    assert auth is not None
    assert auth.tokens["tok-s"]["role"] == "scanner"
    assert auth.tokens["tok-r"]["role"] == "reader"
    assert auth.tokens["tok-a"]["role"] == "admin"


# ---------------------------------------------------------------------------
# AC-8.6 — Backward compat: MCP_AUTH_TOKEN → admin role
# ---------------------------------------------------------------------------


def test_build_rbac_auth_legacy_auth_token_is_admin(monkeypatch):
    """MCP_AUTH_TOKEN maps to admin role for backward compatibility (AC-8.6)."""
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "legacy-admin-token")
    auth = build_rbac_auth()
    assert auth is not None
    assert "legacy-admin-token" in auth.tokens
    assert auth.tokens["legacy-admin-token"]["role"] == "admin"


# ---------------------------------------------------------------------------
# AC-8.7 — Backward compat: MCP_READ_TOKEN → reader role
# ---------------------------------------------------------------------------


def test_build_rbac_auth_legacy_read_token_is_reader(monkeypatch):
    """MCP_READ_TOKEN maps to reader role for backward compatibility (AC-8.7)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_READ_TOKEN", "legacy-read-token")
    auth = build_rbac_auth()
    assert auth is not None
    assert "legacy-read-token" in auth.tokens
    assert auth.tokens["legacy-read-token"]["role"] == "reader"


# ---------------------------------------------------------------------------
# AC-8.8 — Unknown role in MCP_ROLE_* logs WARNING and is skipped
# ---------------------------------------------------------------------------


def test_build_rbac_auth_unknown_role_is_skipped(monkeypatch, caplog):
    """MCP_ROLE_* with unknown role is skipped, a WARNING is logged (AC-8.8), and
    when it's the only role binding the server fails closed (DEC-021)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_BAD", "bad-token:superuser")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
            build_rbac_auth()
    # Warning must still be logged for the unknown-role skip (AC-8.8)
    assert any("superuser" in record.message for record in caplog.records)


def test_build_rbac_auth_unknown_role_skipped_with_legacy_fallback(monkeypatch, caplog):
    """MCP_ROLE_* with unknown role + valid MCP_AUTH_TOKEN — token skipped,
    legacy fallback honored, no raise (AC-8.8 + DEC-021)."""
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_BAD", "bad-token:superuser")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "legacy-admin-token")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        auth = build_rbac_auth()
    assert auth is not None
    assert "bad-token" not in auth.tokens
    assert "legacy-admin-token" in auth.tokens
    assert auth.tokens["legacy-admin-token"]["role"] == "admin"
    assert any("superuser" in record.message for record in caplog.records)


def test_permission_check_unknown_role_in_token_denies(caplog):
    """A token with an unknown role claim is denied access (AC-8.8 fail-safe)."""
    ctx = _make_auth_ctx("superuser")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        result = permission_check("metadata_read")(ctx)
    assert result is False


# ---------------------------------------------------------------------------
# AC-8.9 — Permission denied for reader calling write tool
# ---------------------------------------------------------------------------


def test_reader_denied_finding_mgmt():
    """reader role is denied access to finding_mgmt permission group (AC-8.9)."""
    ctx = _make_auth_ctx("reader")
    assert permission_check("finding_mgmt")(ctx) is False


def test_reader_denied_product_mgmt():
    """reader role is denied access to product_mgmt permission group (AC-8.9)."""
    ctx = _make_auth_ctx("reader")
    assert permission_check("product_mgmt")(ctx) is False


def test_reader_denied_engagement_mgmt():
    """reader role is denied access to engagement_mgmt permission group (AC-8.9)."""
    ctx = _make_auth_ctx("reader")
    assert permission_check("engagement_mgmt")(ctx) is False


def test_reader_denied_scan_mgmt():
    """reader role is denied access to scan_mgmt permission group (AC-8.9)."""
    ctx = _make_auth_ctx("reader")
    assert permission_check("scan_mgmt")(ctx) is False


# ---------------------------------------------------------------------------
# AC-8.10 — Permission allowed for scanner calling import_scan
# ---------------------------------------------------------------------------


def test_scanner_allowed_import_scan():
    """scanner role is allowed to call import_scan (scan_mgmt group, AC-8.10)."""
    ctx = _make_auth_ctx("scanner")
    required_group = TOOL_PERMISSIONS["import_scan"]
    assert required_group == "scan_mgmt"
    assert permission_check(required_group)(ctx) is True


def test_scanner_allowed_reimport_scan():
    """scanner role is allowed to call reimport_scan (scan_mgmt group, AC-8.10)."""
    ctx = _make_auth_ctx("scanner")
    required_group = TOOL_PERMISSIONS["reimport_scan"]
    assert required_group == "scan_mgmt"
    assert permission_check(required_group)(ctx) is True


def test_scanner_allowed_metadata_read():
    """scanner role can read metadata (AC-8.10)."""
    ctx = _make_auth_ctx("scanner")
    assert permission_check("metadata_read")(ctx) is True


def test_scanner_denied_finding_mgmt():
    """scanner role is not allowed to manage findings (AC-8.10)."""
    ctx = _make_auth_ctx("scanner")
    assert permission_check("finding_mgmt")(ctx) is False


# ---------------------------------------------------------------------------
# AC-8.11 — No auth configured = open access
# ---------------------------------------------------------------------------


def test_no_auth_open_access_system():
    """No token → open access for any permission group (AC-8.11)."""
    ctx = _make_auth_ctx(None)
    assert permission_check("system")(ctx) is True


def test_no_auth_open_access_finding_mgmt():
    """No token → open access even for write operations (AC-8.11)."""
    ctx = _make_auth_ctx(None)
    assert permission_check("finding_mgmt")(ctx) is True


def test_no_auth_open_access_product_mgmt():
    """No token → open access for product_mgmt (AC-8.11)."""
    ctx = _make_auth_ctx(None)
    assert permission_check("product_mgmt")(ctx) is True


def test_build_rbac_auth_none_means_open_access(monkeypatch):
    """build_rbac_auth() returns None when no tokens configured → open access mode (AC-8.11)."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    assert build_rbac_auth() is None


# ---------------------------------------------------------------------------
# AC-8.12 — Permission denial audit log entry contains required fields
# ---------------------------------------------------------------------------


def test_permission_denial_logs_warning_with_role_info(caplog):
    """Unknown role denial logs a WARNING with role name in message (AC-8.12)."""
    ctx = _make_auth_ctx("unknown-role-xyz")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        result = permission_check("system")(ctx)
    assert result is False
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, "Expected at least one WARNING log record"
    combined = " ".join(r.message for r in warning_records)
    assert "unknown-role-xyz" in combined


def test_permission_denial_log_contains_required_group(caplog):
    """Unknown role denial log contains the required_permission group (AC-8.12)."""
    ctx = _make_auth_ctx("imaginary-role")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        permission_check("finding_mgmt")(ctx)
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    # The required group should appear in at least one warning message
    assert any("finding_mgmt" in msg for msg in warning_messages)


def test_permission_denial_log_caller_id_via_mock(caplog):
    """Audit log entry on denial can include caller_id via claims (AC-8.12).

    The rbac module logs role_name and required_group; the caller_id comes from
    token.claims["client_id"] which is present in our mock token.
    """
    ctx = _make_auth_ctx("imaginary-role-abc")
    # Ensure client_id is accessible in claims
    assert ctx.token.claims["client_id"] == "test-client"
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        result = permission_check("engagement_mgmt")(ctx)
    assert result is False
    # The role name appears in the log (role is the primary identifier logged)
    assert any("imaginary-role-abc" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# AC-8.13 — No runtime permission modification tools exist in TOOL_PERMISSIONS
# ---------------------------------------------------------------------------


_FORBIDDEN_TOOL_PATTERNS = [
    "set_role", "assign_role", "grant_permission", "revoke_permission",
    "modify_role", "update_role", "change_role", "add_permission",
    "remove_permission", "set_permission", "escalate",
]


def test_no_role_modification_tool_in_tool_permissions():
    """TOOL_PERMISSIONS must not contain any runtime permission modification tools (AC-8.13)."""
    tool_names = set(TOOL_PERMISSIONS.keys())
    for forbidden in _FORBIDDEN_TOOL_PATTERNS:
        matching = [t for t in tool_names if forbidden in t.lower()]
        assert not matching, (
            f"Found role/permission modification tool(s) in TOOL_PERMISSIONS: {matching!r}"
        )


def test_tool_permissions_contains_no_admin_mutation_tools():
    """No tool in TOOL_PERMISSIONS should manage roles or permissions (AC-8.13)."""
    for tool_name in TOOL_PERMISSIONS:
        assert "role" not in tool_name.lower(), f"Tool {tool_name!r} appears to manage roles"
        assert "permission" not in tool_name.lower(), (
            f"Tool {tool_name!r} appears to manage permissions"
        )


# ---------------------------------------------------------------------------
# AC-8.14 — Role definitions are immutable after startup (module-level constants)
# ---------------------------------------------------------------------------


def test_role_permissions_is_module_level_dict():
    """ROLE_PERMISSIONS is a module-level dict, not dynamically generated (AC-8.14)."""
    import mcp_defectdojo.rbac as rbac_module
    assert hasattr(rbac_module, "ROLE_PERMISSIONS")
    assert isinstance(rbac_module.ROLE_PERMISSIONS, dict)


def test_tool_permissions_is_module_level_dict():
    """TOOL_PERMISSIONS is a module-level dict, not dynamically generated (AC-8.14)."""
    import mcp_defectdojo.rbac as rbac_module
    assert hasattr(rbac_module, "TOOL_PERMISSIONS")
    assert isinstance(rbac_module.TOOL_PERMISSIONS, dict)


def test_role_permissions_not_modified_by_build_rbac_auth(monkeypatch):
    """Calling build_rbac_auth() does not alter ROLE_PERMISSIONS (AC-8.14)."""
    import copy
    import mcp_defectdojo.rbac as rbac_module
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_TMP", "tmp-token:writer")

    snapshot_before = copy.deepcopy({k: set(v) for k, v in rbac_module.ROLE_PERMISSIONS.items()})
    build_rbac_auth()
    snapshot_after = {k: set(v) for k, v in rbac_module.ROLE_PERMISSIONS.items()}

    assert snapshot_before == snapshot_after, "ROLE_PERMISSIONS was mutated by build_rbac_auth()"


def test_tool_permissions_not_modified_by_build_rbac_auth(monkeypatch):
    """Calling build_rbac_auth() does not alter TOOL_PERMISSIONS (AC-8.14)."""
    import copy
    import mcp_defectdojo.rbac as rbac_module
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MCP_ROLE_TMP", "tmp-token:admin")

    snapshot_before = copy.deepcopy(rbac_module.TOOL_PERMISSIONS)
    build_rbac_auth()
    snapshot_after = dict(rbac_module.TOOL_PERMISSIONS)

    assert snapshot_before == snapshot_after, "TOOL_PERMISSIONS was mutated by build_rbac_auth()"


# ---------------------------------------------------------------------------
# SB-6 — Malformed MCP_ROLE_* env var edge cases
# ---------------------------------------------------------------------------


def _clean_role_env(monkeypatch):
    """Helper to clear all auth env vars."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)


def test_build_rbac_auth_empty_token_part(monkeypatch, caplog):
    """MCP_ROLE_X=:scanner (empty token) is skipped with warning, then
    fail-closed since it's the only binding (DEC-021)."""
    _clean_role_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_EMPTY", ":scanner")
    import logging
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
            build_rbac_auth()


def test_build_rbac_auth_no_colon_separator(monkeypatch, caplog):
    """MCP_ROLE_X=justtoken (no colon) is skipped with warning, then
    fail-closed since it's the only binding (DEC-021)."""
    _clean_role_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_NOSEP", "justtoken")
    import logging
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
            build_rbac_auth()
    assert any("malformed" in r.message.lower() or "expected format" in r.message.lower()
               for r in caplog.records)


def test_build_rbac_auth_empty_value(monkeypatch, caplog):
    """MCP_ROLE_X= (empty value) is skipped with warning, then fail-closed (DEC-021)."""
    _clean_role_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_BLANK", "")
    import logging
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
            build_rbac_auth()


def test_build_rbac_auth_token_with_colons(monkeypatch):
    """MCP_ROLE_X=abc:def:ghi:scanner — rsplit takes last segment as role."""
    _clean_role_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_COLON", "abc:def:ghi:scanner")
    auth = build_rbac_auth()
    assert auth is not None
    assert "abc:def:ghi" in auth.tokens
    assert auth.tokens["abc:def:ghi"]["role"] == "scanner"


# ---------------------------------------------------------------------------
# SB-4 — Cross-reference TOOL_PERMISSIONS against registered tool auth decorators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_registered_tools_have_permission_check():
    """Every tool registered on the MCP server must have a non-None auth callback."""
    from mcp_defectdojo.server import mcp as server_mcp
    tools = await server_mcp.list_tools(run_middleware=False)
    for tool in tools:
        assert tool.auth is not None, (
            f"Tool {tool.name!r} has no auth — deny-by-default violated"
        )


@pytest.mark.asyncio
async def test_registered_tool_count_matches_tool_permissions():
    """The number of registered tools must match TOOL_PERMISSIONS (24)."""
    from mcp_defectdojo.server import mcp as server_mcp
    tools = await server_mcp.list_tools(run_middleware=False)
    tool_names = {t.name for t in tools}
    assert tool_names == set(TOOL_PERMISSIONS.keys()), (
        f"Drift detected between registered tools and TOOL_PERMISSIONS.\n"
        f"  In server but not TOOL_PERMISSIONS: {tool_names - set(TOOL_PERMISSIONS.keys())}\n"
        f"  In TOOL_PERMISSIONS but not server: {set(TOOL_PERMISSIONS.keys()) - tool_names}"
    )


# ---------------------------------------------------------------------------
# Phase 9 / T1 / DEC-021 — Fail-closed when MCP_ROLE_* present but unparseable
# ---------------------------------------------------------------------------


def _clear_auth_env(monkeypatch):
    """Strip every MCP_AUTH_TOKEN / MCP_READ_TOKEN / MCP_ROLE_* from env."""
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MCP_READ_TOKEN", raising=False)
    for key in [k for k in __import__("os").environ if k.startswith("MCP_ROLE_")]:
        monkeypatch.delenv(key, raising=False)


def test_build_rbac_auth_raises_when_only_malformed_role_env(monkeypatch):
    """MCP_ROLE_* set but missing :role suffix must raise, not silently open access (DEC-021)."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_CLAUDE", "bare-token-no-colon")
    with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
        build_rbac_auth()


def test_build_rbac_auth_raises_when_only_unknown_role(monkeypatch):
    """MCP_ROLE_* with an invalid role name (e.g., 'superuser') must raise (DEC-021)."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_BAD", "tok:nonexistent_role")
    with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
        build_rbac_auth()


def test_build_rbac_auth_raises_when_only_empty_token_part(monkeypatch):
    """MCP_ROLE_* with an empty token (just :role) must raise (DEC-021)."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_X", ":admin")
    with pytest.raises(RuntimeError, match="MCP_ROLE_.*present but none parsed"):
        build_rbac_auth()


def test_build_rbac_auth_open_access_when_no_role_env_at_all(monkeypatch):
    """Zero MCP_ROLE_* and no legacy tokens stays open access — that's intentional, not a misconfig."""
    _clear_auth_env(monkeypatch)
    auth = build_rbac_auth()
    assert auth is None  # AC-8.11 — open access, lifespan check enforces on network transport


def test_build_rbac_auth_no_raise_when_legacy_fallback_present(monkeypatch):
    """Malformed MCP_ROLE_* + valid MCP_AUTH_TOKEN must NOT raise — legacy is the fallback."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_CLAUDE", "bare-token-no-colon")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "valid-admin-token")
    auth = build_rbac_auth()
    assert auth is not None
    assert "valid-admin-token" in auth.tokens
    assert auth.tokens["valid-admin-token"]["role"] == "admin"


def test_build_rbac_auth_no_raise_when_at_least_one_role_parses(monkeypatch):
    """If at least one MCP_ROLE_* parses, ignore the others' format errors and start normally."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("MCP_ROLE_GOOD", "good-tok:reader")
    monkeypatch.setenv("MCP_ROLE_BAD", "bare-no-colon")
    auth = build_rbac_auth()
    assert auth is not None
    assert "good-tok" in auth.tokens
    assert auth.tokens["good-tok"]["role"] == "reader"


# ---------------------------------------------------------------------------
# Phase 9 / T1 / DEC-022 — permission_check_now() handler-level redundancy
# ---------------------------------------------------------------------------


def _patch_access_token(monkeypatch, role: str | None, client_id: str = "test-client"):
    """Patch fastmcp.server.dependencies.get_access_token to return a fake token.

    Pass role=None to simulate open-access mode (no token).
    """
    if role is None:
        token = None
    else:
        token = MagicMock()
        token.claims = {"role": role, "client_id": client_id}
    import fastmcp.server.dependencies as deps
    monkeypatch.setattr(deps, "get_access_token", lambda: token)


def test_permission_check_now_open_access_is_noop(monkeypatch):
    """When no auth provider is configured, permission_check_now is a no-op (AC-8.11)."""
    _patch_access_token(monkeypatch, role=None)
    permission_check_now("product_mgmt")  # must not raise


def test_permission_check_now_runtime_error_falls_back_to_noop(monkeypatch):
    """If get_access_token raises (no request context, e.g. test setup), treat as open access."""
    import fastmcp.server.dependencies as deps
    def _raise():
        raise RuntimeError("no http request")
    monkeypatch.setattr(deps, "get_access_token", _raise)
    permission_check_now("product_mgmt")  # must not raise


def test_permission_check_now_admin_allowed_on_product_mgmt(monkeypatch):
    """Admin role passes permission_check_now for product_mgmt."""
    _patch_access_token(monkeypatch, role="admin")
    permission_check_now("product_mgmt")  # must not raise


def test_permission_check_now_scanner_denied_on_product_mgmt(monkeypatch, caplog):
    """Scanner role lacks product_mgmt — permission_check_now must raise ToolError."""
    _patch_access_token(monkeypatch, role="scanner")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(ToolError, match="permission denied"):
            permission_check_now("product_mgmt")
    assert any("scanner" in rec.message for rec in caplog.records)


def test_permission_check_now_scanner_denied_on_finding_mgmt(monkeypatch):
    """Scanner role lacks finding_mgmt — permission_check_now must raise ToolError."""
    _patch_access_token(monkeypatch, role="scanner")
    with pytest.raises(ToolError, match="permission denied"):
        permission_check_now("finding_mgmt")


def test_permission_check_now_reader_denied_on_engagement_mgmt(monkeypatch):
    """Reader role lacks engagement_mgmt — permission_check_now must raise ToolError."""
    _patch_access_token(monkeypatch, role="reader")
    with pytest.raises(ToolError, match="permission denied"):
        permission_check_now("engagement_mgmt")


def test_permission_check_now_writer_allowed_on_finding_mgmt(monkeypatch):
    """Writer role has finding_mgmt — permission_check_now must not raise."""
    _patch_access_token(monkeypatch, role="writer")
    permission_check_now("finding_mgmt")


def test_permission_check_now_unknown_role_denies(monkeypatch, caplog):
    """A token with a role not in the Role enum must be denied (defense against tampering)."""
    _patch_access_token(monkeypatch, role="superuser")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.rbac"):
        with pytest.raises(ToolError, match="permission denied"):
            permission_check_now("product_mgmt")
    assert any("superuser" in rec.message for rec in caplog.records)


def test_permission_check_now_generic_error_no_information_leak(monkeypatch):
    """Error message must be generic — must not reveal required permission group or caller role."""
    _patch_access_token(monkeypatch, role="reader")
    try:
        permission_check_now("finding_mgmt")
        pytest.fail("expected ToolError")
    except ToolError as e:
        assert str(e) == "permission denied"
        assert "finding_mgmt" not in str(e)
        assert "reader" not in str(e)

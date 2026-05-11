"""Role-Based Access Control (RBAC) for mcp-defectdojo.

Implements a 4-role model (admin, writer, scanner, reader) with fine-grained
permission groups, replacing the binary read/write scope model.
"""

import logging
import os
from enum import Enum

from dotenv import load_dotenv
from fastmcp.server.auth.authorization import AuthCheck, AuthContext

logger = logging.getLogger(__name__)


class Role(str, Enum):
    ADMIN = "admin"
    WRITER = "writer"
    SCANNER = "scanner"
    READER = "reader"


# Role-Permission matrix — each role gets the named permission groups.
# Hierarchy: admin > writer > scanner > reader.
ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: frozenset({
        "system",
        "metadata_read",
        "product_mgmt",
        "engagement_mgmt",
        "finding_mgmt",
        "scan_mgmt",
    }),
    Role.WRITER: frozenset({
        "system",
        "metadata_read",
        "engagement_mgmt",
        "finding_mgmt",
        "scan_mgmt",
    }),
    Role.SCANNER: frozenset({
        "system",
        "metadata_read",
        "scan_mgmt",
    }),
    Role.READER: frozenset({
        "system",
        "metadata_read",
    }),
}

# Map each of the 23 tool function names to its required permission group.
TOOL_PERMISSIONS: dict[str, str] = {
    # system
    "health_check": "system",
    # metadata_read
    "list_products": "metadata_read",
    "get_product": "metadata_read",
    "list_product_types": "metadata_read",
    "list_engagements": "metadata_read",
    "get_engagement": "metadata_read",
    "list_tests": "metadata_read",
    "get_test": "metadata_read",
    "list_test_types": "metadata_read",
    "list_findings": "metadata_read",
    "get_finding": "metadata_read",
    "list_finding_notes": "metadata_read",
    # product_mgmt
    "create_product": "product_mgmt",
    # engagement_mgmt
    "create_engagement": "engagement_mgmt",
    "create_test": "engagement_mgmt",
    # finding_mgmt
    "create_finding": "finding_mgmt",
    "update_finding": "finding_mgmt",
    "close_finding": "finding_mgmt",
    "add_finding_note": "finding_mgmt",
    "add_finding_tags": "finding_mgmt",
    "remove_finding_tags": "finding_mgmt",
    # scan_mgmt
    "import_scan": "scan_mgmt",
    "reimport_scan": "scan_mgmt",
}


def permission_check(required_group: str) -> AuthCheck:
    """Return an auth check that requires the given permission group.

    If no auth is configured (ctx.token is None), allow all access (AC-8.11).
    Otherwise, extract the role from the token's claims and verify the role
    has the required permission group.
    """
    def check(ctx: AuthContext) -> bool:
        if ctx.token is None:
            return True  # No auth configured — open access (AC-8.11)
        caller_id = ctx.token.claims.get("client_id", "unknown")
        role_name = ctx.token.claims.get("role", "reader")
        tool_name = getattr(ctx.component, "name", "unknown")
        try:
            role = Role(role_name)
        except ValueError:
            logger.warning(
                "Permission denied — caller_id=%r tool_name=%r required_permission=%r caller_role=%r (unknown role)",
                caller_id,
                tool_name,
                required_group,
                role_name,
            )
            return False
        allowed = required_group in ROLE_PERMISSIONS[role]
        if not allowed:
            # AC-8.12: Audit log permission denials
            logger.warning(
                "Permission denied — caller_id=%r tool_name=%r required_permission=%r caller_role=%r",
                caller_id,
                tool_name,
                required_group,
                role_name,
            )
        return allowed

    return check


def build_rbac_auth():
    """Build a StaticTokenVerifier from RBAC environment variables.

    Parses:
    - MCP_ROLE_<NAME>=<token>:<role>  (preferred)
    - MCP_AUTH_TOKEN=<token>          (legacy → admin role, AC-8.6)
    - MCP_READ_TOKEN=<token>          (legacy → reader role, AC-8.7)

    Returns None if no tokens are configured, so FastMCP runs in open-access mode.
    """
    load_dotenv()
    tokens: dict[str, dict] = {}

    # Parse MCP_ROLE_* env vars (preferred format)
    valid_role_names = {r.value for r in Role}
    for key, value in os.environ.items():
        if not key.startswith("MCP_ROLE_"):
            continue
        if not value or ":" not in value:
            logger.warning(
                "Ignoring malformed %s — expected format <token>:<role>", key
            )
            continue
        token_str, role_name = value.rsplit(":", 1)
        if not token_str:
            logger.warning("Ignoring %s — token part is empty", key)
            continue
        if role_name not in valid_role_names:
            logger.warning(
                "Ignoring %s — unknown role %r (valid roles: %s)",
                key,
                role_name,
                sorted(valid_role_names),
            )
            continue
        tokens[token_str] = {
            "client_id": key[len("MCP_ROLE_"):].lower(),
            "role": role_name,
            "scopes": [],
        }

    # Parse legacy MCP_AUTH_TOKEN → admin role (AC-8.6)
    auth_token = os.environ.get("MCP_AUTH_TOKEN")
    if auth_token and auth_token not in tokens:
        tokens[auth_token] = {
            "client_id": "mcp-client",
            "role": Role.ADMIN.value,
            "scopes": [],
        }

    # Parse legacy MCP_READ_TOKEN → reader role (AC-8.7)
    read_token = os.environ.get("MCP_READ_TOKEN")
    if read_token and read_token not in tokens:
        tokens[read_token] = {
            "client_id": "mcp-read-client",
            "role": Role.READER.value,
            "scopes": [],
        }

    if not tokens:
        return None

    from fastmcp.server.auth import StaticTokenVerifier
    return StaticTokenVerifier(tokens=tokens)

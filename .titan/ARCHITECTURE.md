# Architecture — mcp-defectdojo

## Deployment Architecture
The MCP server will be deployed as a containerized service managed by systemd or a container orchestrator in the Laima network, with configuration injected via environment variables managed by Vault.

```text
+---------------------+
|   Laima Infrastructure|
|  +---------------+  |
|  |     Vault     |  |
|  +-------+-------+  |
|          |          |
|  +-------v-------+  |
|  |   MCP Server  |  |
|  |  (Container)  |  |
|  +---------------+  |
+---------------------+
```

## Security Architecture
- **Configuration:** API keys retrieved from HashiCorp Vault at runtime.
- **Isolation:** Service runs as a non-root user within the container.

## RBAC Architecture

### Role Model

```python
class Role(Enum):
    ADMIN = "admin"       # Full access — all permission groups
    WRITER = "writer"     # Engagement/finding/scan management + read
    SCANNER = "scanner"   # Scan import/reimport + read
    READER = "reader"     # Read-only access to all data
```

**Hierarchy:** admin > writer > scanner > reader. Higher roles include all permissions of lower roles.

### Permission Groups

| Group | Tools | Description |
|-------|-------|-------------|
| `system` | health_check | System operations |
| `metadata_read` | list_products, get_product, list_product_types, list_engagements, get_engagement, list_tests, get_test, list_test_types, list_findings, get_finding, list_finding_notes | Read any data |
| `product_mgmt` | create_product | Create/manage products |
| `engagement_mgmt` | create_engagement, create_test | Create engagements and tests |
| `finding_mgmt` | create_finding, update_finding, close_finding, add_finding_note, add_finding_tags, remove_finding_tags | Full finding lifecycle |
| `scan_mgmt` | import_scan, reimport_scan | Import scan results |

### Role-Permission Matrix

| Role | system | metadata_read | product_mgmt | engagement_mgmt | finding_mgmt | scan_mgmt |
|------|--------|---------------|--------------|-----------------|--------------|-----------|
| admin | x | x | x | x | x | x |
| writer | x | x | - | x | x | x |
| scanner | x | x | - | - | - | x |
| reader | x | x | - | - | - | - |

### Storage Approach — Environment Variables

Token-to-role binding is configured via environment variables, consistent with the existing pattern and Vault injection:

```bash
# New RBAC-style configuration (preferred)
MCP_ROLE_CI_SCANNER="token123:scanner"
MCP_ROLE_ANALYST="token456:writer"
MCP_ROLE_ADMIN="token789:admin"

# Legacy variables (backward-compatible)
MCP_AUTH_TOKEN="tokenABC"       # Mapped to admin role
MCP_READ_TOKEN="tokenDEF"      # Mapped to reader role
```

**Resolution order:**
1. Parse all `MCP_ROLE_*` env vars → extract token:role pairs
2. Parse legacy `MCP_AUTH_TOKEN` → map to admin (if not already claimed by a ROLE var)
3. Parse legacy `MCP_READ_TOKEN` → map to reader (if not already claimed)
4. Build the token registry: `{token: {client_id, role, permissions}}`

### Enforcement Layer

```text
Request → Token Extraction → Role Resolution → Permission Check → Tool Execution
                                    |                    |
                              token_registry        permission_map
                              {token → role}        {role → set[group]}

Permission resolution:
  1. Extract bearer token from request
  2. Look up role: token_registry[token] → Role
  3. Look up permissions: ROLE_PERMISSIONS[role] → set[permission_group]
  4. Check tool requirement: TOOL_PERMISSIONS[tool_name] → required_group
  5. If required_group in caller_permissions → allow
  6. Else → ToolError("Permission denied: requires {group}")
```

**Enhanced scope_check (replaces current implementation):**

```python
def permission_check(required_group: str) -> AuthCheck:
    """Check caller has the permission group needed for this tool."""
    def check(ctx: AuthContext) -> bool:
        if ctx.token is None:
            return True  # No auth configured = open access
        role = ctx.token.metadata.get("role", "reader")
        permissions = ROLE_PERMISSIONS[role]
        return required_group in permissions
    return check
```

### Migration Path

1. **Phase 1 (non-breaking):** Add `MCP_ROLE_*` env var parsing alongside existing `MCP_AUTH_TOKEN`/`MCP_READ_TOKEN`. Both work. New-style takes precedence if a token appears in both.
2. **Phase 2 (non-breaking):** Replace `scope_check("read")`/`scope_check("write")` with `permission_check("metadata_read")`/`permission_check("finding_mgmt")` etc. Existing tokens mapped to admin/reader continue working identically.
3. **Phase 3 (documentation):** Deprecate `MCP_AUTH_TOKEN`/`MCP_READ_TOKEN` in docs. Recommend `MCP_ROLE_*` pattern.

No breaking changes at any phase. Existing deployments continue working without configuration changes.

### Permission Resolution Flow

```text
                    +------------------+
                    | Incoming Request |
                    +--------+---------+
                             |
                    +--------v---------+
                    | Extract Token    |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     +--------v---------+        +---------v--------+
     | Token Found      |        | No Token (None)  |
     +--------+---------+        +---------+--------+
              |                             |
     +--------v---------+          +--------v--------+
     | Lookup in         |          | No auth config? |
     | token_registry    |          +--------+--------+
     +--------+---------+                    |
              |                     Yes: ALLOW ALL
     +--------v---------+          No: DENY (401)
     | Resolve Role      |
     +--------+---------+
              |
     +--------v---------+
     | Get Permission Set|
     | for Role          |
     +--------+---------+
              |
     +--------v---------+
     | Tool requires     |
     | group X?          |
     +--------+---------+
              |
       +------+------+
       |             |
  X in perms    X not in perms
       |             |
    ALLOW          DENY (403)
```

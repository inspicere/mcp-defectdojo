---
phase: 8
name: RBAC Implementation
goal: Implement Role-Based Access Control per Phase 7.3 design (FR-030 through FR-034)
branch: titan/phase-8-rbac-implementation
status: built
created: 2026-05-10T23:55:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 8 — RBAC Implementation — Execution Plan

## Goal
Replace the binary read/write scope model with a 4-role RBAC system (admin, writer, scanner, reader) using permission groups. Backward-compatible with existing `MCP_AUTH_TOKEN`/`MCP_READ_TOKEN` deployments.

## Context
- Design complete in Phase 7.3: ARCHITECTURE.md (role model, permission matrix, enforcement layer), REQUIREMENTS.md (FR-030–034, 14 acceptance criteria), DECISIONS.md (DEC-018–020)
- Current auth: `scope_check("read"/"write")` with `_build_auth()` parsing `MCP_AUTH_TOKEN` + `MCP_READ_TOKEN`
- 23 tools: 14 read-scope, 9 write-scope
- 302 existing tests, 2 auth-specific tests (`test_build_auth_no_token`, `test_build_auth_with_token`)
- FastMCP auth model: `@mcp.tool(auth=check_fn)` with `AuthContext` providing `ctx.token.scopes` and `ctx.token.metadata`

## Acceptance Criteria (This Phase)
All 14 ACs from FR-030 through FR-034 (AC-8.1 through AC-8.14).

## Tasks

### Task T1: RBAC Module — Role Model and Token Parsing

- **AC**: AC-8.1, AC-8.2, AC-8.3, AC-8.4, AC-8.5, AC-8.6, AC-8.7, AC-8.8, AC-8.14
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: `src/mcp_defectdojo/rbac.py`
- **Files to Read**: `.titan/ARCHITECTURE.md` (RBAC section), `.titan/REQUIREMENTS.md` (Phase 8 section)
- **Action**:
  1. Create `src/mcp_defectdojo/rbac.py` with:
     - `Role` enum: ADMIN, WRITER, SCANNER, READER
     - `ROLE_PERMISSIONS` dict mapping each Role to its set of permission group strings (hierarchical — admin gets all, writer gets engagement_mgmt+finding_mgmt+scan_mgmt+metadata_read+system, etc.)
     - `TOOL_PERMISSIONS` dict mapping each tool function name to its required permission group string
     - `permission_check(required_group: str) -> AuthCheck` function that replaces `scope_check`:
       - If `ctx.token is None`: return True (open access, AC-8.11)
       - Extract role from `ctx.token.metadata["role"]` (default "reader")
       - Check if `required_group` is in `ROLE_PERMISSIONS[role]`
       - Return True/False
     - `build_rbac_auth()` function that replaces `_build_auth()`:
       - Parse `MCP_ROLE_*` env vars (format: `<token>:<role>`)
       - Parse legacy `MCP_AUTH_TOKEN` → admin role (AC-8.6)
       - Parse legacy `MCP_READ_TOKEN` → reader role (AC-8.7)
       - Log WARNING and skip unknown role names (AC-8.8)
       - Return None if no tokens configured
       - Return `StaticTokenVerifier` with tokens dict including `metadata: {"role": role_name}`
  2. In `server.py`:
     - Replace `from .security import ...` line to also import from rbac
     - Replace `_build_auth()` call with `build_rbac_auth()` from the new module
     - Remove the old `scope_check()` function and `_build_auth()` function
     - Import `permission_check` from rbac module
- **Verification Steps**:
  1. `python -c "from mcp_defectdojo.rbac import Role, ROLE_PERMISSIONS, TOOL_PERMISSIONS, permission_check, build_rbac_auth"` succeeds
  2. `ROLE_PERMISSIONS[Role.ADMIN]` contains all 6 permission groups
  3. `ROLE_PERMISSIONS[Role.READER]` contains only `system` and `metadata_read`
  4. `TOOL_PERMISSIONS` has an entry for all 23 tool names
  5. `uv run pytest tests/ -q --tb=short` — existing tests still pass (auth tests may need update)
- **Done Criteria**: RBAC module exists with complete role model, permission maps, and auth builder. Old `scope_check`/`_build_auth` removed from server.py.
- **Dependencies**: none

### Task T2: Enforcement Migration — Replace scope_check with permission_check

- **AC**: AC-8.9, AC-8.10, AC-8.12, AC-8.13
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: `src/mcp_defectdojo/rbac.py` (for permission group names)
- **Action**:
  Replace all 23 `@mcp.tool(auth=scope_check("read"))` / `@mcp.tool(auth=scope_check("write"))` decorators with the appropriate `permission_check("<group>")`:
  - `health_check` → `permission_check("system")`
  - `list_products`, `get_product`, `list_product_types`, `list_engagements`, `get_engagement`, `list_tests`, `get_test`, `list_test_types`, `list_findings`, `get_finding`, `list_finding_notes` → `permission_check("metadata_read")`
  - `create_product` → `permission_check("product_mgmt")`
  - `create_engagement`, `create_test` → `permission_check("engagement_mgmt")`
  - `create_finding`, `update_finding`, `close_finding`, `add_finding_note`, `add_finding_tags`, `remove_finding_tags` → `permission_check("finding_mgmt")`
  - `import_scan`, `reimport_scan` → `permission_check("scan_mgmt")`

  Also add audit logging for permission denials (AC-8.12): in `permission_check()`, when returning False, log a WARNING with caller_id, tool_name, required_permission, and caller_role.
- **Verification Steps**:
  1. `grep 'scope_check' src/mcp_defectdojo/server.py` returns NO matches (fully migrated)
  2. `grep -c 'permission_check' src/mcp_defectdojo/server.py` returns 23 (one per tool)
  3. `uv run pytest tests/ -q --tb=short` — all tests pass
- **Done Criteria**: All 23 tools use permission_check with correct permission groups. No scope_check references remain.
- **Dependencies**: T1

### Task T3: RBAC Test Suite

- **AC**: AC-8.1 through AC-8.14 (comprehensive test coverage)
- **Mode**: agent
- **Files to Modify**: `tests/test_server.py` (update existing auth tests)
- **Files to Create**: `tests/test_rbac.py`
- **Files to Read**: `src/mcp_defectdojo/rbac.py`, `.titan/REQUIREMENTS.md` (Phase 8 ACs)
- **Action**:
  1. Create `tests/test_rbac.py` with tests for:
     - Role enum values and hierarchy (AC-8.1, AC-8.2)
     - ROLE_PERMISSIONS completeness — admin has all 6, writer has 4, scanner has 2, reader has 2 (AC-8.1)
     - TOOL_PERMISSIONS covers all 23 tools (AC-8.3)
     - Unknown tool defaults to admin-only (AC-8.4) — test via deny-by-default behavior
     - `build_rbac_auth()` with MCP_ROLE_* env vars (AC-8.5)
     - `build_rbac_auth()` backward compat with MCP_AUTH_TOKEN → admin (AC-8.6)
     - `build_rbac_auth()` backward compat with MCP_READ_TOKEN → reader (AC-8.7)
     - `build_rbac_auth()` unknown role logs WARNING and skips (AC-8.8)
     - Permission denied for reader calling write tool (AC-8.9)
     - Permission allowed for scanner calling import_scan (AC-8.10)
     - No auth configured = open access (AC-8.11)
     - Permission denial audit log entry (AC-8.12)
     - No runtime permission modification tools exist (AC-8.13)
     - Role definitions immutable after startup (AC-8.14)
  2. Update existing `test_build_auth_no_token` and `test_build_auth_with_token` in test_server.py to use `build_rbac_auth` instead of `_build_auth`.
- **Verification Steps**:
  1. `uv run pytest tests/test_rbac.py -v` — all RBAC tests pass
  2. `uv run pytest tests/ -q --tb=short` — full suite passes
  3. At least 14 new test functions exist (one per AC minimum)
- **Done Criteria**: Complete RBAC test suite covering all 14 acceptance criteria. Full test suite passes.
- **Dependencies**: T1, T2

## Execution Strategy

### Wave 1 — Foundation (T1)
T1 creates the RBAC module and rewires auth building. Must complete before T2 can migrate decorators.

### Wave 2 — Enforcement + Tests (T2, T3 parallel)
T2 migrates all decorators. T3 writes tests. These can execute in parallel since T3 tests the module from T1 directly, and T2's decorator changes don't conflict with T3's test file creation. Both depend only on T1.

## Boundaries — DO NOT MODIFY

- `.forgejo/` — CI workflows are out of scope
- `Dockerfile` — container image is out of scope
- `pyproject.toml` — no new dependencies needed (all stdlib + existing FastMCP)
- `.titan/` — TITAN state files updated only after completion
- `src/mcp_defectdojo/audit_logging.py` — logging infrastructure is stable
- `src/mcp_defectdojo/client.py` — API client is out of scope

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 | auto | Verify rbac.py module imports cleanly and existing tests pass |
| 2 | Wave 2 | human-verify | Review the full diff — this touches auth for all 23 tools |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| FastMCP StaticTokenVerifier doesn't support `metadata` field | Medium | High | Check FastMCP source for metadata support before implementation. If unsupported, use `scopes` list to encode role (e.g., scope = role name). |
| Existing auth tests break during migration | High | Low | Update them in T1 alongside the _build_auth removal. |
| permission_check needs tool name but AuthContext doesn't provide it | Medium | Medium | If AuthContext lacks tool name, the denial audit log (AC-8.12) can use a ContextVar set by the audit_tool decorator. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget
- [x] Total tasks ≤ 3

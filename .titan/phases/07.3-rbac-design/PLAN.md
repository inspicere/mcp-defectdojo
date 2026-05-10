---
phase: 7.3
name: RBAC Feature Design
goal: Specify Role-Based Access Control as a feature — design only, no implementation
branch: titan/phase-7.3-rbac-design
status: approved
created: 2026-05-10T23:45:00Z
estimated_tasks: 3
estimated_waves: 1
---

# Phase 7.3 — RBAC Feature Design — Execution Plan

## Goal
Design a Role-Based Access Control system for mcp-defectdojo. Produce requirements with acceptance criteria, architecture updates, and decision log entries. No code changes — design only.

## Context
- Current access control: binary read/write scopes via `scope_check()`, static tokens (`MCP_AUTH_TOKEN` + `MCP_READ_TOKEN`)
- Current tools: 23 total (14 read, 9 write). Write tools: `create_product`, `create_engagement`, `create_test`, `create_finding`, `update_finding`, `close_finding`, `import_scan`, `reimport_scan`, `add_finding_note`, `add_finding_tags`, `remove_finding_tags`
- Deployment: single-tenant (one DefectDojo instance), multi-caller (multiple MCP clients can connect)
- Regulatory context: NCUA-regulated financial services — audit trail already exists

## Acceptance Criteria (This Phase)
- AC-7.3.1: REQUIREMENTS.md updated with RBAC requirements and acceptance criteria
- AC-7.3.2: ARCHITECTURE.md updated with role model, permission scheme, and storage approach
- AC-7.3.3: DECISIONS.md has entries for key RBAC design choices

## Tasks

### Task T1: RBAC Requirements Specification

- **AC**: AC-7.3.1
- **Mode**: in-session
- **Files to Modify**: `.titan/REQUIREMENTS.md`
- **Files to Create**: none
- **Files to Read**: `src/mcp_defectdojo/server.py` (for tool list)
- **Action**: Add a new "Phase 8: RBAC" section to REQUIREMENTS.md with:
  - FR-030: Role Definition — define roles (admin, writer, reader, scanner) with permission sets
  - FR-031: Granular Permissions — per-tool-group permissions (product_mgmt, engagement_mgmt, finding_mgmt, scan_mgmt, metadata_read)
  - FR-032: Token-Role Binding — map static tokens to roles
  - FR-033: Permission Enforcement — decorator-based enforcement with descriptive errors
  - FR-034: Role Escalation Prevention — no role can grant permissions it doesn't hold
  - Each requirement must have explicit acceptance criteria in Given/When/Then format
- **Verification Steps**:
  1. REQUIREMENTS.md contains all 5 FR entries with AC in Given/When/Then format
  2. Every role has an explicit permission set listed
  3. Every tool is covered by at least one permission group
- **Done Criteria**: RBAC requirements are fully specified with testable acceptance criteria.
- **Dependencies**: none

### Task T2: RBAC Architecture Design

- **AC**: AC-7.3.2
- **Mode**: in-session
- **Files to Modify**: `.titan/ARCHITECTURE.md`
- **Files to Create**: none
- **Files to Read**: `src/mcp_defectdojo/server.py` (for current auth implementation)
- **Action**: Add an "RBAC Architecture" section to ARCHITECTURE.md with:
  - Role model: enum of roles with hierarchy (admin > writer > reader)
  - Permission scheme: mapping from roles to permission sets, permission sets to tools
  - Storage approach: environment-variable-based role-token mapping (aligns with current static token pattern)
  - Enforcement layer: enhanced `scope_check()` that resolves token → role → permissions → tool access
  - Migration path: how to upgrade from current read/write binary to RBAC without breaking existing deployments
  - Diagram showing the permission resolution flow
- **Verification Steps**:
  1. ARCHITECTURE.md contains the RBAC section with all components listed above
  2. The design is backward-compatible (existing `MCP_AUTH_TOKEN`/`MCP_READ_TOKEN` still work)
  3. Permission resolution is explicit (no implicit grants)
- **Done Criteria**: RBAC architecture is fully specified and implementable.
- **Dependencies**: T1 (needs requirements to design against)

### Task T3: RBAC Decision Log

- **AC**: AC-7.3.3
- **Mode**: in-session
- **Files to Modify**: `.titan/DECISIONS.md`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: Add decision entries for:
  - DEC-010: Why static token → role mapping over OAuth/OIDC (simplicity, single-tenant, no external IdP)
  - DEC-011: Why hierarchical roles over flat permission sets (simpler mental model, fewer tokens needed)
  - DEC-012: Why environment variables over config file for role definitions (consistency with existing pattern, Vault integration, container-friendly)
- **Verification Steps**:
  1. DECISIONS.md contains all 3 DEC entries
  2. Each entry has Context, Decision, Rationale, and Consequences sections
- **Done Criteria**: Key RBAC design decisions are documented with rationale.
- **Dependencies**: T1, T2 (decisions reference the design)

## Execution Strategy

### Wave 1 — Sequential in-session (T1 → T2 → T3)
Design documents build on each other: requirements inform architecture, both inform decisions.

## Boundaries — DO NOT MODIFY

- `src/` — no source code changes in a design phase
- `tests/` — no test changes
- `.forgejo/` — no CI changes
- `Dockerfile` — no container changes
- `pyproject.toml` — no project config changes

## Checkpoints

None — design documents are reviewed in verification.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Over-engineering the RBAC model | Medium | Low | Keep scope to what's needed for current 23 tools and known use cases |
| Design conflicts with FastMCP auth model | Low | Medium | Reference FastMCP's StaticTokenVerifier pattern as the base |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget
- [x] Total tasks ≤ 3

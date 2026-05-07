# Roadmap — mcp-defectdojo

## Phase Overview
Phase 1: Deployment Configuration  ████████████  [S] ✓
Phase 2: Audit Remediation         ████████████  [S] ✓
Phase 3.1: Input Validation & Pagination  ████████████  [S] ✓
Phase 3.2.1: Robustness & Logging  ░░░░░░░░░░  [S]
Phase 3.2.2: Test Coverage         ░░░░░░░░░░  [S]

## Phase 1: Deployment Configuration — Laima Network
**Goal:** Deploy the MCP server to the Laima network.
**Estimated Complexity:** S
**Status:** Complete
**Features:**
- FR-006: Containerization (Dockerfile)
- FR-007: Deployment automation (Ansible)
- FR-008: Health Check Endpoint
**Dependencies:** None
**Milestone:** ★ The MCP server runs as a managed service within the Laima infrastructure.

## Phase 2: Audit Remediation — Critical & Stability Fixes
**Goal:** Fix all critical audit findings and stabilize the client/server lifecycle.
**Estimated Complexity:** S
**Status:** Complete
**Features:**
- FR-009: Security Configuration (gitignore, Dockerfile non-root)
- FR-010: Client Lifecycle Management (async lifecycle, timeouts, error handling)
- FR-011: Server Lifespan Integration (deferred client, real health check)
**Dependencies:** Phase 1 complete
**Milestone:** ★ All 4 critical audit findings resolved. Server is production-stable.

## Phase 3.1: Input Validation & Pagination
**Goal:** Add input validation and pagination metadata so LLM agent consumers get reliable errors and can paginate results.
**Estimated Complexity:** S
**Status:** Complete (verified — PASS-WITH-NOTES)
**Features:**
- FR-012: Input Validation (severity enum, limit caps, ID bounds)
- FR-013: Pagination Metadata (total count, offset, limit in responses)
- Resolves: SB-01, SB-03, SB-05, SB-06, SB-07
**Dependencies:** Phase 2 complete
**Milestone:** ★ Invalid inputs rejected with clear errors; paginated responses include metadata.

## Phase 3.2.1: Robustness & Logging
**Goal:** Fix all robustness issues and add structured logging for audit trails.
**Estimated Complexity:** S
**Status:** Pending
**Features:**
- FR-014: Structured Logging (audit trail for mutations)
- Resolves: SA-001, SA-002, SA-01, SA-02, SA-03, SA-05, SA-06, SB-02, SB-03, SB-04, SB-07, SB-08, SB-10
**Dependencies:** Phase 3.1 complete
**Milestone:** ★ MCP server is robust and observable. All deferred findings resolved.

## Phase 3.2.2: Test Coverage
**Goal:** Establish test infrastructure and comprehensive test suite.
**Estimated Complexity:** S
**Status:** Pending
**Features:**
- SB-09: Test coverage (pytest infrastructure + test suite)
**Dependencies:** Phase 3.2.1 complete
**Milestone:** ★ MCP server has full test coverage. All important-severity audit recommendations met.

## Dependency Map
Phase 1 ──→ Phase 2 ──→ Phase 3.1 ──→ Phase 3.2.1 ──→ Phase 3.2.2

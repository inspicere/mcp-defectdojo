# Roadmap — mcp-defectdojo

## Phase Overview
Phase 1: Deployment Configuration  ████████████  [S] ✓
Phase 2: Audit Remediation         ░░░░░░░░░░  [S]
Phase 3: Quality Improvements      ░░░░░░░░░░  [S]

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
**Features:**
- FR-009: Security Configuration (gitignore, Dockerfile non-root)
- FR-010: Client Lifecycle Management (async lifecycle, timeouts, error handling)
- FR-011: Server Lifespan Integration (deferred client, real health check)
**Dependencies:** Phase 1 complete
**Milestone:** ★ All 4 critical audit findings resolved. Server is production-stable.

## Phase 3: Quality Improvements — Validation & Response Format
**Goal:** Add input validation, pagination metadata, and structured logging.
**Estimated Complexity:** S
**Features:**
- FR-012: Input Validation (severity enum, limit caps, ID bounds)
- FR-013: Pagination Metadata (total count, offset, limit in responses)
- FR-014: Structured Logging (audit trail for mutations)
**Dependencies:** Phase 2 complete
**Milestone:** ★ MCP server meets all important-severity audit recommendations.

## Dependency Map
Phase 1 ──→ Phase 2 ──→ Phase 3

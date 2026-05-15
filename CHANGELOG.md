# Changelog

All notable changes to mcp-defectdojo are documented in this file.

## [Unreleased]

### Planned — Phase 9 (Red Team Engagement 119 — Remediation Wave 2, 2026-05-14)

- TITAN Phase 9 planned (`.titan/phases/09-red-team-remediation-2/PLAN.md`) — 6 tasks, 4 waves, branch `titan/phase-9-red-team-remediation-2`. Targets all 11 still-open engagement-119 findings (2 Critical, 2 High, 7 Medium) including 3 residual bypasses (F-016/F-017/F-018) filed in Phase 2 verification.
- T1 investigation completed (`.titan/phases/09-red-team-remediation-2/INVESTIGATION-T1.md`) — root cause for F-001 / F-014 identified as a deployment misconfiguration (`MCP_ROLE_CLAUDE` set to bare token without `:role` suffix) combined with a silent fail-open in `build_rbac_auth()`. Prior STATE.md hypothesis (FastMCP `initialize`-bypass) corrected: FastMCP's `_get_tool` enforces `tool.auth` on every `tools/call`. Fix path: add fail-closed branch to `build_rbac_auth()` plus belt-and-suspenders `permission_check_now()` on the 5 highest-impact mutation tools. No source/test changes shipped this session — implementation deferred to T1 build phase.

### Security — Red Team Engagement Remediation (engagement 119)

- **F-013**: `import_scan` / `reimport_scan` returned HTTP 415 because the shared httpx client carried a `Content-Type: application/json` default that leaked into multipart POSTs. Removed the JSON default; httpx now sets the correct header per call (`json=...` → JSON, `files=...` → multipart with boundary).
- **F-008**: `update_finding` no longer lets a `finding_mgmt` caller clear `is_mitigated` to reopen a mitigated finding. Added `reopen_finding` tool requiring `engagement_mgmt` permission for the reopen flow.
- **F-015**: `update_finding` rejects mutually exclusive state combinations in the same request (`active=true + is_mitigated=true`, and `verified=true + active=false`).
- **F-003**: `FindingNote.author` accepts the nested `{id, username, first_name, last_name}` object DefectDojo actually returns (new `NoteAuthor` model). Previously raised `ValidationError` leaking schema and Pydantic version to callers.
- **F-012**: `client.get_finding_notes` extracts the `notes` key from the DefectDojo `{finding_id, notes:[...]}` wrapper (previously fell back to wrapping the envelope into a single bogus note).
- **F-011**: `client.remove_finding_tags` normalizes the empty-body success response (`{}`) into `{"tags": []}` so the response model no longer raises on successful removals.
- **F-005**: New `validate_no_secrets()` rejects values containing recognizable credential patterns (AWS keys, GitHub PATs, Slack tokens, PEM private keys, `*_API_KEY=`/`*_SECRET=`/`*_TOKEN=`/`*_PASSWORD=` assignments, bearer tokens) on every write tool that accepts user-controlled text.
- **F-006 / F-010**: `validate_tag()` rejects tag values containing any control character (0x00–0x1F, 0x7F) — closes newline-injection and ANSI-escape vectors.
- **F-009**: `validate_tag()` rejects tags containing commas, which DefectDojo silently splits server-side into multiple tags.

### Added

- `reopen_finding` MCP tool — `engagement_mgmt`-gated remediation-reversal path, complement to `close_finding`. Total tool count now 24.
- `NoteAuthor` Pydantic model for DefectDojo's nested note-author shape.
- `validate_tag()` and `validate_no_secrets()` in `security.py` with comprehensive test coverage.

## [3.0.0] — 2026-05-11

### Added
- **Role-Based Access Control (RBAC)**: 4-role permission model replacing binary read/write scopes
  - Roles: `admin` (all permissions), `writer` (engagement/finding/scan management), `scanner` (scan management + read), `reader` (read-only)
  - 6 permission groups: `system`, `metadata_read`, `product_mgmt`, `engagement_mgmt`, `finding_mgmt`, `scan_mgmt`
  - New `MCP_ROLE_<NAME>=<token>:<role>` env var format for fine-grained token-role binding
  - Permission denial audit logging with caller_id, tool_name, required_permission, caller_role
  - Deny-by-default: all 23 tools require explicit permission assignment
- `tests/test_rbac.py`: 55 RBAC-specific tests covering all 14 acceptance criteria
- `MutationRateLimiter` stale caller eviction (prevents unbounded memory growth)
- Integration test for session summary in lifespan teardown

### Changed
- **BREAKING**: Auth model upgraded from binary scopes (`read`/`write`) to role-based permissions. Existing `MCP_AUTH_TOKEN` maps to `admin` role and `MCP_READ_TOKEN` maps to `reader` role for backward compatibility.
- Lifespan security warning now correctly detects `MCP_ROLE_*` env vars (no longer triggers false alarm for RBAC-only deployments)
- `ROLE_PERMISSIONS` uses `frozenset` to enforce immutability at the language level
- `MCP_ROLE_*` env var parsing uses `rsplit(":", 1)` to correctly handle tokens containing colons

## [2.2.1] — 2026-05-10

### Fixed
- `add_finding_note` sending `note_type: 0` which DefectDojo rejected as invalid pk — changed to `int | None = None`, only included when explicitly set
- API error messages leaking DefectDojo field names and validation rules to MCP clients — added `_sanitize_api_error()` with generic messages per HTTP status code (400→"Invalid request parameters", 404→"Resource not found", etc.)
- `HTTPSLogHandler` accepting non-HTTP URL schemes (e.g., `file://`) — added scheme validation for defense in depth

### Security (CI hardening)
- Removed `curl -sk` TLS bypass in DefectDojo upload steps — CI now uses `--cacert` with internal CA certificate (Medium finding resolved)
- Added SHA256 hash verification for Gitleaks binary download in security workflow
- Pinned uv installer to version 0.11.5 in test workflow for supply chain integrity

### Improved
- `HTTPSLogHandler` logs WARNING when configured with `http://` scheme (defense in depth)
- `close_finding` returns result with `_warning` field on partial success (note attachment failure after successful close)
- `health_check` sanitizes error messages — returns generic response to clients, raw error logged server-side only

## [2.2.0] — 2026-05-10

### Added
- `import_scan` tool: upload scanner results (225+ scan types) via multipart form upload with base64 file content (50MB max)
- `reimport_scan` tool: re-upload results to existing test with `close_old_findings` support
- `list_product_types` tool: enumerate product types for use in `create_product`
- `list_test_types` tool: enumerate test types for use in `create_test`
- `close_finding` tool: close findings with reason (mitigated/false_positive/out_of_scope/duplicate) and optional note
- `add_finding_note` tool: attach notes to findings
- `list_finding_notes` tool: read notes on a finding
- `add_finding_tags` / `remove_finding_tags` tools: tag management on findings
- `ImportScanResult`, `ProductTypeSummary`, `TestTypeSummary`, `FindingNote` Pydantic models
- `_multipart_request` client method for multipart form uploads
- `_decode_file` helper for base64 file validation
- 96 new tests (302 total)

### Changed
- `list_findings` enhanced from 3 to 18 filter parameters (product_id, engagement_id, severity, active, verified, duplicate, false_p, out_of_scope, is_mitigated, risk_accepted, has_jira, tags, outside_of_sla, component_name, title)

### Fixed
- CI test workflow: Python install switched from apt to `uv python install` (node:22-slim lacks python3.X packages)
- CI security workflow: DefectDojo upload `scan_date` removed to avoid UTC/timezone "future date" errors
- CI security workflow: Gitleaks step uses `set +e` exit code handling instead of `continue-on-error: true`

## [2.1.0] — 2026-05-10

### Added
- SIEM log forwarding via syslog (TCP/UDP/TCP+TLS with RFC 5424 framing)
- SIEM log forwarding via HTTPS webhook with batching and background delivery
- `AUDIT_LOG_HTTPS_TOKEN` added to secret redaction list
- SIEM integration documentation in README

## [2.0.0] — 2026-05-09

### Added
- Structured JSON audit logging with correlation IDs and retention class tagging
- HMAC-SHA256 integrity chain for tamper-evident audit log records
- Per-tool audit decorator capturing caller identity, request params, and outcomes
- Scope-based access control (read/write) with per-tool enforcement
- Mutation rate limiting (configurable window and max calls)
- TLS enforcement for DefectDojo API connections (with explicit opt-out)
- Secret redaction in all log output (API keys, auth tokens, HMAC keys)
- Log export to file with configurable path
- Session summary logging on shutdown (tool call counts, error rates)
- `pip-audit` vulnerability scanning in CI
- Python 3.13 CI test matrix

### Changed
- Switched to streamable-http MCP transport (from SSE)
- Docker base image pinned by digest for reproducibility
- Finding titles truncated in audit logs for privacy

### Fixed
- Dockerfile runtime permission errors (cache dirs, uv sync)
- README quickstart env file path
- `uv` version pinned in CI workflow

## [1.0.0] — 2026-05-07

### Added
- 14 MCP tools: products, engagements, tests, findings (CRUD + list)
- Health check tool for connectivity verification
- Pydantic response models with strict validation
- Input validation (date formats, severity values, numeric ranges)
- Pagination with configurable limits
- Structured logging for client operations
- Docker container deployment
- 182 unit tests at 96% coverage
- MIT license

### Fixed
- URL validation and TLS warnings
- Null client reference after close
- `locals()` removed from error context (security)
- Bearer auth for MCP transport

# Roadmap — mcp-defectdojo

## Phase Overview
Phase 1: Deployment Configuration  ████████████  [S] ✓
Phase 2: Audit Remediation         ████████████  [S] ✓
Phase 3.1: Input Validation & Pagination  ████████████  [S] ✓
Phase 3.2.1: Robustness & Logging  ████████████  [S] ✓
Phase 3.2.2: Test Coverage         ████████████  [S] ✓

### Milestone v2.0 — Regulatory-Grade Audit Logging & Hardening
Phase 4.1: Structured Log Infrastructure  ████████████  [S] ✓
Phase 4.2: Audit Coverage & Identity      ████████████  [S] ✓
Phase 5: Access Control & Hardening       ████████████  [M] ✓
Phase 6: Log Integrity & Export           ████████████  [S] ✓

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
**Status:** Complete (verified 2026-05-07 — PASS-WITH-NOTES)
**Features:**
- FR-014: Structured Logging (audit trail for mutations)
- Resolves: SA-001, SA-002, SA-01, SA-02, SA-03, SA-05, SA-06, SB-02, SB-03, SB-04, SB-07, SB-08, SB-10
**Dependencies:** Phase 3.1 complete
**Milestone:** ★ MCP server is robust and observable. All deferred findings resolved.

## Phase 3.2.2: Test Coverage
**Goal:** Establish test infrastructure and comprehensive test suite.
**Estimated Complexity:** S
**Status:** Complete (verified 2026-05-07 — PASS-WITH-NOTES, 88% coverage)
**Features:**
- SB-09: Test coverage (pytest infrastructure + test suite)
- 77 tests across 3 files (test_models.py, test_client.py, test_server.py)
- Coverage: client 100%, models 100%, server 80%, overall 88%
**Dependencies:** Phase 3.2.1 complete
**Milestone:** ★ MCP server has full test coverage. All important-severity audit recommendations met.

## Phase 4.1: Structured Log Infrastructure
**Goal:** Replace unstructured text logging with structured JSON output, configurable log levels, and sensitive data redaction.
**Estimated Complexity:** S
**Status:** Complete (verified 2026-05-08 — PASS-WITH-NOTES)
**Features:**
- FR-015 (partial): Structured JSON log format — every log line is a single JSON object with standardized fields (timestamp, level, logger, message, event_type)
- FR-020: Configurable log levels — support LOG_LEVEL env var (DEBUG/INFO/WARNING/ERROR). Default to INFO in production. DEBUG includes full request/response bodies (with API key redaction).
- FR-021: Sensitive data redaction — ensure API keys, tokens, and credentials never appear in log output. Redact Authorization headers in debug-level request logging.
**Dependencies:** v1.0.0 complete
**Milestone:** ★ All log output is structured JSON. Log levels are configurable. Secrets are redacted.

## Phase 4.2: Audit Coverage & Identity
**Goal:** Every tool invocation produces a complete audit record with caller identity, correlation ID, timing, and full read trail — sufficient for NCUA Part 748 / FFIEC examination evidence.
**Estimated Complexity:** S
**Status:** Complete (verified 2026-05-08 — PASS-WITH-NOTES)
**Features:**
- FR-015 (complete): Full structured audit fields (tool_name, caller_id, request_params, response_summary, duration_ms, outcome) on every tool call
- FR-016: Full read audit trail — all `list_*` and `get_*` operations logged at INFO level, not just mutations. "Who accessed what vulnerability data, when" must be answerable from logs alone.
- FR-017: Correlation IDs — generate a unique request_id per tool invocation, propagate to the DefectDojo API call. Thread through both server.py and client.py log entries for end-to-end tracing.
- FR-018: Request duration tracking — measure wall-clock time for each tool invocation and each upstream API call. Log both.
- FR-019: Caller identity extraction — extract client_id from MCP auth token (already available via StaticTokenVerifier scopes). Log it on every request. If no auth token, log as "anonymous" with a warning.
**Dependencies:** Phase 4.1 complete
**Milestone:** ★ Every tool call produces a structured audit record. Log output is ready for ingestion by Loki/ELK/Splunk. An examiner can reconstruct a complete access timeline from logs alone.

## Phase 5: Access Control & Hardening
**Goal:** Implement granular access controls, enforce TLS, and add security headers — meeting the "principle of least privilege" and "defense in depth" expectations of FFIEC IT Examination Handbook.
**Estimated Complexity:** M
**Status:** Complete (verified 2026-05-08 — PASS-WITH-NOTES)
**Features:**
- FR-022: Scoped tool authorization — MCP auth scopes ("read", "write") enforced per-tool. Read-scoped tokens can call list_*/get_* but not create_*/update_*. Currently scopes are declared but not enforced.
- FR-023: Separate read/write API keys — support DEFECTDOJO_READ_API_KEY and DEFECTDOJO_WRITE_API_KEY. Read operations use the read-only key. Mutations use the write key. Limits blast radius of key compromise. (Resolves deferred SEC-05 / Vikunja #260)
- FR-024: TLS enforcement — reject DEFECTDOJO_URL with http:// scheme unless ALLOW_INSECURE_HTTP=true is explicitly set. Log a critical warning if insecure mode is enabled. Default to secure.
- FR-025: Rate limiting — per-client rate limits on mutation operations (create_*, update_*) to prevent abuse or runaway automation. Configurable via env vars (default: 60 mutations/minute).
- FR-026: Request size limits — cap description and title field lengths at the server validation layer before forwarding to DefectDojo. Prevents DoS via oversized payloads.
- FR-027: Security response headers — if serving over HTTP transport, add X-Content-Type-Options, X-Frame-Options, Cache-Control: no-store on API responses containing vulnerability data.
**Dependencies:** Phase 4 complete (audit logging must be in place before adding access controls — need to log authorization decisions)
**Milestone:** ★ Tool access is scoped by credential. TLS is enforced by default. The server implements defense-in-depth controls appropriate for a system handling vulnerability management data.

## Phase 6: Log Integrity & Export
**Goal:** Ensure audit logs are tamper-evident, exportable, and retainable — closing the loop on regulatory evidence requirements for NCUA/FFIEC examinations.
**Estimated Complexity:** S
**Status:** Complete (verified 2026-05-08 — PASS-WITH-NOTES)
**Features:**
- FR-028: Structured log export — write audit logs to a dedicated file (configurable path) in addition to stdout. Support log rotation via standard mechanisms (logrotate-compatible). JSON-lines format for direct ingestion.
- FR-029: Log integrity checksums — append a rolling HMAC-SHA256 chain to each log entry. Each entry's hash includes the previous entry's hash, creating a tamper-evident chain. Verification tool included.
- FR-030: Session audit summary — on server shutdown (lifespan teardown), emit a summary log entry: total requests served, breakdown by tool, error count, uptime duration. Provides a per-session audit bookmark.
- FR-031: Retention metadata — include `retention_class` field in each log entry (e.g., "security_audit", "operational"). Allows downstream log management to apply different retention policies per NCUA Part 748 record retention requirements.
- FR-032: Audit log test suite — comprehensive tests validating log format, required fields present, redaction works, integrity chain verifiable, rotation doesn't break chain.
**Dependencies:** Phase 5 complete
**Milestone:** ★ Audit logs are tamper-evident, exportable, and carry retention metadata. The system produces examination-ready evidence without manual log processing.

## Post-Ship: Post-TLS Audit (2026-05-09)
**Goal:** Address all remaining findings from the post-TLS 12-dimension audit.
**Status:** Complete — all 7 findings remediated in commits `c215f7e` and `dc3daa5`.
**Findings resolved:**
- [Medium] `pip-audit` vulnerability scanning added to CI
- [Medium] Finding `title` added to audit log truncation fields (privacy)
- [Low] README quickstart env file path corrected
- [Low] `uv` version pinned in CI workflow
- [Low] Python 3.13 added to CI test matrix
- [Low] CHANGELOG.md created with v1.0.0 and v2.0.0 entries
- [Low] Docker base image pinned by sha256 digest

## Post-Ship: CI/CD Workflow Fixes (2026-05-10)
**Goal:** Fix 3 CI workflow failures blocking green builds.
**Status:** Complete — commit `12c1be6`, both workflows green.
**Fixes:**
- Python install switched from apt to `uv python install` (node:22-slim lacks python3.X packages)
- DefectDojo upload `scan_date` removed (UTC/timezone mismatch caused "future date" error)
- Gitleaks step changed from `continue-on-error: true` to `set +e` exit code handling

## v2.2.0 — Feature Expansion (2026-05-10)
**Goal:** Add scan import/reimport, finding lifecycle tools, metadata lookups, and enhanced filtering.
**Status:** Complete — all 4 feature sets implemented and merged to main.
**Stats:** Tools 14→23 (+9), Tests 206→302 (+96), all passing.

### Scan Import/Reimport (Tier 1 — commit `124cf73`)
- `import_scan`: upload scanner results (225+ types), multipart form upload, base64 file content, 50MB max
- `reimport_scan`: re-upload to existing test, supports close_old_findings
- `_multipart_request` client method, `_decode_file` base64 validator, `ImportScanResult` model
- Full parameter support: product_name, engagement_name, auto_create_context, close_old_findings, version, branch_tag, commit_hash, tags, group_by, minimum_severity
- 29 new tests

### Metadata Lookup Tools (Tier 1 — commit `c22bd1c`)
- `list_product_types`: enumerate product types for use in create_product
- `list_test_types`: enumerate test types for use in create_test
- `ProductTypeSummary` and `TestTypeSummary` models
- 18 new tests

### Finding Lifecycle Tools (Tier 2 — commit `e27a5dd`)
- `close_finding`: close with reason (mitigated/false_positive/out_of_scope/duplicate) + optional note
- `add_finding_note`: attach notes to findings
- `list_finding_notes`: read notes on a finding
- `add_finding_tags` / `remove_finding_tags`: tag management
- `FindingNote` model, 6 client methods
- 35 new tests

### Enhanced list_findings Filters (Tier 2 — commit `36cc453`)
- Enhanced from 3 to 18 filter parameters
- New: product_id, engagement_id, severity, active, verified, duplicate, false_p, out_of_scope, is_mitigated, risk_accepted, has_jira, tags, outside_of_sla, component_name, title
- 14 new tests

## Post-Ship: Bug Fixes & Finding Closure (2026-05-10)
**Goal:** Fix bugs discovered during production use and close all DefectDojo findings.
**Status:** Complete — commits `ef932f7` and `b9b1e8d`.
**Fixes:**
- `add_finding_note` note_type defaulted to 0 (invalid pk), changed to `None` with conditional inclusion
- API error messages leaked field names/validation rules to MCP clients — added `_sanitize_api_error()` with generic messages per HTTP status code
- `HTTPSLogHandler` accepted non-HTTP URL schemes — added scheme validation
**Findings closed:** #933 (rate limiting), #934 (error leakage), #971 (shared API key), #1926 (dynamic urllib). Zero open findings.

## Planned: v3.0.0 — Operational Features
**Goal:** Tier 3 operational features and remaining gaps.
**Status:** Not started.
**Candidates:**
- JIRA push configuration
- SLA configuration
- Metrics/statistics endpoints
- Bulk finding operations
- Product/engagement update tools

## Dependency Map
Phase 1 ──→ Phase 2 ──→ Phase 3.1 ──→ Phase 3.2.1 ──→ Phase 3.2.2
                                                            │
                                                            ▼
                                          Phase 4.1 ──→ Phase 4.2 ──→ Phase 5 ──→ Phase 6

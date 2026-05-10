# Changelog

All notable changes to mcp-defectdojo are documented in this file.

## [Unreleased]

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

# Changelog

All notable changes to mcp-defectdojo are documented in this file.

## [Unreleased]

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

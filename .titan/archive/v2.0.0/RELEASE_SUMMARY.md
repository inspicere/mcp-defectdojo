# Release v2.0.0 — mcp-defectdojo

## What Was Built

### Phase 4.1 — Structured Log Infrastructure
- Structured JSON logging via StructuredJsonFormatter — every log line is machine-parseable
- Configurable log levels via LOG_LEVEL env var (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- RedactingFilter ensures API keys and tokens never appear in log output
- Tasks: 3/3 completed | Verdict: PASS-WITH-NOTES

### Phase 4.2 — Audit Coverage & Identity
- audit_tool decorator on all 14 tools — request_id, caller_id, duration_ms, outcome tracking
- ContextVar-based request_id propagation from server to client layer
- Caller identity extraction from FastMCP Context (client_id or "anonymous" with warning)
- Tasks: 3/3 completed | Verdict: PASS-WITH-NOTES

### Phase 5 — Access Control & Hardening
- Per-tool scope enforcement (read/write) via FastMCP auth parameter
- TLS enforcement by default — http:// rejected unless ALLOW_INSECURE_HTTP=true
- Mutation rate limiting (60/min per caller via sliding window)
- Request size limits (title 200 chars, description 10K chars, name 200 chars)
- Dual API key support (DEFECTDOJO_READ_API_KEY / DEFECTDOJO_WRITE_API_KEY)
- Tasks: 3/3 completed + 1 added (SB-01 fix) | Verdict: PASS-WITH-NOTES

### Phase 6 — Log Integrity & Export
- HMAC-SHA256 integrity chain — tamper-evident audit log with rolling hash
- Dedicated audit log file via WatchedFileHandler (logrotate-compatible)
- Retention metadata (security_audit / operational / debug) per log entry
- Session shutdown summary (total requests, per-tool breakdown, error count, uptime)
- Tasks: 3/3 completed + 1 added (SB-02 fix) | Verdict: PASS-WITH-NOTES

### Pre-Ship Audit Fixes
- 7 audit findings resolved: pagination logic defect, inspect.signature caching,
  IntegrityChainFormatter JSON round-trip elimination, RedactingFilter secret caching,
  ephemeral HMAC key warning, auth-disabled network transport warning, 6 missing happy-path tests

## Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 9 | stdlib logging, not structlog | No new dependency; existing logger pattern sufficient |
| 10 | Per-tool auth via FastMCP `auth` param | Auto-skips auth on stdio, enforces on HTTP/SSE |
| 11 | Custom mutation-only rate limiter | FastMCP's built-in applies globally; we only limit writes |
| 12 | FR-027 (security headers) deferred to reverse proxy | FastMCP manages HTTP app internally |

## Known Limitations
- SSRF: Private/loopback IP ranges not blocked in URL validation (requires operator access)
- Rate limiter: Anonymous callers share a single bucket
- MutationRateLimiter._windows: Empty deques not evicted (negligible for few callers)
- ConnectError messages may expose infrastructure URLs
- TestSummary model name triggers PytestCollectionWarning
- found_by: [1] hardcoded in create_finding

## Metrics
- Phases completed: 4 (4.1, 4.2, 5, 6)
- Total tasks: 12 planned, 12 completed, 0 deferred, 2 added in-session
- Test suite: 182 tests, all passing
- Verification findings: 21 total (0 critical, 2 important fixed in-session, 19 minor/accepted)
- Pre-ship audit: Score B (up from D+ at v1.0), 7 important findings fixed
- Dependencies: 0 CVEs (pip-audit clean)
- Knowledge items: 6 pattern categories, 30+ learnings captured

## Deferred to Future
- DOM-04: Auto-pagination mechanism (Vikunja #259)
- svc-mcp role elevation for product creation (Vikunja #264)
- SB-02 (Phase 5): MutationRateLimiter memory cleanup for many callers
- SB-05 (Phase 5): ConnectError may leak infrastructure URLs
- SA-01/SB-05 (Phase 6): Integration test for session summary in lifespan teardown

# TITAN State

## Current Position
- Phase: —
- Step: shipped
- Status: milestone complete
- Last Action: Released v2.0.0
- Updated: 2026-05-09

## Completed Milestones
| Version | Phases | Date | Notes |
|---------|--------|------|-------|
| v1.0.0 | 01, 02, 03.1, 03.2.1, 03.2.2 | 2026-05-07 | Initial release — MCP server for DefectDojo with 14 tools, full test suite, B- audit score |
| v2.0.0 | 4.1, 4.2, 5, 6 | 2026-05-09 | Regulatory-grade audit logging & hardening — structured JSON logging, HMAC integrity chain, per-tool auth, TLS enforcement, rate limiting, 182 tests, B audit score |

## Completed Phases
| Phase | Name | Status | Date | Milestone |
|-------|------|--------|------|-----------|
| 01 | Deployment Configuration | complete | 2026-05-04 | v1.0.0 |
| 02 | Audit Remediation | verified | 2026-05-07 | v1.0.0 |
| 03.1 | Input Validation & Pagination | verified | 2026-05-07 | v1.0.0 |
| 03.2.1 | Robustness & Logging | verified | 2026-05-07 | v1.0.0 |
| 03.2.2 | Test Coverage | verified | 2026-05-07 | v1.0.0 |
| 4.1 | Structured Log Infrastructure | verified | 2026-05-08 | v2.0.0 |
| 4.2 | Audit Coverage & Identity | verified | 2026-05-08 | v2.0.0 |
| 5 | Access Control & Hardening | verified | 2026-05-08 | v2.0.0 |
| 6 | Log Integrity & Export | verified | 2026-05-08 | v2.0.0 |

## Active Decisions
(none)

## Deferred Items
- DOM-04: Auto-pagination mechanism (Vikunja #259)
- svc-mcp role elevation for product creation (Vikunja #264)
- SB-02 (Phase 5): MutationRateLimiter memory cleanup for many callers
- SB-05 (Phase 5): ConnectError may leak infrastructure URLs
- SA-01/SB-05 (Phase 6): Integration test for session summary in lifespan teardown

## Blockers
none

## Knowledge Snapshots
- phase 01 complete (2026-05-04): mcp scaffolding, 14 tools, defendojo client, health check
- audit complete (2026-05-06): full audit — 4 critical, 17 important, 18 minor
- phase 02 verified (2026-05-07): all 4 critical audit findings resolved
- phase 03.1 verified (2026-05-07): input validation + pagination metadata
- phase 03.2.1 verified (2026-05-07): robustness + logging + auth
- phase 03.2.2 verified (2026-05-07): full test suite
- pre-ship audit (2026-05-07): B- overall — 0 critical, 10 important (all resolved), 16 minor
- v1.0.0 shipped (2026-05-07): 5 phases, 15 tasks, all important findings resolved
- deployed (2026-05-07): mcp-host:3500, svc-mcp service account (Writer role), Vault-stored token, Docker networking fixed via nftables role
- production validated (2026-05-08): 32 live tests, all 14 tools pass, create_finding bug fixed (missing numerical_severity/found_by), svc-mcp Writer cannot create_product (403)
- phase 4.1 verified (2026-05-08): structured JSON logging, configurable log levels, secret redaction (including extra dict values), exception tracebacks in JSON
- phase 4.2 verified (2026-05-08): audit_tool decorator on all 14 tools, caller_id/request_id/duration_ms/outcome tracking, ContextVar propagation to client, recursive nested dict redaction. 125 tests, 94% coverage.
- phase 5 verified (2026-05-08): per-tool scope enforcement (read/write), TLS enforcement by default, mutation rate limiting (60/min per caller), request size limits, dual API key support. SB-01 fixed (secret redaction). 164 tests.
- phase 6 verified (2026-05-08): HMAC-SHA256 integrity chain, dedicated audit log file (WatchedFileHandler), retention metadata (security_audit/operational/debug), session shutdown summary. SB-02 fixed (HMAC key redaction). 176 tests.
- pre-ship audit v2.0 (2026-05-09): B overall — 0 critical, 7 important (all fixed), 12 minor (accepted). 182 tests.
- v2.0.0 shipped (2026-05-09): 4 phases, 14 tasks, regulatory-grade audit logging & hardening complete.

## Next Action
> Milestone v2.0.0 shipped. Start next milestone with `/titan-vision` or `/titan-plan`.

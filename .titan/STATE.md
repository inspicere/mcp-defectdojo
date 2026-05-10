# TITAN State

## Current Position
- Phase: 8
- Step: verify (ready)
- Status: active
- Last Action: Build complete — all 3 tasks done for Phase 8 — RBAC Implementation
- Updated: 2026-05-10

## Completed Milestones
| Version | Phases | Date | Notes |
|---------|--------|------|-------|
| v1.0.0 | 01, 02, 03.1, 03.2.1, 03.2.2 | 2026-05-07 | Initial release — MCP server for DefectDojo with 14 tools, full test suite, B- audit score |
| v2.0.0 | 4.1, 4.2, 5, 6 | 2026-05-09 | Regulatory-grade audit logging & hardening — structured JSON logging, HMAC integrity chain, per-tool auth, TLS enforcement, rate limiting, 182 tests, B audit score |
| v2.2.0 | scan-import, metadata, lifecycle, filters | 2026-05-10 | Feature expansion — 9 new tools (23 total), scan import/reimport, finding lifecycle (close/notes/tags), metadata lookup, enhanced list_findings filters, 302 tests |

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
| 7.1 | CI Hardening | verified | 2026-05-10 | v2.2.1 |
| 7.2 | Code Hardening | verified | 2026-05-10 | v2.2.1 |
| 7.3 | RBAC Feature Design | verified | 2026-05-10 | v2.2.1 |

## Active Decisions
(none)

## Deferred Items
- DOM-04: Auto-pagination mechanism (Vikunja #259)
- svc-mcp role elevation for product creation (Vikunja #264)
- SB-02 (Phase 5): MutationRateLimiter memory cleanup for many callers
- ~~SB-05 (Phase 5): ConnectError may leak infrastructure URLs~~ — resolved by `_sanitize_api_error()` in commit `b9b1e8d`
- SA-01/SB-05 (Phase 6): Integration test for session summary in lifespan teardown

## Blockers
none

## Knowledge Snapshots
- v2.2 full audit (2026-05-10): 12-dimension audit of v2.2.0. 0 critical, 0 high, 1 medium (CI curl -sk TLS bypass), 5 low, 6 info. Risk posture: Low. All prior audit findings verified resolved. DefectDojo #2058 created. Vikunja #404-#409 created. Report: docs/audit-v2.2-full.md.
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
- project audit v2.0 (2026-05-09): 12-dimension audit (service-api + application overlays). 0 critical, 2 high, 6 medium, 8 low, 5 info. All 6 high+medium findings fixed: README rewrite, audit log description truncation, .env.example, pyproject.toml version 2.0.0, CI pipeline (.forgejo/workflows/test.yml), write tool docstrings. 182 tests pass.
- container deployment fixes (2026-05-09): Dockerfile fixed (README.md COPY, uv cache cleanup, UV_NO_CACHE=1, --no-sync on entrypoint). Commit c8ef3c0, pushed.
- TLS deployment (2026-05-09): Both MCP communication legs secured with TLS via Caddy. MCP→DefectDojo uses https://defectdojo.example.internal (existing Caddy route). Claude Code→MCP uses https://defectdojo-mcp.example.internal (new Caddy route). ALLOW_INSECURE_HTTP removed. Transport changed to streamable-http.
- dnsmasq service aliases (2026-05-09): Added dnsmasq_service_aliases variable (21 Caddy-proxied subdomains including defectdojo-mcp) and address= directives in template to fix local DNS resolution for *.internal.example.internal behind Caddy.
- post-TLS audit (2026-05-09): 12-dimension audit post-TLS (`docs/audit-v2.0-post-tls.md`). 0 critical, 0 high, 2 medium, 5 low, 7 info. Committed as `9d558f9`.
- post-TLS audit remediation batch 1 (2026-05-09): 4 findings fixed (commit `c215f7e`): pip-audit in CI (Medium), title added to `_TRUNCATE_FIELDS` (Medium, privacy), README env path fix (Low), uv version pinned in CI (Low).
- post-TLS audit remediation batch 2 (2026-05-09): 3 findings fixed (commit `dc3daa5`): Python 3.13 CI matrix (Low), CHANGELOG.md created (Low), Docker base image pinned by sha256 digest (Low). Zero open findings from post-TLS audit.
- CI/CD workflow fixes (2026-05-10): 3 issues resolved in commit `12c1be6`: (1) Python install in test workflow switched from apt to `uv python install` via standalone uv installer (node:22-slim lacks python3.X apt packages); (2) DefectDojo upload scan_date removed to avoid UTC/timezone mismatch "future date" error; (3) Gitleaks step changed from `continue-on-error: true` to `set +e` exit code handling for proper failure reporting. Both security and test workflows fully green.
- container redeployment (2026-05-10): Latest code (including SIEM forwarding handlers from prior session) synced to mcp-host via rsync, image rebuilt with `--no-cache`, container healthy, health_check OK.
- v2.1.0 feature assessment (2026-05-10): Assessed 14-tool inventory against DefectDojo API v2 capabilities. Major gap identified: `import_scan`/`reimport_scan` (core DefectDojo workflow). Tiered roadmap produced: Tier 1 (scan import, product types, test types), Tier 2 (finding lifecycle), Tier 3 (operational features).
- v2.2.0 feature expansion (2026-05-10): 9 new tools implemented via 4 parallel worktree-isolated subagents, merged to main. Tools: 14→23, Tests: 206→302. Tier 1 complete (import_scan, reimport_scan, list_product_types, list_test_types). Tier 2 complete (close_finding, add_finding_note, list_finding_notes, add_finding_tags, remove_finding_tags). Enhanced list_findings from 3 to 18 filter params. Container needs rebuild to include new features.
- bug fixes (2026-05-10): (1) `add_finding_note` fixed — `note_type: 0` rejected by DefectDojo, changed to `int | None = None` so it's omitted when unset (commit `ef932f7`). (2) API error messages sanitized — `_sanitize_api_error()` maps HTTP status codes to generic messages, preventing field name/validation rule leakage to MCP clients (Finding #934). (3) `HTTPSLogHandler` validates URL scheme, rejecting non-HTTP schemes (Finding #1926). Both fixes in commit `b9b1e8d`. Container rebuilt on mcp-host.
- DefectDojo findings closed (2026-05-10): All 4 active findings for mcp-defectdojo closed — #933 (rate limiting, already fixed in v2.0.0), #971 (shared API key, already fixed in v2.0.0), #934 (error message leakage, fixed this session), #1926 (dynamic urllib use, fixed this session). Zero open findings.
- phase 7 complete (2026-05-10): All v2.2 audit findings resolved. Phase 7.1: CI hardening (TLS bypass removed, gitleaks SHA256 verification, uv pinned). Phase 7.2: code hardening (HTTPSLogHandler http:// warning, close_finding partial success, health_check error sanitization). Phase 7.3: RBAC design (requirements FR-030-034, architecture with 4-role hierarchy, 3 decision log entries). 302 tests pass.

## Next Action
> Run /user:titan-verify to verify Phase 8 — RBAC Implementation

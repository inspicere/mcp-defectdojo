---
phase: 5
name: Access Control & Hardening
verified: 2026-05-08T19:30:00Z
tasks_done: 3
tasks_modified: 0
tasks_deferred: 0
tasks_failed: 0
tasks_added: 1
ac_pass: 10
ac_fail: 0
deviations: 2
---

# Phase 5 — Access Control & Hardening — Reconciliation Summary

## Task Reconciliation

| Task | Planned | Actual | Status | Notes |
|------|---------|--------|--------|-------|
| T1: Scope Enforcement & TLS Hardening | Per-tool auth via scope_check, TLS rejection, _build_auth multi-token | Implemented as planned in server.py and client.py | DONE | — |
| T2: Rate Limiting, Request Size Limits & Dual API Keys | security.py module, rate limiter, field validation, dual API keys | Implemented as planned across security.py, client.py, server.py | DONE | — |
| T3: Test Suite | 36 tests across scope, TLS, rate limiting, field validation, dual keys | 37 tests (added boundary test during verification) | DONE | — |
| — | Not planned | Fix SB-01: Add Phase 5 secrets to RedactingFilter | ADDED | Found during adversarial review |

## Acceptance Criteria Verification

| AC ID | Criterion | Verdict | Evidence |
|-------|-----------|---------|----------|
| AC-5.1 | Read-only token denied on write tool | ✓ PASS | scope_check("write") returns False for ["read"] token; test_scope_check_denies_missing_scope |
| AC-5.2 | Read+write token succeeds on any tool | ✓ PASS | scope_check allows both scopes; test_scope_check_allows_matching_scope + test_scope_check_write_allows_write_token |
| AC-5.3 | No auth configured = all tools accessible | ✓ PASS | _build_auth returns None; scope_check returns True when token is None; test_build_auth_no_tokens + test_scope_check_allows_when_no_token |
| AC-5.4 | MCP_READ_TOKEN gives read-only access | ✓ PASS | _build_auth registers read token with ["read"] only; test_build_auth_dual_tokens |
| AC-5.5 | http:// raises ValueError unless ALLOW_INSECURE_HTTP=true | ✓ PASS | client.py rejects http:// by default; test_http_url_rejected_by_default + test_http_url_allowed_with_env_override |
| AC-5.6 | Rate limit rejects after threshold | ✓ PASS | MutationRateLimiter with sliding window; test_rate_limiter_rejects_over_limit + test_rate_limiter_window_expiry |
| AC-5.7 | Title > 200 chars rejected | ✓ PASS | validate_field_length in create_finding; test_field_length_validation_rejects + test_field_length_at_exact_boundary |
| AC-5.8 | Dual keys: GET uses read key | ✓ PASS | _select_client routes GET to _read_client; test_read_operations_use_read_client |
| AC-5.9 | Single key backward compat | ✓ PASS | _dual_key_mode=False when only DEFECTDOJO_API_KEY; test_single_api_key_mode |
| AC-5.10 | All features have positive + negative tests | ✓ PASS | 37 new tests + 1 redaction test cover all features with both paths |

## Deviations

| # | Type | Description | Impact | Acceptable? |
|---|------|-------------|--------|-------------|
| D1 | SCOPE_ADDITION | Added SB-01 fix: Phase 5 secrets to RedactingFilter | Positive — closed a security gap | Yes |
| D2 | SCOPE_ADDITION | Added boundary test for field validation | Positive — improved test coverage | Yes |

## State Consistency
✓ All state files consistent

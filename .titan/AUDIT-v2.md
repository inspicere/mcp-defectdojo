# TITAN Audit Report — mcp-defectdojo v2.0 Pre-Ship

- **Date:** 2026-05-09
- **Scope:** All source (5 files), Dockerfile, pyproject.toml, test suite (7 files)
- **Dimensions:** Security, Performance, Domain/MCP, Code Quality, Test Coverage
- **Test baseline:** 176 passed, 0 failed
- **Dependency audit:** pip-audit clean (0 CVEs)

## Summary

| Dimension | Critical | Important | Minor | Score |
|-----------|----------|-----------|-------|-------|
| Security | 0 | 3 | 3 | B |
| Performance | 0 | 2 | 2 | B |
| Domain/MCP | 0 | 1 | 2 | B+ |
| Code Quality | 0 | 0 | 3 | A- |
| Test Coverage | 0 | 1 | 2 | B- |
| **Overall** | **0** | **7** | **12** | **B** |

## v1.0 Issue Resolution

| v1.0 ID | Issue | Status |
|---------|-------|--------|
| DOM-01 | RuntimeError propagation in 13/14 tools | RESOLVED — all tools use `except RuntimeError as e: raise ToolError(str(e))` |
| SEC-02 | `locals()` kwargs injection in update_finding | RESOLVED — explicit field allow-list dict |
| PERF-01 | Closed client reference not nullified | RESOLVED — `client = None` in lifespan finally |
| DOM-02/SEC-08 | No date format validation | RESOLVED — `_validate_date()` with `date.fromisoformat()` |
| SEC-01 | No MCP-level auth | RESOLVED — `StaticTokenVerifier` with read/write scopes |
| SEC-03 | No URL validation (SSRF potential) | PARTIAL — scheme, hostname, credentials checked; private IPs not blocked |
| SEC-04 | No TLS enforcement | RESOLVED — HTTP rejected unless `ALLOW_INSECURE_HTTP=true` |
| SEC-05 | Single shared API key | RESOLVED — dual-key mode with method-based routing |
| CQ-01 | 14x duplicated null-guard | RESOLVED — `_require_client` decorator |
| CQ-02 | Client methods return `Any` | PARTIAL — `dict[str, Any]` return types now declared |

## Security Findings

### SEC-01 — IMPORTANT — SSRF: Private IP ranges not blocked
**OWASP:** A10 (SSRF) / A03 (Injection)
**File:** `client.py:45–58`

URL validation checks scheme, hostname, embedded credentials, and TLS. Does NOT block private/link-local/loopback IPs (`169.254.*`, `127.*`, `10.*`, `172.16-31.*`, `192.168.*`, `[::1]`). Requires operator-level env var access to exploit, but defense-in-depth expects the application to reject known-bad targets.

**Recommendation:** Add private IP blocking or document as accepted risk for internal-only deployment.

### SEC-02 — IMPORTANT — Ephemeral HMAC key
**OWASP:** A08 (Data Integrity) / A02 (Cryptographic Failures)
**File:** `audit_logging.py:210–211`

When `AUDIT_HMAC_KEY` is not set, a random key is generated via `secrets.token_bytes(32)`. Key is ephemeral — lost on restart. Post-restart HMAC chain verification is impossible. No warning is logged when running with an ephemeral key.

**Recommendation:** Log CRITICAL warning when AUDIT_HMAC_KEY is not set. Document as required for regulatory deployments.

### SEC-03 — IMPORTANT — No auth-disabled warning on network transport
**OWASP:** A07 (Authentication) / A04 (Insecure Design)
**File:** `server.py:25–31`

When no `MCP_AUTH_TOKEN` is configured, `scope_check()` allows all access (by design for stdio). But deploying on SSE/HTTP transport without auth silently exposes full read+write access. No startup warning emitted.

**Recommendation:** Log CRITICAL warning at startup when auth is not configured and transport is network-facing.

### SEC-04 — MINOR — TLS cert verification implicit
**File:** `client.py:13–23`

`httpx.AsyncClient` created without explicit `verify=True`. Relies on httpx default. Unlikely to cause issues but explicit is better for regulated environments.

### SEC-05 — MINOR — Dockerfile image not pinned by digest
**File:** `Dockerfile:1`

Base image `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` referenced by tag, not SHA digest.

### SEC-06 — MINOR — Full description logged in audit records
**File:** `audit_logging.py:165`

`request_params` logs full `description` field (up to 10K chars). Finding descriptions may contain sensitive internal details.

## Performance Findings

### PERF-01 — IMPORTANT — `inspect.signature()` not cached
**File:** `audit_logging.py:144`

Called on every tool invocation inside `audit_tool` wrapper. Signature never changes — should be captured once at decoration time.

### PERF-02 — IMPORTANT — Triple JSON round-trip in IntegrityChainFormatter
**File:** `audit_logging.py:61–75`

`super().format()` → JSON string → `json.loads()` → mutate dict → `json.dumps()` for HMAC → `json.dumps()` for output. Three serialization operations per log record.

### PERF-03 — MINOR — RedactingFilter rebuilds secrets list per record
**File:** `audit_logging.py:85`

`os.environ.get()` called for all 6 secret env vars on every log record. Should be cached at init time.

### PERF-04 — MINOR — Rate limiter never evicts empty deques
**File:** `security.py:24`

`defaultdict(deque)` keys persist after expiry. Unbounded growth with many unique caller IDs.

## Domain/MCP Findings

### DOM-01 — IMPORTANT — Pagination `has_next` logic defect
**File:** `server.py:96–101`

```python
count=result.get("count", len(items)),      # fallback: len(items)
has_next=(offset + limit) < result.get("count", 0),  # fallback: 0
```

Two different fallbacks for the same missing `count` key. When `count` is absent, `has_next` is always False regardless of actual data. LLM consumers would never paginate further.

### DOM-02 — MINOR — No date-range cross-validation
**File:** `server.py:224–225`

`create_engagement` and `create_test` validate each date individually but never check `target_start <= target_end`.

### DOM-03 — MINOR — `found_by: [1]` hardcoded
**File:** `client.py:179`

Assumes test type ID 1 exists on target DefectDojo instance. Should be configurable or documented.

## Code Quality Findings

### CQ-01 — MINOR — TestSummary triggers PytestCollectionWarning
**File:** `models.py:26`

Class name starting with "Test" collides with pytest discovery.

### CQ-02 — MINOR — DefectDojoClient.__init__ CC=13
**File:** `client.py:27`

Constructor handles URL validation, credential routing, and client creation in one method.

### CQ-03 — MINOR — RedactingFilter.filter() CC=12
**File:** `audit_logging.py:84`

Nested closures defined inside `filter()` on every call. Should be instance methods.

## Test Coverage Findings

### TEST-01 — IMPORTANT — 6 tools missing happy-path tests
**File:** `test_server.py`

No success-path tests for: `get_engagement`, `get_test`, `list_tests`, `create_test`, `get_finding`, `create_finding`.

### TEST-02 — MINOR — No `has_next=True` pagination test
**File:** `test_server.py`

All pagination tests use single-item responses. The DOM-01 defect is undetectable by current suite.

### TEST-03 — MINOR — No concurrent rate-limiter test
**File:** `test_access_control.py`

asyncio.Lock behavior under concurrent callers is untested.

## Recommended Actions

### Must-fix before ship (3 items):
1. **DOM-01** — Fix `has_next` pagination fallback inconsistency
2. **PERF-01** — Cache `inspect.signature()` at decoration time
3. **SEC-02** — Add CRITICAL warning when AUDIT_HMAC_KEY not set

### Should-fix (4 items):
4. **SEC-03** — Add warning when auth disabled on network transport
5. **PERF-02** — Refactor IntegrityChainFormatter to avoid JSON round-trip
6. **PERF-03** — Cache secrets_list in RedactingFilter
7. **TEST-01** — Add happy-path tests for 6 uncovered tools

### Accept for v2.0, track for later (10 items):
8–19. SEC-01, SEC-04–06, DOM-02–03, CQ-01–03, PERF-04, TEST-02–03

## Overall Assessment

**Score: B** — Substantial improvement from v1.0 (D+). All 10 v1.0 findings resolved or partially resolved. Zero critical issues. The 3 must-fix items are low-effort, high-impact changes (estimated 30 minutes total). The codebase is production-ready for internal deployment after those fixes.

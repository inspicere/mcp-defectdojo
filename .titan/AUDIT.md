# TITAN Audit Report

- **Date:** 2026-05-10
- **Version:** v3.0.0
- **Scope:** All source files (7), test files (14), CI workflows (2), Dockerfile, pyproject.toml, dependencies
- **Dimensions:** Security, Performance, Code Quality, Domain (MCP Server)
- **Dependency Scan:** `pip-audit` — no known vulnerabilities found
- **Test Suite:** 390 passed, 0 failed (97% coverage)

## Summary
| Dimension | Critical | Important | Minor | Score |
|-----------|----------|-----------|-------|-------|
| Security | 0 | 6 | 6 | B+ |
| Performance | 0 | 4 | 5 | B |
| Code Quality | 0 | 4 | 11 | B |
| Domain (MCP) | 0 | 8 | 9 | B- |
| **Overall** | **0** | **22** | **31** | **B** |

**Previous audit (v2.2, 2026-05-10):** 0 critical, 0 high, 1 medium, 5 low — Risk: Low
**Delta:** This is a deeper multi-dimensional audit. The prior audit focused on 12 security-oriented dimensions. This audit adds performance, code quality, and MCP domain analysis, surfacing structural and design-level findings not covered before.

---

## Security Findings

### Critical
(none)

### Important

**SEC-001: Open-access fallback when no auth tokens configured (A01)**
- **File:** `rbac.py:95-96`
- When `ctx.token is None` (no auth configured), all access is allowed regardless of permission group. A misconfigured deployment silently grants full access. Logged at CRITICAL level at startup (`server.py:46-50`).
- **Fix:** Add a `REQUIRE_AUTH=true` flag (default `true` for network transports) that causes startup failure if no tokens are configured.

**SEC-002: HMAC key ephemeral by default (A02)**
- **File:** `audit_logging.py:436-445`
- When `AUDIT_HMAC_KEY` is not set, an ephemeral 32-byte key is generated via `secrets.token_bytes(32)`. The integrity chain is unverifiable after restart. CRITICAL log emitted.
- **Fix:** Consider refusing to start on network transports without `AUDIT_HMAC_KEY`, or emit a startup warning to stderr.

**SEC-003: ALLOW_INSECURE_HTTP override too easy to enable (A05)**
- **File:** `client.py:81-87`
- `ALLOW_INSECURE_HTTP=true` bypasses TLS enforcement. A simple boolean is easy to set accidentally.
- **Fix:** Require a stronger confirmation value (e.g., `ALLOW_INSECURE_HTTP=i-understand-the-risk`).

**SEC-004: CI installer pipe without integrity check (A08)**
- **File:** `.forgejo/workflows/test.yml:24`
- `curl -LsSf https://astral.sh/uv/0.11.5/install.sh | sh` — CDN compromise = arbitrary code in CI. The security workflow pins Trivy/Gitleaks with SHA256, but the test workflow does not apply the same rigor to the uv installer.
- **Fix:** Download install script separately, verify hash, then execute. Or use a container with uv pre-installed.

**SEC-005: Default bind 0.0.0.0 for HTTP transport (A01)**
- **File:** `server.py:775`
- Server binds to all interfaces by default. Correct for Docker, risky on bare-metal.
- **Fix:** Document that `FASTMCP_HOST` should be set to `127.0.0.1` when not containerized.

**SEC-006: No private IP validation on DEFECTDOJO_URL (A10)**
- **File:** `client.py:56,73-79`
- URL is validated for scheme and hostname but not against internal/private IP ranges or cloud metadata (169.254.169.254). Operator-controlled env var, so low risk.
- **Fix:** For defense-in-depth, validate against link-local and metadata addresses.

### Minor

- **SEC-007:** `client.py` — FastMCP `StaticTokenVerifier` uses `dict.get()` (hash lookup, not timing-safe comparison) for token validation. Upstream library issue; low practical risk for internal MCP server.
- **SEC-008:** `Dockerfile` — No `HEALTHCHECK` instruction. Container orchestrators cannot auto-detect unhealthy state.
- **SEC-009:** `Dockerfile` — No `read_only`, `no-new-privileges`, or `cap_drop` directives documented for runtime security context.
- **SEC-010:** `.forgejo/workflows/security.yml:33` — Semgrep installed via `pip3 install` without `--require-hashes`. Version pinned but package integrity not verified.
- **SEC-011:** `server.py:123-129` — `_caller_id()` returns `"anonymous"` for unauthenticated callers. Multiple anonymous callers are indistinguishable in audit logs.
- **SEC-012:** `.forgejo/workflows/test.yml:25,28` — `${{ matrix.python-version }}` in `run:` blocks. Safe (values are author-controlled), but noted for awareness.

### Info

- No hardcoded secrets found in source or git history. `.gitignore` correctly excludes `.env`.
- `pip-audit` reports no known vulnerabilities in any dependency.
- Docker image pinned by SHA256 digest. Good supply chain practice.
- HMAC-chained audit logging provides tamper detection. `RedactingFilter` scrubs 7 secret env vars.
- All 23 tools have explicit `auth=permission_check(...)` decorators. No tools missing auth checks.
- Dual API key mode correctly separates read/write at the HTTP client level.
- No `curl -k`, `curl --insecure`, or `${{ github.event.* }}` in CI workflow `run:` blocks.
- Security headers (CSP, HSTS, etc.) are not applicable — MCP JSON API, not a web app.

---

## Performance Findings

### Critical
(none)

### Important

**PERF-001: IntegrityChainFormatter double-serializes every log entry**
- **File:** `audit_logging.py:71-84`
- `json.dumps()` called twice per record: once for HMAC payload (line 77), once for final output (line 84). With 4 handlers (stderr + file + syslog + HTTPS), up to 8 JSON serializations per log entry.
- **Fix:** Serialize once for HMAC, then insert the HMAC field into the already-serialized string before the closing brace.

**PERF-002: RedactingFilter regex compiled on every invocation**
- **File:** `audit_logging.py:100-128`
- `re.sub(r"Token \S+", ...)` is compiled on every call. With 7 secrets and nested values, cost scales with field count.
- **Fix:** Pre-compile with `re.compile()` at module/class level. Consider a single combined regex pattern for all secrets.

**PERF-003: HTTPSLogHandler double-parses JSON in flush**
- **File:** `audit_logging.py:316`
- Each batch item is deserialized from JSON string back to dict, then the batch is re-serialized. 10 `json.loads()` + 1 `json.dumps()` per flush.
- **Fix:** Store pre-parsed dicts in the queue, or concatenate raw JSON strings as NDJSON.

**PERF-004: Pydantic model create-and-dump overhead in response formatting**
- **File:** `server.py:88-106`
- List responses create N Pydantic model instances only to immediately `model_dump()` them. For 100 findings, this means 100 `FindingSummary` constructions with validation.
- **Fix:** Use `TypeAdapter` for batch validation, or a plain dict projection for the hot path.

### Minor

- **PERF-005:** `security.py:24,29` — Global `asyncio.Lock()` in rate limiter serializes all callers through a single lock. Negligible at 2-5 callers; use per-caller locks at higher concurrency.
- **PERF-006:** `audit_logging.py:383` — `_TRUNCATE_FIELDS` frozenset reconstructed inside wrapper on every tool call. Move to module level.
- **PERF-007:** `server.py:438-450` — `_decode_file()` holds ~87MB peak memory for max-size scan imports (base64 string + decoded bytes). Acceptable for single-tenant.
- **PERF-008:** `server.py:101` — `json.dumps(..., indent=2)` adds ~30-40% whitespace to all responses. Increases LLM token count. Consider compact JSON.
- **PERF-009:** `client.py:41-51` — `Content-Type: application/json` set as default header on httpx client, requiring manual override for multipart uploads. Design concern, not a performance issue.

---

## Code Quality Findings

### Critical
(none)

### Important

**CQ-001: import_scan / reimport_scan near-identical duplication**
- **File:** `server.py:486-769`, `client.py:331-444`
- ~90% identical validation logic and dict-building code duplicated across both functions in both files (~120 lines).
- **Fix:** Extract shared `_validate_scan_params()` and `_build_scan_data()` helpers.

**CQ-002: Module-level mutable global client**
- **File:** `server.py:21`
- `client: DefectDojoClient | None = None` modified at runtime via `lifespan()`. Implicit coupling, harder to test.
- **Fix:** Store client in FastMCP app context dict rather than a module global.

**CQ-003: SessionCounter lacks thread safety**
- **File:** `audit_logging.py:333-352`
- Plain int attributes and dict updated from async context without synchronization. CPython GIL prevents corruption, but not guaranteed on all implementations.
- **Fix:** Use `threading.Lock` or `collections.Counter` with a lock.

**CQ-004: health_check inconsistency**
- **File:** `server.py:134`
- Only tool that doesn't use `_require_client` pattern and returns a plain string instead of JSON. Forces LLM agents to special-case its response.
- **Fix:** Return `json.dumps({"status": "ok", ...})` and unify with `_require_client`.

### Minor

- **CQ-005:** `server.py:8`, `client.py:7` — Mixed `Optional[X]` and `X | None` syntax. Standardize on `X | None` (Python 3.12+ project).
- **CQ-006:** `client.py:290` — `get_finding_tags` defined but never called by any MCP tool. Dead code or missing tool.
- **CQ-007:** `server.py:481,604,617` — `close_finding`, `add_finding_note`, `list_finding_notes` return raw `json.dumps(res)` bypassing `_format_response()` and Pydantic validation.
- **CQ-008:** `models.py:49-54` — `FindingNote` model defined but never used for response validation.
- **CQ-009:** `server.py:83-86` — `_mutation_limiter` constructed at module import before `load_dotenv()` in `lifespan`. `.env` rate limit config silently ignored.
- **CQ-010:** `server.py:409` — `update_finding` filters `None` values correctly (`False is not None` is `True`), but variable name `kwargs` could be clearer.
- **CQ-011:** `server.py:335` — `list_findings` description hardcodes "18 filter parameters" — maintenance hazard.
- **CQ-012:** `models.py:56-61` — `ImportScanResult` missing `findings_count`, `created`, `closed`, `reactivated`, `untouched` fields.
- **CQ-013:** `models.py:26-32` — `TestSummary` omits `target_start`, `target_end` fields returned by API.
- **CQ-014:** `models.py:18-24` — `EngagementSummary` omits `status` field. LLM cannot determine if engagement is active/complete.
- **CQ-015:** `server.py:314` — `list_findings` cyclomatic complexity ~15. Linear validation branches, not nested — acceptable but at threshold.

### Info

- No TODO/FIXME/HACK comments found in any source file. Clean codebase.
- Type annotations complete on all function signatures. Only `Any` usage is for API response dicts (appropriate).
- 390 tests across 14 test files. Tests cover happy paths, validation, null guards, rate limiting, RBAC matrix, audit structure, log integrity.
- `pyproject.toml` correctly sets `requires-python = ">=3.12"`. Dockerfile runs as non-root user.

---

## Domain (MCP Server) Findings

### Critical
(none)

### Important

**DOM-001: 5 tools bypass response model validation**
- **Files:** `server.py:481,604,617,635,651`
- `close_finding`, `add_finding_note`, `list_finding_notes`, `add_finding_tags`, `remove_finding_tags` return raw `json.dumps(res)` instead of using `_format_response()` with Pydantic models. Inconsistent response shapes — 18 tools return validated JSON, 5 return raw API responses. `close_finding` is most critical (leaks internal DefectDojo field names).
- **Fix:** Route through `_format_response()` with appropriate models.

**DOM-002: FindingSummary too sparse for LLM triage**
- **File:** `models.py:34-47`
- Missing `tags`, `component_name`, `component_version`, `cwe`, `cvssv3_score`, `file_path`, `line`, `risk_accepted`, `vulnerability_ids`. LLM agents cannot determine CWE, CVSS, affected component, or file location without a second API call.
- **Fix:** Add key triage fields as optional.

**DOM-003: ImportScanResult lacks finding counts**
- **File:** `models.py:56-61`
- After importing a scan, the LLM cannot report how many findings were created/closed/reactivated/untouched.
- **Fix:** Add `findings_count`, `created`, `closed`, `reactivated`, `untouched` as optional int fields.

**DOM-004: create_finding hardcodes found_by to [1]**
- **File:** `client.py:252`
- Assumes test type ID 1 exists. On instances where it doesn't, finding creation fails with a cryptic 400 error.
- **Fix:** Accept `found_by` as a parameter with a sensible default, or derive from the test's type.

**DOM-005: Uncaught httpx exceptions bypass error sanitization**
- **File:** `client.py:112-130`
- Only catches `HTTPStatusError`, `ConnectError`, `TimeoutException`. Other httpx exceptions (`ReadError`, `WriteError`, `PoolTimeout`, `DecodingError`, `TooManyRedirects`) propagate unhandled, potentially leaking internal URLs.
- **Fix:** Add `except httpx.HTTPError` as a fallback catch after the specific handlers.

**DOM-006: TestSummary omits target dates**
- **File:** `models.py:26-32`
- After creating a test with specific dates, the returned summary does not include them. Confusing for LLM agents.
- **Fix:** Add `target_start: str | None = None` and `target_end: str | None = None`.

**DOM-007: Module-level rate limiter reads env before dotenv**
- **File:** `server.py:83-86`
- `_mutation_limiter` constructed at import time; `load_dotenv()` called later in `lifespan`. `.env` file rate limit config silently ignored.
- **Fix:** Move limiter construction into `lifespan` or call `load_dotenv()` first.

**DOM-008: Missing Dockerfile HEALTHCHECK and EXPOSE**
- **File:** `Dockerfile`
- Container orchestrators cannot determine health. `EXPOSE 8000` missing for documentation. `STOPSIGNAL SIGTERM` missing for graceful shutdown.
- **Fix:** Add all three directives.

### Minor

- **DOM-009:** `models.py:18-24` — `EngagementSummary` omits `status`. LLM cannot determine if engagement is active/complete.
- **DOM-010:** `server.py:132-143` — `health_check` returns plain string while all other tools return JSON.
- **DOM-011:** `server.py:608-617` — `list_finding_notes` has no `limit`/`offset` pagination, unlike every other list tool.
- **DOM-012:** `client.py:290-291` — `get_finding_tags` exists but no tool exposes it. LLM can add/remove tags but cannot list them.
- **DOM-013:** `server.py:488-506` — `import_scan` has 19 parameters. High cognitive load for LLM agents. Needs "common invocation" documentation.
- **DOM-014:** `audit_logging.py:316` — `HTTPSLogHandler._flush` silently fails entire batch if any line is malformed JSON. Add per-line `try/except`.
- **DOM-015:** `rbac.py:54-84` — `TOOL_PERMISSIONS` dict is a manual mirror of tool registrations with no validation. If a tool is added but not in the dict, no startup error.
- **DOM-016:** `pyproject.toml` — `fastmcp>=3.2.4` with no upper bound. FastMCP is pre-1.0; breaking changes to `auth` API could silently break RBAC.
- **DOM-017:** `server.py:335` — `list_findings` description hardcodes filter count. Drifts as filters are added.

---

## Dependency Audit

```
$ .venv/bin/pip-audit
No known vulnerabilities found
```

All dependencies clean. Base image pinned by SHA256 digest. `uv.lock` provides deterministic builds.

## Secrets Scan

- No hardcoded secrets in source or git history — **CLEAR**
- `.gitignore` correctly excludes `.env`, `.env.*` — **CLEAR**
- `.env.example` tracked in git (no real secrets) — **CLEAR**
- `RedactingFilter` scrubs 7 secret env vars from all log output — **VERIFIED**

## Container Security

- Non-root user (`appuser`) — GOOD
- `--frozen` flag for reproducible builds — GOOD
- SHA256-pinned base image — GOOD
- No secrets baked into image — GOOD
- Missing: `HEALTHCHECK`, `EXPOSE`, `STOPSIGNAL` directives

## What Could NOT Be Checked

1. **Runtime behavior** — Static analysis only. No fuzzing or penetration testing performed.
2. **FastMCP framework internals** — Token comparison timing safety is in upstream library. Full auth middleware not exhaustively audited.
3. **DefectDojo API response trust** — Upstream responses trusted after HTTP status validation. Malicious JSON payloads from DefectDojo not tested.
4. **Network-level security** — TLS cipher suites, certificate validation, and network segmentation not tested.
5. **Container image CVEs** — Base image not scanned for OS-level vulnerabilities. SHA256 pin ensures reproducibility, not vulnerability-free status.
6. **Read-path DoS** — Rate limiter protects mutations only. No protection against read-path resource exhaustion.
7. **Secret rotation** — No mechanism to rotate tokens without restart. Token expiration not configured.
8. **Dependency supply chain** — `pip-audit` checks advisory databases. Does not detect unpublished zero-days or compromised wheels.

## Recommended Actions (Priority Order)

1. **DOM-001 / CQ-007:** Route all 5 tools through `_format_response()` with Pydantic models — prevents data leakage, fixes response consistency
2. **DOM-002:** Expand `FindingSummary` with CWE, CVSS, tags, component, file_path — enables LLM vulnerability triage
3. **SEC-001:** Add `REQUIRE_AUTH` flag for network transports — prevents accidental open-access deployments
4. **SEC-004:** Add hash verification to CI uv installer — aligns test workflow with security workflow's rigor
5. **PERF-001/002/003:** Fix logging double-serialization and pre-compile regex — low-effort CPU reduction in the hot path
6. **CQ-001:** Extract shared scan import/reimport helpers — reduces ~120 lines of duplication
7. **DOM-005:** Add `httpx.HTTPError` fallback catch — prevents URL leakage from uncaught exceptions
8. **DOM-007 / CQ-009:** Move rate limiter init into lifespan — fix silent `.env` config ignore
9. **DOM-003:** Expand `ImportScanResult` with finding counts — enables post-import reporting
10. **DOM-008:** Add Dockerfile `HEALTHCHECK`, `EXPOSE 8000`, `STOPSIGNAL SIGTERM`

## Comparison to Previous Audits

| Audit | Date | Cr | Hi/Imp | Med/Min | Score | Notes |
|-------|------|----|--------|---------|-------|-------|
| Phase 01 | 2026-05-06 | 4 | 17 | 18 | D+ | Initial codebase, no auth/tests/validation |
| Pre-ship v1.0 | 2026-05-07 | 0 | 10 | 16 | B- | All critical fixed, remaining accepted |
| Pre-ship v2.0 | 2026-05-09 | 0 | 7 | 12 | B | Regulatory logging, auth, TLS added |
| Post-TLS | 2026-05-09 | 0 | 0/2 | 5/7 | B+ | All remediated |
| v2.2 Full | 2026-05-10 | 0 | 0/1 | 5/6 | A- | Security-focused, low risk |
| **v3.0 Full** | **2026-05-10** | **0** | **22** | **31** | **B** | Multi-dimensional (4 axes), structural findings |

The v3.0 audit is deeper than prior audits — it covers performance, code quality, and MCP domain dimensions not previously examined. Security posture has improved steadily (D+ → B+). The "B" overall score reflects design-level findings (response model gaps, code duplication) rather than security regression.

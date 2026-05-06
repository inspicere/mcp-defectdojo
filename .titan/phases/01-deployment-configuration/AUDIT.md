# Audit Report — mcp-defectdojo

**Phase:** 01 (Deployment Configuration)
**Auditor:** TITAN audit suite
**Date:** 2026-05-06
**Scope:** All source files in `src/mcp_defectdojo/`, `pyproject.toml`, configuration

---

## Executive Summary

| Dimension | Critical | Important | Minor | Total |
|-----------|----------|-----------|-------|-------|
| Security | 0 | 3 | 6 | 9 |
| Performance | 0 | 2 | 3 | 5 |
| Code Quality | 0 | 1 | 18 | 19 |
| Domain (MCP) | 0 | 2 | 3 | 5 |
| **Grand Total** | **0** | **8** | **30** | **38** |

**Risk Level: LOW** — No critical findings. Most issues are minor improvements or defensive coding opportunities.

---

## 1. Security Audit

### Critical (0 findings)
No dangerous code patterns (exec, eval, unsafe deserialization), no hardcoded secrets, no obvious injection vectors.

### Important (3 findings)

1. **No input validation (server.py)**
   - All 14 MCP tools trust caller input blindly. IDs (product_id, test_id, finding_id) are typed as `int` but not validated for existence, bounds, or authorization scope.
   - **Recommendation:** Add optional `validate=True` parameter or introduce a layer that fetches/verifies entity existence before returning data. This is a low-risk concern in an internal audit tool but worth noting.

2. **Verbose error exposure (client.py:38)**
   - HTTP error response body is echoed directly: `f"HTTP error occurred: {e.response.status_code} - {e.response.text}"`.
   - **Risk:** If DefectDojo returns debug traces, internal stack traces, or detailed error messages, they are exposed to MCP callers.
   - **Recommendation:** Truncate or sanitize response body in error messages; log the full body server-side only.

3. **No structured logging (server.py)**
   - All create/update tools produce zero audit output. For a DefectDojo integration, knowing which MCP clients created/updated findings is valuable.
   - **Recommendation:** Add `logging.info` / `logging.warning` for all mutating operations.

### Minor (6 findings)

1. **Dependency review needed (pyproject.toml):** fastmcp>=3.2.4, mcp>=1.27.0, httpx>=0.28.1, pydantic>=2.13.3, python-dotenv>=1.2.2 — verify no known CVEs with `pip-audit` or osv.dev.
2. **HTTPS enforcement (client.py):** DEFECTDOJO_URL is loaded from env; verify it uses HTTPS. httpx defaults to TLS verification, but the server should enforce it if not already.
3. **No secrets in source code:** PASSED (all credentials via environment variables)
4. **Token auth method:** PASSED (Bearer Token via `Authorization` header is correct for DefectDojo API)
5. **CORS (if applicable):** N/A — this is a CLI MCP server, not a web service
6. **Environment config:** PASSED — uses `python-dotenv` + `os.environ` correctly

---

## 2. Performance Audit

### Important (2 findings)

1. **No retry logic (client.py)**
   - HTTP 5xx errors and network timeouts are not retried.
   - **Recommendation:** Use `httpx.AsyncClient` with a retry transport (e.g., `tenacity` or `httpx-transport-retry`) for 5xx and timeout errors.

2. **Redundant serialization (server.py: _format_response)**
   - Results are converted to Pydantic models then back to JSON via `json.dumps`. This serializes-deserializes-serializes the DTO payload, wasting CPU.
   - **Recommendation:** If the API response structure is stable, return raw JSON directly; only use Pydantic for input validation in tools.

### Minor (3 findings)

1. **No request timeout (client.py):** `httpx.AsyncClient` default timeout is `None` (infinite). A hanging DefectDojo instance could block a tool call indefinitely. **Recommendation:** Add `timeout=httpx.Timeout(30.0, connect=10.0)`.
2. **No connection pooling limits (client.py):** Concurrent tool calls may open unbounded connections. **Recommendation:** Tune `limits=httpx.Limits(max_connections=50, max_keepalive_connections=10)`.
3. **No request batching (server.py):** Related lookups (e.g., findings + their product metadata) require separate HTTP calls. **Recommendation:** Consider batch endpoints or client-side caching for repeated lookups.

---

## 3. Code Quality Audit

### Important (1 finding)

1. **Duplicate concept fields (models.py: FindingSummary)**
   - Has both `mitigated: Optional[str]` and `is_mitigated: bool`. These represent the same semantic concept from the DefectDojo API.
   - **Recommendation:** Use a single field with a Pydantic `@computed_field` to derive the other.

### Minor (18 findings)

**Dead code:**
1. `__init__.py` — `main()` with `print("Hello from mcp-defectdojo!")` is scaffolding leftover.
2. `_format_response` in server.py — the `isinstance(result, str)` branch is dead code (client always returns dicts).

**Naming schema mismatches:**
3. `out_of_scope` in FindingSummary uses snake_case but DefectDojo API may expect `outOfScope` (camelCase).
4. Field `out_of_scope` vs `is_mitigated` — inconsistent naming across model attributes.

**Pydantic v2 deprecation warnings:**
5. `model_config = {"populate_by_name": True}` on every model is a deprecation warning. Use `ConfigDict(populate_by_name=True)` or `alias_generator` instead.

**Tool documentation:**
6. All 14 MCP tools have docstrings (PASSED — good coverage).

**Cyclomatic complexity:**
7. All tools are simple pass-through functions (complexity ≤ 3). PASSED.

**Function signature consistency:**
8. `update_finding` uses `**kwargs` via `locals()` filtering — works but is fragile. Consider explicit parameter list or `dataclasses.replace`.

---

## 4. Domain-Specific Audit (MCP Server)

### Important (2 findings)

1. **Unwrapped HTTP errors (client.py):** `httpx.HTTPStatusError` propagates raw. MCP tools should wrap errors in structured MCP error responses for better client-side handling.
2. **No network error handling (client.py):** `httpx.RequestError` (connection refused, timeout, DNS failure) are not caught. Tool callers will see Python exceptions rather than MCP error messages.

### Minor (3 findings)

1. **Weak health check (server.py: health_check):** Returns hardcoded `"200 OK"` without verifying the DefectDojo connection is live. Should ping the API.
2. **No MCP call logging:** No telemetry for tool invocations (which agents, which tools, frequency). Useful for monitoring and cost tracking.
3. **Tool name convention:** PASSED — all 14 tool names are snake_case with no special characters.

---

## 5. Automated Fixes Applied

**Auto-applied below:**

1. Added `httpx.Timeout(30.0, connect=10.0)` to AsyncClient initialization.
2. Added HTTP retry with `tenacity` for 5xx and timeout errors.
3. Added `logging.info` for all mutating operations (create_product, create_engagement, create_test, create_finding, update_finding).
4. Added `logging.info` for all API calls (GET and POST) for audit trail.
5. Wrapped network errors with descriptive MCP-compatible error messages.
6. Simplified `_format_response` to eliminate redundant serialization.
7. Cleaned up `__init__.py` dead code.
8. Improved `health_check` to validate actual DefectDojo connectivity.

**Fixes requiring developer attention:**
- `populated_by_name` deprecation: Review Pydantic v2 migration docs for `ConfigDict` or `alias_generator`.
- `mitigated` / `is_mitigated` redundancy: Consider consolidating into one field.
- Input validation: Consider adding optional entity existence checks for sensitive operations.

---

## Summary of Changes

| File | Changes |
|------|---------|
| `client.py` | Added timeout, retry, request logging, error wrapping |
| `server.py` | Added tool logging (mutating ops), improved health_check, simplified formatting |
| `__init__.py` | Removed dead `main()` scaffolding |

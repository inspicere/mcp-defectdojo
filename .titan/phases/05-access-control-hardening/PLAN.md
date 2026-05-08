---
phase: 5
name: Access Control & Hardening
status: planned
tasks: 3
waves: 2
created: 2026-05-08
---

# Phase 5 — Access Control & Hardening

## Goal
Implement granular access controls, enforce TLS, add rate limiting and request size guards — meeting FFIEC "least privilege" and "defense in depth" expectations.

## Features
- FR-022: Scoped tool authorization (read/write scopes enforced per tool)
- FR-023: Separate read/write DefectDojo API keys
- FR-024: TLS enforcement (reject http:// by default)
- FR-025: Rate limiting on mutation operations
- FR-026: Request size limits on string fields
- FR-027: Security response headers (deferred — reverse proxy is the correct layer)

## Architecture Notes

FastMCP provides built-in support for:
- Per-tool `auth` parameter: `@mcp.tool(auth=require_scopes("write"))` — skips auth on stdio, enforces on HTTP/SSE
- `SlidingWindowRateLimitingMiddleware` — but applies globally, not mutation-only

Design decisions:
- Use FastMCP's per-tool `auth` parameter for FR-022 (scope enforcement)
- Create custom `scope_check(scope)` function that allows access when auth is unconfigured (backward compat)
- Implement mutation-specific rate limiting in a new `security.py` module (not FastMCP global middleware)
- Support dual API keys in client.py with read/write routing
- FR-027 (security headers) deferred — FastMCP manages HTTP app internally; security headers belong at the reverse proxy layer (nginx/traefik)

## Tasks

### T1: Scope Enforcement & TLS Hardening
**Wave:** 1
**Files:** `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`
**Features:** FR-022, FR-024

**Changes to `server.py`:**
1. Add import: `from fastmcp.server.auth.authorization import AuthCheck`
2. Create `scope_check(scope: str) -> AuthCheck` function:
   - Returns a callable that checks `ctx.token.scopes` if token is present
   - Returns True if token is None (backward compat: no auth configured)
   - This allows tools to be accessible when MCP_AUTH_TOKEN is not set
3. Apply `auth=scope_check("read")` to: `health_check`, `list_products`, `get_product`, `list_engagements`, `get_engagement`, `list_tests`, `get_test`, `list_findings`, `get_finding`
4. Apply `auth=scope_check("write")` to: `create_product`, `create_engagement`, `create_test`, `create_finding`, `update_finding`
5. Update `_build_auth()` to support multiple tokens:
   - `MCP_AUTH_TOKEN` → scopes `["read", "write"]` (backward compat, existing)
   - `MCP_READ_TOKEN` → scopes `["read"]` (new: read-only access)
   - Both tokens registered with their own `client_id`

**Changes to `client.py`:**
6. Change http:// handling from warning to rejection:
   - If `parsed.scheme == "http"` and `ALLOW_INSECURE_HTTP` env var is not `"true"`:
     raise ValueError("DEFECTDOJO_URL uses http:// — set ALLOW_INSECURE_HTTP=true to allow insecure connections")
   - If `ALLOW_INSECURE_HTTP=true`: log CRITICAL warning instead of WARNING
7. Keep the existing URL validation (scheme, credentials, hostname)

**Verification:**
- Tools tagged with scope check are visible to scoped tokens
- http:// URL rejected by default
- ALLOW_INSECURE_HTTP=true overrides rejection
- Existing tests still pass (backward compat)

### T2: Rate Limiting, Request Size Limits & Dual API Keys
**Wave:** 1 (parallel with T1 — different files for new module)
**Files:** `src/mcp_defectdojo/security.py` (new), `src/mcp_defectdojo/client.py` (extend), `src/mcp_defectdojo/server.py` (wire in)
**Features:** FR-025, FR-026, FR-023

**New file `security.py`:**
1. Create `MutationRateLimiter` class:
   - Sliding window rate limiter, per-caller
   - `max_mutations` and `window_seconds` configurable (default: 60 mutations per 60 seconds)
   - `async def check(self, caller_id: str) -> None` — raises ToolError if limit exceeded
   - Uses `collections.deque` for request timestamps per caller
   - Thread-safe via `asyncio.Lock`
2. Create `validate_field_length(value: str, field_name: str, max_length: int) -> None`:
   - Raises ToolError if `len(value) > max_length`
3. Module-level constants:
   - `MAX_TITLE_LENGTH = 200`
   - `MAX_DESCRIPTION_LENGTH = 10000`
   - `MAX_NAME_LENGTH = 200`

**Changes to `client.py`:**
4. Support dual API keys:
   - Read `DEFECTDOJO_READ_API_KEY` and `DEFECTDOJO_WRITE_API_KEY` env vars
   - If both present: create `_read_client` and `_write_client` (separate httpx.AsyncClient instances)
   - If only `DEFECTDOJO_API_KEY`: use single client for everything (backward compat)
   - Route `_request()` calls based on HTTP method: GET → read client, POST/PATCH → write client
   - `aclose()` closes both clients
   - Log at INFO which key mode is active ("single API key" vs "separate read/write API keys")

**Changes to `server.py`:**
5. Import and instantiate `MutationRateLimiter` from security.py
   - Read `MUTATION_RATE_LIMIT` env var (default "60") and `MUTATION_RATE_WINDOW` (default "60")
   - Create module-level `_mutation_limiter` instance
6. Import `validate_field_length`, `MAX_TITLE_LENGTH`, `MAX_DESCRIPTION_LENGTH`, `MAX_NAME_LENGTH`
7. Add rate limiting calls to write tools (create_*, update_*):
   - Extract caller_id from ctx (same logic as audit_tool)
   - Call `_mutation_limiter.check(caller_id)` before client call
8. Add field length validation:
   - `create_product`: validate name (MAX_NAME_LENGTH), description (MAX_DESCRIPTION_LENGTH)
   - `create_engagement`: validate name (MAX_NAME_LENGTH)
   - `create_finding`: validate title (MAX_TITLE_LENGTH), description (MAX_DESCRIPTION_LENGTH)
   - `update_finding`: validate title and description if present

**Verification:**
- Rate limiter rejects when limit exceeded
- Field length validation rejects oversized inputs
- Dual API keys route correctly
- Single API key mode still works

### T3: Test Suite
**Wave:** 2 (after T1 and T2)
**Files:** `tests/test_access_control.py` (new)
**Features:** All FR-022 through FR-026

**Test cases:**
1. **Scope enforcement:**
   - `test_scope_check_allows_when_no_token` — scope_check returns True when token is None
   - `test_scope_check_allows_matching_scope` — returns True when scope matches
   - `test_scope_check_denies_missing_scope` — returns False when scope missing
   - `test_read_tools_require_read_scope` — parametrized: all 9 read tools have auth set
   - `test_write_tools_require_write_scope` — parametrized: all 5 write tools have auth set
   - `test_build_auth_multiple_tokens` — MCP_AUTH_TOKEN + MCP_READ_TOKEN both registered

2. **TLS enforcement:**
   - `test_http_url_rejected_by_default` — http:// raises ValueError
   - `test_http_url_allowed_with_env_var` — ALLOW_INSECURE_HTTP=true allows http://
   - `test_https_url_accepted` — https:// always works

3. **Rate limiting:**
   - `test_rate_limiter_allows_within_limit` — requests under limit succeed
   - `test_rate_limiter_rejects_over_limit` — excess requests raise ToolError
   - `test_rate_limiter_per_caller_isolation` — different callers have independent limits
   - `test_rate_limiter_window_expiry` — old requests expire from window

4. **Request size limits:**
   - `test_field_length_validation_passes` — within limit
   - `test_field_length_validation_rejects` — over limit raises ToolError
   - `test_create_finding_rejects_oversized_title` — integration test
   - `test_create_product_rejects_oversized_name` — integration test

5. **Dual API keys:**
   - `test_single_api_key_mode` — DEFECTDOJO_API_KEY only, single client
   - `test_dual_api_key_mode` — both read/write keys, separate clients
   - `test_read_operations_use_read_client` — GET routes to read client
   - `test_write_operations_use_write_client` — POST/PATCH routes to write client

**Verification:**
- All new tests pass
- All existing 125 tests still pass
- No regressions

## Acceptance Criteria

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-5.1 | Given an MCP token with scopes ["read"], When a write tool is called, Then it is denied with an authorization error | T1 |
| AC-5.2 | Given an MCP token with scopes ["read", "write"], When any tool is called, Then it succeeds | T1 |
| AC-5.3 | Given no MCP_AUTH_TOKEN configured, When any tool is called, Then all tools are accessible (backward compat) | T1 |
| AC-5.4 | Given MCP_READ_TOKEN env var, When a client authenticates with it, Then only read tools are accessible | T1 |
| AC-5.5 | Given DEFECTDOJO_URL with http:// scheme, When the client initializes, Then it raises ValueError unless ALLOW_INSECURE_HTTP=true | T1 |
| AC-5.6 | Given a caller exceeding 60 mutations/minute, When the next mutation is attempted, Then it is rejected with a rate limit error | T2 |
| AC-5.7 | Given a title longer than 200 characters, When create_finding is called, Then it is rejected with a validation error | T2 |
| AC-5.8 | Given DEFECTDOJO_READ_API_KEY and DEFECTDOJO_WRITE_API_KEY, When a GET request is made, Then the read key is used | T2 |
| AC-5.9 | Given only DEFECTDOJO_API_KEY (no separate keys), When any request is made, Then the single key is used (backward compat) | T2 |
| AC-5.10 | All new features have test coverage with both positive and negative cases | T3 |

## Wave Schedule

| Wave | Tasks | Parallel? | Rationale |
|------|-------|-----------|-----------|
| 1 | T1, T2 | Yes | T1 touches server.py auth + client.py TLS; T2 creates new security.py + client.py dual keys. Minimal overlap (both touch server.py but different sections). |
| 2 | T3 | No | Tests depend on T1 and T2 being complete |

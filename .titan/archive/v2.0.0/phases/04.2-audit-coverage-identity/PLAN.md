---
phase: "4.2"
name: Audit Coverage & Identity
goal: Every tool invocation produces a complete audit record with caller identity, correlation ID, timing, and full read trail
branch: titan/phase-04.2-audit-coverage-identity
status: built
created: 2026-05-08T22:00:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 4.2 — Audit Coverage & Identity — Execution Plan

## Goal
Every tool invocation (read AND write) produces a structured audit log entry with: tool_name, request_id, caller_id, request_params, outcome, duration_ms. The request_id propagates to client.py API calls for end-to-end tracing. An examiner can reconstruct a complete access timeline from logs alone.

## Context
- Phase 4.1 delivered: StructuredJsonFormatter, RedactingFilter, configure_logging() in audit_logging.py
- FastMCP 3.2.4 `Context` provides `request_id`, `client_id`, `session_id` via injection
- Adding `ctx: Context` to tool signatures causes automatic injection; hidden from tool schema
- `_require_client` decorator uses `functools.wraps` — preserves `__annotations__` for Context injection
- `_build_auth()` sets `StaticTokenVerifier` with `{"client_id": "mcp-client", "scopes": ["read", "write"]}`
- Currently: 5 WRITE tools have manual logger.info() calls; 8 READ tools have zero logging
- `client.py._request()` logs at DEBUG level (method, path, status_code) — no request_id or duration
- Context's `request_id` raises `RuntimeError` outside MCP session — must guard in unit tests

## Acceptance Criteria (This Phase)

- **AC-4.3**: Given any tool invocation, When the tool completes, Then a structured audit log entry is emitted with fields: `tool_name`, `request_id`, `caller_id`, `request_params`, `outcome` (success/error), `duration_ms`.
- **AC-4.4**: Given a `list_products` or `get_finding` (read) tool call, When the call completes, Then an INFO-level audit log entry is emitted (not just mutations).
- **AC-4.5**: Given a tool invocation with a valid auth token, Then `caller_id` in the audit log is `"mcp-client"` (from StaticTokenVerifier config).
- **AC-4.6**: Given a tool invocation without an auth token, Then `caller_id` is `"anonymous"` and a WARNING-level log is emitted.
- **AC-4.7**: Given a tool invocation, When the tool calls DefectDojo API, Then the client.py debug log includes the same `request_id` as the server-side audit log.
- **AC-4.8**: Given a tool invocation, Then `duration_ms` reflects wall-clock time for the tool execution.
- **AC-4.9**: Given a tool invocation that raises an error, Then the audit log `outcome` is `"error"` and the error detail is included.

## Tasks

### Task T1: Audit decorator and client propagation infrastructure

- **AC**: AC-4.3, AC-4.5, AC-4.6, AC-4.7, AC-4.8, AC-4.9
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/audit_logging.py`, `src/mcp_defectdojo/client.py`
- **Files to Read**: `src/mcp_defectdojo/server.py`
- **Action**:

  **audit_logging.py additions:**

  1. Add imports: `import time`, `import uuid`, `from contextvars import ContextVar`

  2. Create a module-level `ContextVar`:
     ```python
     current_request_id: ContextVar[str] = ContextVar("current_request_id", default="")
     ```

  3. Create `audit_tool` decorator function:
     ```python
     def audit_tool(func):
     ```
     This decorator wraps an async tool function. It:
     - Inspects the function signature for a `ctx` parameter. If present, extracts it from kwargs at call time.
     - Extracts `request_id`: try `ctx.request_id` → catch `RuntimeError`/`AttributeError` → fallback to `str(uuid.uuid4())`
     - Extracts `caller_id`: try `ctx.client_id or "anonymous"` → if `None`, log a WARNING with `event_type: security_warning` about anonymous access
     - Sets `current_request_id.set(request_id)` so client.py can read it
     - Records `t0 = time.perf_counter()`
     - Calls the wrapped function in a try/except
     - On success: `outcome = "success"`
     - On exception: `outcome = "error"`, capture error detail
     - Computes `duration_ms = round((time.perf_counter() - t0) * 1000, 2)`
     - Emits a single `logger.info(...)` (or `logger.error(...)` on failure) with `extra={"event_type": "audit", "tool_name": func.__name__, "request_id": request_id, "caller_id": caller_id, "request_params": <extracted from kwargs>, "outcome": outcome, "duration_ms": duration_ms}`
     - On error: re-raises the exception after logging
     - Uses `@functools.wraps(func)` to preserve signatures

     The `request_params` should be built from the function's call kwargs/args, excluding `ctx`. Use `inspect.signature(func).bind(*args, **kwargs)` to map positional args to names.

  **client.py changes:**

  1. Add import: `from .audit_logging import current_request_id`
  2. In `_request()` method:
     - Add `t0 = time.perf_counter()` before the request
     - Read `request_id = current_request_id.get("")`
     - Update ALL debug/warning/error log calls to include `"request_id": request_id` and `"api_duration_ms": duration_ms` in their extra dicts
     - The `api_duration_ms` should be computed from the `time.perf_counter()` diff (measure the actual HTTP call, not the full method)
  3. Add `import time` at the top

- **Verification Steps**:
  1. `uv run python -c "from mcp_defectdojo.audit_logging import audit_tool, current_request_id; print('imports OK')"`
  2. `uv run pytest tests/ -x -q` — all existing tests still pass
  3. Verify `current_request_id` is a ContextVar in audit_logging.py
- **Done Criteria**: `audit_tool` decorator exists and is importable. `current_request_id` ContextVar exists. client.py reads request_id from contextvar and includes it plus api_duration_ms in logs.
- **Dependencies**: none

### Task T2: Apply audit decorator to all tools

- **AC**: AC-4.3, AC-4.4, AC-4.5, AC-4.6, AC-4.8, AC-4.9
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Read**: `src/mcp_defectdojo/audit_logging.py`, `src/mcp_defectdojo/client.py`
- **Action**:

  **server.py changes:**

  1. Add imports: `from .audit_logging import configure_logging, audit_tool` and `from fastmcp import Context`

  2. Add `ctx: Context` parameter to ALL 14 tool functions (13 + health_check). Place it as the last parameter in each signature. Example:
     - Before: `async def list_products(limit: int = 20, offset: int = 0):`
     - After: `async def list_products(limit: int = 20, offset: int = 0, ctx: Context = None):`
     Make `ctx` default to `None` so unit tests that don't provide it still work.

  3. Apply `@audit_tool` decorator to ALL 14 tool functions. Stack it BETWEEN `@mcp.tool` and `@_require_client`:
     ```python
     @mcp.tool
     @audit_tool
     @_require_client
     async def list_products(limit: int = 20, offset: int = 0, ctx: Context = None):
     ```
     For `health_check` which doesn't use `_require_client`:
     ```python
     @mcp.tool
     @audit_tool
     async def health_check(ctx: Context = None):
     ```

  4. **REMOVE** the 5 existing manual `logger.info(...)` calls from mutation tools (lines 143, 185, 229, 271, 304). The `audit_tool` decorator now handles all audit logging — keeping the manual calls would cause duplicate log entries.

  5. **REMOVE** the 2 lifespan `logger.info` calls for "client initialized" and "client closed" — these are lifecycle events, NOT tool calls. Keep them as-is (they already use `event_type: lifecycle`). Actually, do NOT remove these — only remove the tool_call logs.

  Clarification: Remove ONLY the 5 lines that have `extra={"event_type": "tool_call", ...}`. Keep the 3 lifecycle lines (lines 50, 53, 59) untouched.

- **Verification Steps**:
  1. `uv run pytest tests/ -x -q` — all existing tests pass
  2. Verify all 14 tool functions have `@audit_tool` decorator: `grep -c "@audit_tool" src/mcp_defectdojo/server.py` should return 14
  3. Verify all 14 tool functions have `ctx: Context` parameter: `grep -c "ctx: Context" src/mcp_defectdojo/server.py` should return 14
  4. Verify no manual `tool_call` logs remain: `grep -c "event_type.*tool_call" src/mcp_defectdojo/server.py` should return 0
  5. Verify lifecycle logs preserved: `grep -c "event_type.*lifecycle" src/mcp_defectdojo/server.py` should return 3
- **Done Criteria**: All 14 tools have `@audit_tool` + `ctx: Context`. No duplicate manual tool_call logs. All existing tests pass.
- **Dependencies**: T1

### Task T3: Audit coverage test suite

- **AC**: AC-4.3, AC-4.4, AC-4.5, AC-4.6, AC-4.7, AC-4.8, AC-4.9
- **Mode**: agent
- **Files to Create**: `tests/test_audit_coverage.py`
- **Files to Modify**: `tests/conftest.py`
- **Files to Read**: `src/mcp_defectdojo/audit_logging.py`, `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`, `tests/test_server.py`, `tests/test_audit_logging.py`
- **Action**:

  **conftest.py additions:**
  Add a `mock_ctx` fixture that creates a mock Context object:
  ```python
  @pytest.fixture
  def mock_ctx():
      ctx = MagicMock()
      ctx.request_id = "test-request-id-1234"
      ctx.client_id = "test-client"
      ctx.request_context = MagicMock()
      return ctx
  ```
  Also add an `anonymous_ctx` fixture where `ctx.client_id = None`.

  **tests/test_audit_coverage.py tests:**

  1. **`test_audit_tool_emits_structured_log`** — Decorate a simple async function with `@audit_tool`, call it with mock_ctx, capture log output, parse JSON, assert `tool_name`, `request_id`, `caller_id`, `request_params`, `outcome`, `duration_ms` are all present. (AC-4.3)
  2. **`test_audit_tool_success_outcome`** — Call a decorated function that returns normally, assert `outcome == "success"`. (AC-4.3)
  3. **`test_audit_tool_error_outcome`** — Call a decorated function that raises an exception, assert `outcome == "error"` and error detail is logged. Assert the exception is re-raised. (AC-4.9)
  4. **`test_audit_tool_duration_tracked`** — Call a decorated function, assert `duration_ms` is a positive number. (AC-4.8)
  5. **`test_audit_tool_caller_id_from_context`** — Call with mock_ctx where `client_id = "mcp-client"`, assert `caller_id == "mcp-client"`. (AC-4.5)
  6. **`test_audit_tool_anonymous_caller_warning`** — Call with anonymous_ctx where `client_id = None`, assert `caller_id == "anonymous"` and a WARNING-level log is emitted. (AC-4.6)
  7. **`test_request_id_propagates_to_client`** — Set `current_request_id` contextvar, call `client._request()` (mocked HTTP), capture log, assert `request_id` appears in client debug log. (AC-4.7)
  8. **`test_client_api_duration_tracked`** — Call `client._request()` (mocked HTTP), capture log, assert `api_duration_ms` is present and positive. (AC-4.7)
  9. **`test_read_tool_produces_audit_log`** — Call `list_products` (with mocked client and mock_ctx), capture log, assert an audit entry is emitted with `tool_name: "list_products"`. (AC-4.4)
  10. **`test_write_tool_produces_audit_log`** — Call `create_product` (with mocked client and mock_ctx), capture log, assert audit entry with `tool_name: "create_product"`. (AC-4.3)

  Testing approach: Use `capfd` or `io.StringIO` handler to capture structured JSON log output. Parse each line with `json.loads()`. For tool-level tests, use the existing `patched_client` pattern from test_server.py. For client-level tests, use `respx` mocking.

- **Verification Steps**:
  1. `uv run pytest tests/test_audit_coverage.py -v` — all 10 tests pass
  2. `uv run pytest tests/ -x -q` — full suite passes (no regressions)
  3. `uv run pytest tests/ --cov=mcp_defectdojo --cov-report=term-missing` — overall coverage ≥85%
- **Done Criteria**: All 10 tests pass. Full test suite passes. Coverage maintained.
- **Dependencies**: T1, T2

## Execution Strategy

### Wave 1 — Infrastructure
- Task T1: Audit decorator and client propagation infrastructure

### Wave 2 — Integration & Testing (sequential)
- Task T2: Apply audit decorator to all tools (depends on T1)
- Task T3: Audit coverage test suite (depends on T1, T2)

## Boundaries — DO NOT MODIFY

These files are OUT OF SCOPE for this phase:

- `src/mcp_defectdojo/models.py` — No model changes needed
- `src/mcp_defectdojo/__init__.py` — No package-level changes
- `tests/test_models.py` — Model tests unrelated
- `tests/test_audit_logging.py` — Phase 4.1 tests; do not modify
- `Dockerfile` — Container changes deferred
- `pyproject.toml` — No new dependencies (stdlib only)
- `.titan/ROADMAP.md` — Updated separately
- `.titan/REQUIREMENTS.md` — Updated separately

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 (T1) | human-verify | Review audit decorator and client changes |
| 2 | Wave 2 (T2, T3) | human-verify | Review tool integration and test results |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Context injection breaks existing tests | High | Medium | Make `ctx` default to `None`. audit_tool handles None ctx gracefully. |
| Decorator stacking order matters | Medium | High | `@mcp.tool` outermost, then `@audit_tool`, then `@_require_client` innermost. Test with actual tool call. |
| request_id RuntimeError in unit tests | High | Low | audit_tool catches RuntimeError and falls back to uuid4(). |
| Double logging (decorator + manual) | Medium | Medium | T2 explicitly removes manual tool_call log lines. Verify with grep. |
| functools.wraps signature preservation | Low | High | Already proven to work with _require_client. audit_tool uses same pattern. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget (3 tasks, 4 files to create/modify)
- [x] Total tasks ≤ 3
- [x] All task descriptions are detailed enough for a fresh-context executor

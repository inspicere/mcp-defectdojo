---
phase: "4.1"
name: Structured Log Infrastructure
goal: Replace unstructured text logging with structured JSON output, configurable log levels, and sensitive data redaction
branch: titan/phase-04-structured-audit-logging
status: built
created: 2026-05-08T21:00:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 4.1 — Structured Log Infrastructure — Execution Plan

## Goal
Every log line emitted by the MCP server must be a single JSON object parseable by `json.loads()`. Log verbosity must be controllable via `LOG_LEVEL` env var (default INFO). API keys, tokens, and Authorization header values must never appear in log output.

## Context
- FastMCP 3.2.4 is installed. `Middleware` class is NOT available at this version — Phase 4.2 will use a decorator pattern with `Context` injection instead.
- `Context` from `fastmcp.server` provides `request_id`, `client_id`, `session_id` — these will be leveraged in Phase 4.2 (not this phase).
- Current logging: 9 unstructured calls across server.py (5) and client.py (4) using stdlib `logging.getLogger(__name__)`.
- Server.py log calls: 5 `logger.info()` on mutations only (create_product, create_engagement, create_test, create_finding, update_finding) plus 2 in lifespan.
- Client.py log calls: 2 `logger.debug()` (request/response), 1 `logger.warning()` (API error), 1 `logger.error()` (connection failure), 1 `logger.warning()` (HTTP scheme).
- No log formatting is configured — output goes to stderr as default stdlib format.
- Test pattern: `respx` for HTTP mocking, `pytest-asyncio` with `asyncio_mode = "auto"`, fixtures in conftest.py.

## Acceptance Criteria (This Phase)

- **AC-4.2**: Given the server is running, When log output is captured, Then every line is valid JSON parseable by `json.loads()` — no unstructured text mixed in.
- **AC-4.10**: Given `LOG_LEVEL=DEBUG` env var, When the server starts, Then all log output (including request/response details) is emitted.
- **AC-4.11**: Given `LOG_LEVEL=WARNING` env var, When a successful tool call completes, Then no INFO-level log entry is emitted (only warnings and errors).
- **AC-4.12**: Given no `LOG_LEVEL` env var, When the server starts, Then the default level is INFO.
- **AC-4.13**: Given DEBUG-level logging enabled, When an API request is logged with headers, Then the `Authorization` header value is replaced with `Token ***REDACTED***`.
- **AC-4.14**: Given any log level, When `DEFECTDOJO_API_KEY` or `MCP_AUTH_TOKEN` values appear in any loggable context, Then they are redacted before emission.

## Tasks

### Task T1: Create audit_logging.py module

- **AC**: AC-4.2, AC-4.10, AC-4.11, AC-4.12, AC-4.13, AC-4.14
- **Mode**: agent
- **Files to Create**: `src/mcp_defectdojo/audit_logging.py`
- **Files to Read**: `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`
- **Action**:
  Create `src/mcp_defectdojo/audit_logging.py` with three components:

  1. **`StructuredJsonFormatter`** — subclass `logging.Formatter`. Override `format(record)` to return a single-line JSON string with these fields:
     - `timestamp`: ISO 8601 from `record.created` (use `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()`)
     - `level`: `record.levelname`
     - `logger`: `record.name`
     - `message`: `record.getMessage()`
     - Any extra fields passed via `record.__dict__` that are not in `logging.LogRecord.__dict__` (i.e., extra kwargs from `logger.info("msg", extra={...})`)
     Use `json.dumps(data, default=str)` to handle non-serializable types.

  2. **`RedactingFilter`** — subclass `logging.Filter`. Override `filter(record)` to:
     - Read `DEFECTDOJO_API_KEY` and `MCP_AUTH_TOKEN` from `os.environ` at filter time
     - In `record.msg` and `record.args`, replace any occurrence of those values with `***REDACTED***`
     - Replace any string matching `Token <value>` in the message with `Token ***REDACTED***`
     - Return `True` always (the filter modifies, never suppresses)

  3. **`configure_logging()`** — function that:
     - Reads `LOG_LEVEL` env var (default `"INFO"`)
     - Validates level is one of DEBUG, INFO, WARNING, ERROR, CRITICAL (case-insensitive); falls back to INFO if invalid
     - Gets the root logger
     - Removes all existing handlers from root logger
     - Creates a `logging.StreamHandler(sys.stderr)` with `StructuredJsonFormatter`
     - Adds `RedactingFilter` to the handler
     - Sets root logger level to the configured level
     - Adds the handler to the root logger

- **Verification Steps**:
  1. `uv run python -c "from mcp_defectdojo.audit_logging import StructuredJsonFormatter, RedactingFilter, configure_logging; print('imports OK')"`
  2. `uv run python -c "import json, logging; from mcp_defectdojo.audit_logging import configure_logging; configure_logging(); logging.getLogger('test').info('hello'); import sys"` — stderr output is valid JSON with `timestamp`, `level`, `logger`, `message` fields
  3. Verify `configure_logging()` without `LOG_LEVEL` env var sets level to INFO
- **Done Criteria**: Module exists, is importable, and all three components function as specified.
- **Dependencies**: none

### Task T2: Integrate structured logging into server.py and client.py

- **AC**: AC-4.2, AC-4.13, AC-4.14
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`
- **Files to Read**: `src/mcp_defectdojo/audit_logging.py`
- **Action**:
  Wire the structured logging infrastructure into the existing codebase:

  **server.py changes:**
  1. Add import: `from .audit_logging import configure_logging`
  2. In `lifespan()` function, add `configure_logging()` as the first line inside the `try` block (before `client = DefectDojoClient()`)
  3. Update the 5 mutation log calls (lines 141, 183, 227, 269, 302) to pass structured `extra` dicts. Example for create_product (line 141):
     - Before: `logger.info("Creating product: name=%s, prod_type_id=%d", name, prod_type_id)`
     - After: `logger.info("Creating product", extra={"event_type": "tool_call", "tool_name": "create_product", "request_params": {"name": name, "prod_type_id": prod_type_id}})`
  4. Update lifespan log calls (line 48 and 57) similarly with `extra={"event_type": "lifecycle"}`

  **client.py changes:**
  1. Update `_request()` debug log at line 45:
     - Before: `logger.debug("API request: %s %s", method, path)`
     - After: `logger.debug("API request", extra={"event_type": "api_request", "method": method, "path": path})`
  2. Update `_request()` debug log at line 48:
     - Before: `logger.debug("API response: %s %s → %d", method, path, response.status_code)`
     - After: `logger.debug("API response", extra={"event_type": "api_response", "method": method, "path": path, "status_code": response.status_code})`
  3. Update `_request()` warning log at line 53:
     - Before: `logger.warning("API error: %s %s → %d", method, path, e.response.status_code)`
     - After: `logger.warning("API error", extra={"event_type": "api_error", "method": method, "path": path, "status_code": e.response.status_code})`
  4. Update `_request()` error log at line 61:
     - Before: `logger.error("Connection failed: %s %s — %s", method, path, e)`
     - After: `logger.error("Connection failed", extra={"event_type": "connection_error", "method": method, "path": path, "error": str(e)})`
  5. Update HTTP scheme warning at line 26:
     - Before: `logger.warning("DEFECTDOJO_URL uses HTTP — API key will be transmitted in cleartext")`
     - After: `logger.warning("DEFECTDOJO_URL uses HTTP — API key will be transmitted in cleartext", extra={"event_type": "security_warning"})`

- **Verification Steps**:
  1. `uv run pytest tests/ -x -q` — all existing tests pass (no regressions)
  2. `LOG_LEVEL=DEBUG uv run python -c "import json, sys, io; sys.stderr = io.StringIO(); from mcp_defectdojo.audit_logging import configure_logging; configure_logging(); import logging; logging.getLogger('test').info('test', extra={'event_type': 'tool_call'}); output = sys.stderr.getvalue(); data = json.loads(output.strip()); assert data['event_type'] == 'tool_call'"` — extra fields appear in JSON output
  3. Verify no `%s` or `%d` format string patterns remain in server.py or client.py logger calls (all structured via extra)
- **Done Criteria**: All log calls in server.py and client.py use structured `extra` dicts. `configure_logging()` is called in lifespan. All existing tests pass.
- **Dependencies**: T1

### Task T3: Test suite for structured logging

- **AC**: AC-4.2, AC-4.10, AC-4.11, AC-4.12, AC-4.13, AC-4.14
- **Mode**: agent
- **Files to Create**: `tests/test_audit_logging.py`
- **Files to Read**: `src/mcp_defectdojo/audit_logging.py`, `tests/conftest.py`, `tests/test_client.py`
- **Action**:
  Create `tests/test_audit_logging.py` with the following tests:

  1. **`test_structured_json_format`** — call `configure_logging()`, emit an INFO log, capture stderr, parse with `json.loads()`, assert fields `timestamp`, `level`, `logger`, `message` are present. (AC-4.2)
  2. **`test_extra_fields_included`** — emit a log with `extra={"event_type": "tool_call", "tool_name": "list_products"}`, parse JSON, assert `event_type` and `tool_name` appear in output. (AC-4.2)
  3. **`test_log_level_debug`** — set `LOG_LEVEL=DEBUG` via `monkeypatch.setenv`, call `configure_logging()`, emit a DEBUG log, assert it appears in output. (AC-4.10)
  4. **`test_log_level_warning_suppresses_info`** — set `LOG_LEVEL=WARNING`, call `configure_logging()`, emit an INFO log, assert stderr is empty. Emit a WARNING log, assert it appears. (AC-4.11)
  5. **`test_log_level_default_info`** — unset `LOG_LEVEL` via `monkeypatch.delenv`, call `configure_logging()`, emit a DEBUG log (should not appear), emit an INFO log (should appear). (AC-4.12)
  6. **`test_log_level_invalid_falls_back`** — set `LOG_LEVEL=GARBAGE`, call `configure_logging()`, verify effective level is INFO. (AC-4.12)
  7. **`test_redaction_api_key`** — set `DEFECTDOJO_API_KEY=secret-key-123`, call `configure_logging()`, emit a log containing `"secret-key-123"` in the message, assert output contains `***REDACTED***` and does not contain `secret-key-123`. (AC-4.14)
  8. **`test_redaction_auth_header`** — emit a log containing `"Token abc123"`, assert output contains `Token ***REDACTED***` and does not contain `abc123`. (AC-4.13)
  9. **`test_redaction_mcp_auth_token`** — set `MCP_AUTH_TOKEN=mcp-secret-456`, emit a log containing that value, assert redacted. (AC-4.14)
  10. **`test_all_output_is_json`** — configure logging, emit 5 log messages at various levels, capture all stderr output, split by newlines, assert each non-empty line is valid JSON. (AC-4.2)

  Testing approach: Use a custom `logging.StreamHandler` writing to `io.StringIO()` to capture log output within each test, or use `capfd`/capsys. Each test should call `configure_logging()` with a fresh handler setup. Use `monkeypatch` for env vars.

- **Verification Steps**:
  1. `uv run pytest tests/test_audit_logging.py -v` — all 10 tests pass
  2. `uv run pytest tests/ -x -q` — full suite passes (no regressions)
  3. `uv run pytest tests/ --cov=mcp_defectdojo --cov-report=term-missing` — audit_logging.py has ≥90% coverage
- **Done Criteria**: All 10 tests pass. Full test suite passes. audit_logging.py coverage ≥90%.
- **Dependencies**: T1, T2

## Execution Strategy

### Wave 1 — Foundation (sequential)
- Task T1: Create audit_logging.py module

### Wave 2 — Integration & Testing (sequential)
- Task T2: Integrate structured logging into server.py and client.py (depends on T1)
- Task T3: Test suite for structured logging (depends on T1, T2)

## Boundaries — DO NOT MODIFY

These files are OUT OF SCOPE for this phase:

- `src/mcp_defectdojo/models.py` — No model changes needed for logging infrastructure
- `src/mcp_defectdojo/__init__.py` — No package-level changes needed
- `tests/test_models.py` — Model tests unrelated to logging
- `Dockerfile` — Container changes deferred
- `pyproject.toml` — No new dependencies needed (stdlib logging only)
- `.titan/ROADMAP.md` — Updated separately by orchestrator
- `.titan/REQUIREMENTS.md` — Updated separately by orchestrator

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 (T1) | human-verify | Review audit_logging.py module before integration |
| 2 | Wave 2 (T2, T3) | human-verify | Review integration changes and test results |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| FastMCP internal logging emits unstructured text that bypasses our formatter | Medium | Medium | configure_logging() sets root logger — all loggers inherit. Verify by running server with LOG_LEVEL=DEBUG and checking all output. |
| RedactingFilter performance on high-volume log output | Low | Low | Filter only scans string fields, not binary. Log volume in MCP server is low (one entry per tool call). |
| Existing tests that assert on caplog text format break after structured logging | Medium | Medium | T3 verification step runs full suite. If caplog tests break, update them to parse JSON or use `caplog.records` instead of `caplog.text`. |
| uvicorn/httpx emit their own log lines that aren't JSON | Medium | Low | configure_logging() reconfigures root logger; all stdlib loggers inherit. Third-party loggers that create their own handlers need explicit reconfiguration — check during verify. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget (3 tasks, 3 files to create/modify)
- [x] Total tasks ≤ 3
- [x] In-session tasks are in the latest possible wave
- [x] All task descriptions are detailed enough for a fresh-context executor

# Requirements — mcp-defectdojo

## Functional Requirements

### Must-Have (P0)

#### FR-006: Containerization
The MCP server must be containerized to run in the Laima network.
**Acceptance Criteria:**
- Given a Dockerfile, When the image is built, Then it starts the MCP server using `uv run mcp-defectdojo`.

#### FR-007: Deployment Automation
The MCP server must be deployable via Ansible.
**Acceptance Criteria:**
- Given an Ansible playbook, When executed, Then the container is deployed and running on the target Laima host.

#### FR-008: Health Check Endpoint
The server must provide a health status.
**Acceptance Criteria:**
- Given a running service, When health-checked, Then it returns a 200 OK status.

### Non-Functional Requirements (NFR)

#### NFR-003: Configuration
Deployment must use secrets management from the Vault to inject `DEFECTDOJO_API_KEY`.

---

## Phase 2: Audit Remediation

### Must-Have (P0)

#### FR-009: Security Configuration
Harden project configuration and container for production use.
**Acceptance Criteria:**
- Given `.gitignore`, When inspected, Then `.env` and `.env.*` (except `.env.example`) are excluded from version control.
- Given the Dockerfile, When the image is built and run, Then the process runs as a non-root user (`appuser`).
- Given `__init__.py`, When inspected, Then it contains no dead code (no vestigial `main()` function).

#### FR-010: Client Lifecycle Management
The HTTP client must be robust with proper async lifecycle, timeouts, and error handling.
**Acceptance Criteria:**
- Given `DefectDojoClient`, When initialized, Then `httpx.AsyncClient` is created with explicit timeout `httpx.Timeout(30.0, connect=5.0)`.
- Given a network error (ConnectError, TimeoutException), When a tool is called, Then the error is caught and wrapped as a descriptive RuntimeError (not a raw httpx exception).
- Given the `_request` method's inner try/except, When an HTTP error occurs, Then the except clause catches only `json.JSONDecodeError` (not bare `Exception`).
- Given `client.py`, When inspected, Then unused imports (`Dict`, `List`) are removed and `get_findings` parameter `test_id` has correct `Optional[int]` type hint.

#### FR-011: Server Lifespan Integration
The server must manage the client lifecycle via FastMCP lifespan and provide an honest health check.
**Acceptance Criteria:**
- Given server startup, When FastMCP lifespan begins, Then `DefectDojoClient` is created within the async context (not at module level).
- Given server shutdown, When FastMCP lifespan ends, Then `await client._client.aclose()` is called.
- Given the `health_check` tool, When called, Then it makes an actual API call to DefectDojo (e.g., `GET /products/?limit=1`) and returns real connectivity status.
- Given missing `DEFECTDOJO_URL` or `DEFECTDOJO_API_KEY`, When the server starts, Then it logs a warning but does not crash at import time.

---

## Phase 3: Quality Improvements (Deferred)

#### FR-012: Input Validation
#### FR-013: Pagination Metadata
#### FR-014: Structured Logging

---

## Phase 4: Structured Audit Logging

### Must-Have (P0)

#### FR-015: Structured JSON Log Format
Every log line must be a single JSON object with standardized fields for machine parsing.
**Acceptance Criteria:**
- AC-4.1: Given any tool invocation, When the request completes (success or error), Then a single JSON log line is emitted containing: `timestamp` (ISO 8601), `event_type` (tool_call|api_request|lifecycle), `tool_name`, `request_params` (sanitized), `outcome` (success|error), `duration_ms`, and `level`.
- AC-4.2: Given the server is running, When log output is captured, Then every line is valid JSON parseable by `json.loads()` — no unstructured text mixed in.

#### FR-016: Full Read Audit Trail
All data access operations must be logged, not just mutations.
**Acceptance Criteria:**
- AC-4.3: Given a `list_*` or `get_*` tool call, When it completes, Then an INFO-level structured log entry is emitted with `tool_name`, `request_params`, `item_count` (for list operations), and `duration_ms`.
- AC-4.4: Given a `create_*` or `update_*` tool call, When it completes, Then the log entry additionally includes `resource_id` (the ID of the created/updated resource).

#### FR-017: Correlation IDs
Each tool invocation must carry a unique identifier traceable across server and client layers.
**Acceptance Criteria:**
- AC-4.5: Given a tool invocation, When the server handles it, Then a UUID `request_id` is generated and included in both the server-layer log entry and all client-layer log entries for that request.

#### FR-018: Request Duration Tracking
Wall-clock timing for every tool invocation and upstream API call.
**Acceptance Criteria:**
- AC-4.6: Given any tool invocation, When it completes, Then `duration_ms` is present in the log entry, measured from tool entry to tool return.
- AC-4.7: Given the client `_request` method, When an API call completes, Then `api_duration_ms` is logged separately at the client layer.

#### FR-019: Caller Identity Extraction
Log entries must identify which MCP client made the request.
**Acceptance Criteria:**
- AC-4.8: Given an authenticated MCP request, When a tool is called, Then the log entry includes `caller_id` extracted from the auth token's `client_id` field.
- AC-4.9: Given an unauthenticated MCP request (no token), When a tool is called, Then `caller_id` is set to `"anonymous"` and a WARNING-level log entry is emitted.

#### FR-020: Configurable Log Levels
Log verbosity must be controllable at runtime via environment variable.
**Acceptance Criteria:**
- AC-4.10: Given `LOG_LEVEL=DEBUG` env var, When the server starts, Then all log output (including request/response bodies) is emitted.
- AC-4.11: Given `LOG_LEVEL=WARNING` env var, When a successful tool call completes, Then no INFO-level log entry is emitted (only warnings and errors).
- AC-4.12: Given no `LOG_LEVEL` env var, When the server starts, Then the default level is INFO.

#### FR-021: Sensitive Data Redaction
Credentials and secrets must never appear in log output.
**Acceptance Criteria:**
- AC-4.13: Given DEBUG-level logging enabled, When an API request is logged with headers, Then the `Authorization` header value is replaced with `Token ***REDACTED***`.
- AC-4.14: Given any log level, When `DEFECTDOJO_API_KEY` or `MCP_AUTH_TOKEN` values appear in any loggable context, Then they are redacted before emission.

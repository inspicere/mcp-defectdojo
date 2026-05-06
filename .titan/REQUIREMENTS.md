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

---
phase: "03.2.2"
name: Test Coverage
goal: Establish pytest infrastructure and comprehensive test suite for all modules
branch: titan/phase-03-quality-improvements
status: built
created: 2026-05-07T05:30:00Z
estimated_tasks: 3
estimated_waves: 3
---

# Phase 03.2.2 — Test Coverage — Execution Plan

## Goal
Establish test infrastructure (pytest + async support + HTTP mocking) and write comprehensive tests covering client, server, and model modules. This resolves the zero-test-coverage gap (SB-09) that has been flagged in every verification since Phase 02.

## Context
- Zero test infrastructure exists — no `tests/` directory, no test dependencies in `pyproject.toml`
- The project uses `uv` for dependency management with a `src/` layout
- All tool functions are plain async functions decorated with `@mcp.tool()` — callable directly without MCP transport
- Client uses `httpx.AsyncClient` — best mocked with `respx` library (httpx-native mock transport)
- Server tools use a module-level global `client` — must be patched for testing
- Models use Pydantic v2 with `Field(alias=...)` and `populate_by_name` config
- Key code paths to test: `_request` (5 branches), `_format_response` (4 branches), 14 tool functions (null guard + validation + happy path + error), lifespan (success + ValueError), models (valid + invalid + alias)

## Acceptance Criteria (This Phase)

| ID | Criterion |
|----|-----------|
| AC-3.2.2a | `uv run pytest` executes without errors and discovers tests in `tests/` directory |
| AC-3.2.2b | `tests/conftest.py` provides reusable fixtures: mock environment vars, mock httpx transport, mock server client |
| AC-3.2.2c | `tests/test_models.py` verifies all 5 Pydantic models accept valid data, reject invalid data, and handle field aliases |
| AC-3.2.2d | `tests/test_client.py` verifies DefectDojoClient init validation, all 13 API methods (happy path), and all 4 error paths in `_request` |
| AC-3.2.2e | `tests/test_server.py` verifies null guards, input validation, happy paths, and error responses for all 14 tool functions plus `_format_response` and `lifespan` |
| AC-3.2.2f | Test coverage ≥ 80% on lines (measured by `pytest-cov`) |

## Tasks

### Task T1: Infrastructure & Model Tests

- **AC**: AC-3.2.2a, AC-3.2.2b, AC-3.2.2c
- **Mode**: agent
- **Files to Modify**: `pyproject.toml`
- **Files to Create**: `tests/__init__.py`, `tests/conftest.py`, `tests/test_models.py`
- **Files to Read** (reference only): `src/mcp_defectdojo/models.py`, `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/server.py`
- **Action**:

  MODIFIED: `pyproject.toml` — add test dependencies and pytest config
  - Current: No `[dependency-groups]` section. No `[tool.pytest.ini_options]` section.
  - Target: Add after the `[build-system]` section:
    ```toml
    [dependency-groups]
    dev = [
        "pytest>=8.0",
        "pytest-asyncio>=0.25",
        "pytest-cov>=6.0",
        "respx>=0.22",
    ]

    [tool.pytest.ini_options]
    asyncio_mode = "auto"
    testpaths = ["tests"]
    ```

  ADDED: `tests/__init__.py` — empty file (package marker)

  ADDED: `tests/conftest.py` — shared fixtures:
  - `mock_env(monkeypatch)` — sets `DEFECTDOJO_URL="http://test.defectdojo.local"` and `DEFECTDOJO_API_KEY="test-api-key-12345"` as env vars
  - `mock_client(mock_env)` — creates a real `DefectDojoClient` instance (env vars are set by mock_env) for use by client tests
  - `sample_product()` — returns `{"id": 1, "name": "Test Product", "description": "A test product", "prod_type": 1}`
  - `sample_engagement()` — returns `{"id": 1, "product": 2, "name": "Test Engagement", "target_start": "2026-01-01", "target_end": "2026-12-31"}`
  - `sample_test_obj()` — returns `{"id": 1, "engagement": 3, "test_type": 1, "title": "Unit Test"}`
  - `sample_finding()` — returns `{"id": 1, "test": 4, "title": "XSS Vuln", "severity": "High", "description": "Found XSS", "active": True, "verified": False, "mitigated": None, "is_mitigated": False, "out_of_scope": False, "false_p": False, "duplicate": False}`
  - `paginated_response(items, count=None)` — helper function (not fixture) that wraps items in `{"count": count or len(items), "results": items}`

  ADDED: `tests/test_models.py` — model validation tests:
  - `test_product_summary_valid(sample_product)` — instantiate ProductSummary, assert fields
  - `test_product_summary_missing_field()` — omit `name`, assert `ValidationError`
  - `test_engagement_summary_alias(sample_engagement)` — verify `product_id` populated from `product` alias
  - `test_engagement_summary_optional_name()` — verify `name=None` is valid
  - `test_test_summary_alias(sample_test_obj)` — verify `engagement_id` populated from `engagement` alias
  - `test_finding_summary_all_fields(sample_finding)` — verify all fields including booleans
  - `test_finding_summary_missing_required()` — omit `title`, assert `ValidationError`
  - `test_severity_enum_values()` — verify all 5 values: Critical, High, Medium, Low, Info
  - `test_severity_enum_invalid()` — verify invalid value raises ValueError
  - `test_pagination_metadata_valid()` — construct with count=50, offset=0, limit=20, has_next=True
  - `test_pagination_metadata_has_next_false()` — count=5, offset=0, limit=20, has_next=False

  After creating files, run: `cd /home/terrabot/mcp-defectdojo && uv sync --group dev` to install test dependencies.

- **Verification Steps**:
  1. Run `uv run pytest tests/test_models.py -v` and confirm all tests pass
  2. Run `grep 'pytest' pyproject.toml` and confirm test dependencies present
  3. Run `grep 'asyncio_mode' pyproject.toml` and confirm pytest-asyncio configured
  4. Run `python3 -c "import tests.conftest"` from the project root (or verify file exists with ls)
- **Done Criteria**: `uv run pytest tests/test_models.py` passes with 11 tests; all fixtures importable from conftest.
- **Dependencies**: none

### Task T2: Client Tests

- **AC**: AC-3.2.2d
- **Mode**: agent
- **Files to Modify**: none
- **Files to Create**: `tests/test_client.py`
- **Files to Read** (reference only): `src/mcp_defectdojo/client.py`, `tests/conftest.py`
- **Action**:

  ADDED: `tests/test_client.py` — test DefectDojoClient using `respx` for HTTP mocking:

  **Init tests:**
  - `test_client_init_success(mock_env)` — create DefectDojoClient, assert `base_url` and `api_key` are set, assert `_client` is an `httpx.AsyncClient` with base_url ending in `/api/v2`
  - `test_client_init_missing_url(monkeypatch)` — set only API_KEY, assert `ValueError` raised with message containing "DEFECTDOJO_URL"
  - `test_client_init_missing_key(monkeypatch)` — set only URL, assert `ValueError` raised
  - `test_client_init_both_missing()` — no env vars, assert `ValueError`
  - `test_client_aclose(mock_client)` — call `await mock_client.aclose()`, assert no error

  **_request method tests (use `respx` with `mock_client`):**
  - `test_request_get_success(mock_client)` — mock GET `/products/` returning `{"count": 1, "results": [...]}`, call `await mock_client.get_products()`, assert result matches
  - `test_request_post_success(mock_client)` — mock POST `/products/` returning product dict, call `await mock_client.create_product(...)`, assert result
  - `test_request_204_no_content(mock_client)` — mock returning status 204, assert result is `{}`
  - `test_request_http_error_json(mock_client)` — mock returning 404 with JSON body `{"detail": "Not found"}`, assert `RuntimeError` raised containing "404" and "Not found"
  - `test_request_http_error_non_json(mock_client)` — mock returning 500 with plain text body, assert `RuntimeError` raised containing "500"
  - `test_request_connect_error(mock_client)` — mock raising `httpx.ConnectError`, assert `RuntimeError` raised containing "Failed to connect"
  - `test_request_timeout(mock_client)` — mock raising `httpx.ReadTimeout`, assert `RuntimeError` raised containing "Failed to connect"

  **API method tests (one per method, happy path with respx):**
  - `test_get_products(mock_client)` — mock GET `/products/?limit=20&offset=0`, verify called
  - `test_get_product(mock_client)` — mock GET `/products/5/`, verify called with correct path
  - `test_create_product(mock_client)` — mock POST `/products/`, verify JSON body sent with correct fields
  - `test_get_engagements(mock_client)` — mock GET `/engagements/?product=1&limit=20&offset=0`
  - `test_get_engagement(mock_client)` — mock GET `/engagements/3/`
  - `test_create_engagement(mock_client)` — mock POST `/engagements/`, verify JSON body
  - `test_get_tests(mock_client)` — mock GET `/tests/?engagement=2&limit=20&offset=0`
  - `test_get_test(mock_client)` — mock GET `/tests/7/`
  - `test_create_test(mock_client)` — mock POST `/tests/`, verify JSON body
  - `test_get_findings(mock_client)` — mock GET `/findings/?limit=20&offset=0` (no test_id)
  - `test_get_findings_with_test_id(mock_client)` — mock GET `/findings/?test=4&limit=20&offset=0`
  - `test_get_finding(mock_client)` — mock GET `/findings/9/`
  - `test_create_finding(mock_client)` — mock POST `/findings/`, verify JSON body with all fields
  - `test_update_finding(mock_client)` — mock PATCH `/findings/9/`, verify only passed kwargs sent

  **Important implementation notes:**
  - Use `respx.mock` decorator or context manager on each test
  - The `mock_client` fixture provides a real `DefectDojoClient` with env vars set — respx intercepts the httpx transport
  - Use `respx.route(method="GET", path="/products/").mock(return_value=httpx.Response(200, json={...}))` pattern
  - For the `mock_client` fixture in conftest.py, ensure it's usable with respx by NOT pre-configuring a mock transport — respx patches at the httpx level globally when used as decorator/context manager

- **Verification Steps**:
  1. Run `uv run pytest tests/test_client.py -v` and confirm all tests pass
  2. Run `uv run pytest tests/test_client.py --co -q` and confirm ≥ 20 tests collected
  3. Run `grep -c 'async def test_' tests/test_client.py` and confirm count ≥ 20
- **Done Criteria**: `uv run pytest tests/test_client.py` passes with all tests green; covers init, _request error paths, and all 13 API methods.
- **Dependencies**: T1 (needs conftest.py fixtures and dev dependencies installed)

### Task T3: Server Tests

- **AC**: AC-3.2.2e, AC-3.2.2f
- **Mode**: agent
- **Files to Modify**: none
- **Files to Create**: `tests/test_server.py`
- **Files to Read** (reference only): `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/models.py`, `tests/conftest.py`
- **Action**:

  ADDED: `tests/test_server.py` — test all server tool functions using `unittest.mock.AsyncMock`:

  **Strategy:** Patch `mcp_defectdojo.server.client` with an `AsyncMock` before calling tool functions. This tests tool logic (null guards, validation, formatting) independently of HTTP.

  **Lifespan tests:**
  - `test_lifespan_success(mock_env)` — use `async with lifespan(mcp)` from `mcp_defectdojo.server`, assert `server.client` is not None after entry, assert `aclose` called after exit. Import `mcp_defectdojo.server as server_module` to access the global.
  - `test_lifespan_missing_env()` — no env vars set, assert `ValueError` raised within the context manager

  **_format_response tests:**
  - `test_format_response_list(sample_product)` — call `_format_response({"count": 1, "results": [sample_product]}, ProductSummary)`, parse JSON result, assert `items` has 1 entry and `pagination` has correct metadata
  - `test_format_response_single(sample_product)` — call `_format_response(sample_product, ProductSummary)`, parse JSON, assert product fields present
  - `test_format_response_validation_error_list()` — pass invalid data in results list, assert return starts with "ERROR: Invalid API response data:"
  - `test_format_response_validation_error_single()` — pass invalid single dict, assert ERROR string returned

  **Null guard tests (parametrized):**
  - `test_tool_null_guard(tool_func)` — parametrize over all 14 tool functions. Set `server_module.client = None`. Call each with minimal valid args. Assert return contains "ERROR: DefectDojo client not initialized". Use `@pytest.mark.parametrize` with a list of (function, kwargs) tuples.

  **Input validation tests:**
  - `test_list_products_limit_too_high(patched_client)` — call `list_products(limit=200)`, assert ERROR about limit
  - `test_list_products_limit_too_low(patched_client)` — call `list_products(limit=0)`, assert ERROR
  - `test_list_products_negative_offset(patched_client)` — call `list_products(offset=-1)`, assert ERROR
  - `test_get_product_zero_id(patched_client)` — call `get_product(0)`, assert ERROR about product_id
  - `test_get_product_negative_id(patched_client)` — call `get_product(-5)`, assert ERROR
  - `test_create_finding_invalid_severity(patched_client)` — call `create_finding(1, "t", "Invalid", "d")`, assert ERROR about severity
  - `test_create_finding_zero_test_id(patched_client)` — call `create_finding(0, "t", "High", "d")`, assert ERROR about test_id
  - `test_update_finding_no_fields(patched_client)` — call `update_finding(1)`, assert ERROR about no fields
  - `test_list_engagements_zero_product_id(patched_client)` — assert ERROR
  - `test_list_tests_zero_engagement_id(patched_client)` — assert ERROR
  - `test_create_test_zero_test_type_id(patched_client)` — assert ERROR

  **Happy path tests (with mocked client):**
  - `test_health_check_ok(patched_client, sample_product)` — mock `client.get_products` returning paginated products, assert "OK: DefectDojo is reachable"
  - `test_health_check_unhealthy(patched_client)` — mock `client.get_products` raising RuntimeError, assert "UNHEALTHY:"
  - `test_list_products_success(patched_client, sample_product)` — mock returns paginated, parse JSON result, assert items and pagination
  - `test_get_product_success(patched_client, sample_product)` — mock returns single dict, parse JSON
  - `test_create_product_success(patched_client, sample_product)` — mock returns created, verify logged (optional)
  - `test_list_engagements_success(patched_client, sample_engagement)` — similar pattern
  - `test_create_engagement_success(patched_client, sample_engagement)` — similar
  - `test_list_findings_with_test_id(patched_client, sample_finding)` — verify test_id passed through
  - `test_update_finding_partial(patched_client, sample_finding)` — pass only `severity="Low"`, verify only severity in kwargs to client

  **Implementation notes:**
  - Create a `patched_client` fixture in this file (or add to conftest.py): uses `unittest.mock.patch("mcp_defectdojo.server.client")` to inject an `AsyncMock` with pre-configured return values
  - For parametrized null guard test, the tool functions and their minimal kwargs are:
    ```python
    TOOL_FUNCTIONS = [
        (health_check, {}),
        (list_products, {"limit": 20, "offset": 0}),
        (get_product, {"product_id": 1}),
        (create_product, {"name": "x", "description": "x", "prod_type_id": 1}),
        (list_engagements, {"product_id": 1, "limit": 20, "offset": 0}),
        (get_engagement, {"engagement_id": 1}),
        (create_engagement, {"product_id": 1, "name": "x", "target_start": "2026-01-01", "target_end": "2026-12-31"}),
        (list_tests, {"engagement_id": 1, "limit": 20, "offset": 0}),
        (get_test, {"test_id": 1}),
        (create_test, {"engagement_id": 1, "test_type_id": 1, "target_start": "2026-01-01", "target_end": "2026-12-31"}),
        (list_findings, {"test_id": None, "limit": 20, "offset": 0}),
        (get_finding, {"finding_id": 1}),
        (create_finding, {"test_id": 1, "title": "x", "severity": "High", "description": "x", "active": True, "verified": False}),
        (update_finding, {"finding_id": 1, "title": "updated"}),
    ]
    ```
  - Import tool functions directly: `from mcp_defectdojo.server import health_check, list_products, ...`
  - Import `mcp_defectdojo.server as server_module` for accessing/patching the `client` global

  **Coverage check:**
  - After all tests pass, run `uv run pytest --cov=mcp_defectdojo --cov-report=term-missing` and verify ≥ 80% line coverage

- **Verification Steps**:
  1. Run `uv run pytest tests/test_server.py -v` and confirm all tests pass
  2. Run `uv run pytest --cov=mcp_defectdojo --cov-report=term-missing` and confirm ≥ 80% coverage
  3. Run `uv run pytest tests/ -v` and confirm full suite passes (all 3 test files)
  4. Run `grep -c 'async def test_' tests/test_server.py` and confirm count ≥ 25
- **Done Criteria**: Full test suite passes; coverage ≥ 80% on all modules; null guards, validation, happy paths, and error handling all verified.
- **Dependencies**: T1 (needs conftest fixtures), T2 (not a hard dependency, but T2 validates fixtures work correctly with respx before T3 uses AsyncMock approach)

## Execution Strategy

### Wave 1 — Foundation (sequential)
T1 establishes infrastructure, installs deps, and proves the test framework works with model tests.
- Task T1: Infrastructure & Model Tests

### Wave 2 — Client Layer (sequential, depends on Wave 1)
T2 tests the HTTP client using respx mocking. Validates that conftest fixtures work with real async tests.
- Task T2: Client Tests (depends on T1)

### Wave 3 — Server Layer (sequential, depends on Wave 2)
T3 tests all tool functions and runs coverage report. Depends on T1 for fixtures; sequenced after T2 to validate pattern works.
- Task T3: Server Tests (depends on T1, T2)

## Boundaries — DO NOT MODIFY

These files and directories are OUT OF SCOPE for this phase:

- `src/mcp_defectdojo/client.py` — Source under test; must not change
- `src/mcp_defectdojo/server.py` — Source under test; must not change
- `src/mcp_defectdojo/models.py` — Source under test; must not change
- `src/mcp_defectdojo/__init__.py` — No changes needed
- `Dockerfile` — Deployment config; not related to tests
- `deploy/` — Ansible playbooks; out of scope
- `.gitignore` — Finalized in Phase 2
- `uv.lock` — Will be auto-updated by `uv sync` but should not be manually edited

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 (T1) complete | human-verify | Confirm `uv run pytest tests/test_models.py` passes and deps installed |
| 2 | Wave 2 (T2) complete | human-verify | Confirm client tests pass with respx mocking |
| 3 | Wave 3 (T3) complete | human-verify | Confirm full suite passes and coverage ≥ 80% |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| respx incompatibility with httpx version | Low | High | `httpx>=0.28.1` is recent; respx 0.22+ supports it. Pin `respx>=0.22` |
| pytest-asyncio auto mode conflicts with tool decorators | Medium | Medium | FastMCP `@mcp.tool()` wraps functions but they remain async callables. Test by calling directly, not through MCP transport |
| Coverage below 80% due to lifespan/main code paths | Low | Low | Lifespan is testable. `main()` just calls `mcp.run()` — exclude from coverage or test with mock |
| Module-level `client = None` global causes import-time issues in tests | Medium | Medium | Always patch `server_module.client` before calling tool functions; conftest handles this |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic (T1 → T2 → T3)
- [x] Total scope fits context budget (~45% estimated)
- [x] No task touches more than 5 files
- [x] No banned phrases in task descriptions

---
phase: "03.2.1"
name: Robustness & Logging
goal: Fix all robustness issues and add structured logging for audit trails
branch: titan/phase-03-quality-improvements
status: built
created: 2026-05-07T04:00:00Z
estimated_tasks: 3
estimated_waves: 3
---

# Phase 03.2.1 — Robustness & Logging — Execution Plan

## Goal
Fix all deferred robustness findings (lifespan fragility, null guards, validation gaps, ValidationError handler) and add structured logging for API calls and mutations to establish an audit trail.

## Context
- Phase 3.2 was split into 3.2.1 (robustness + logging) and 3.2.2 (test coverage) because the combined scope exceeded the 3-task budget
- 14 deferred findings from Phase 02 and Phase 03.1 evaluations need resolution
- The lifespan function has 3 related bugs: client outside try (SB-02), private aclose (SA-01), no ValueError handler (SA-001)
- All 14 tool functions access module-level `client` without null guard — will AttributeError if called pre-lifespan
- `logger` is declared in client.py but never used; no logging exists anywhere in the project
- ValidationError handler uses fragile `e.errors()[0]['msg']` that will IndexError on empty errors list
- 5 ID parameters lack validation: product_id in list_engagements, engagement_id in list_tests, test_id in list_findings/create_finding, test_type_id in create_test
- `valid_severities` list is recomputed identically in create_finding (line 163) and update_finding (line 190)

## Acceptance Criteria (This Phase)

| ID | Criterion | Source |
|----|-----------|--------|
| AC-3.2.1a | Lifespan handles missing env vars with logged error instead of unhandled crash | SA-001 |
| AC-3.2.1b | Lifespan finally block uses public `client.aclose()` with None guard | SA-01, SB-02 |
| AC-3.2.1c | All 14 tools return descriptive error string when client is None | SA-002, SB-03 |
| AC-3.2.1d | ValidationError handler uses `str(e)` instead of `e.errors()[0]['msg']` | SB-02 (3.1) |
| AC-3.2.1e | All ID parameters validated > 0: product_id, engagement_id, test_id, test_type_id | SA-02, SA-03, SA-05, SA-06 |
| AC-3.2.1f | VALID_SEVERITIES extracted as module-level constant | SB-07 |
| AC-3.2.1g | client._request logs all API calls (method, path, status) | FR-014, SB-04 |
| AC-3.2.1h | Mutation tools (create_*, update_*) log invocations with key parameters | FR-014 |
| AC-3.2.1i | All 14 tool docstrings document parameter constraints and return format | SB-08 |
| AC-3.2.1j | Dockerfile comment accurately describes UV_CACHE_DIR behavior | SB-10 |

## Tasks

### Task T1: Foundation — Client Logging, Lifespan & Dockerfile

- **AC**: AC-3.2.1a, AC-3.2.1b, AC-3.2.1g, AC-3.2.1j
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/server.py`, `Dockerfile`
- **Files to Create**: none
- **Files to Read** (reference only): `src/mcp_defectdojo/models.py`
- **Action**:

  MODIFIED: `src/mcp_defectdojo/client.py` — `_request()` method (lines 32-47)
  - Current: No log statements. `logger` declared at line 7 but unused.
  - Target: Add 3 log statements to `_request()`:
    1. Before the request: `logger.debug("API request: %s %s", method, path)` — first line of method
    2. After successful response: `logger.debug("API response: %s %s → %d", method, path, response.status_code)` — after `response.raise_for_status()`
    3. On HTTP error: `logger.warning("API error: %s %s → %d", method, path, e.response.status_code)` — first line inside `except httpx.HTTPStatusError`
    4. On connection error: `logger.error("Connection failed: %s %s — %s", method, path, e)` — first line inside `except (httpx.ConnectError, httpx.TimeoutException)`
  - Do NOT change any other lines in client.py. Do NOT change function signatures.

  MODIFIED: `src/mcp_defectdojo/server.py` — imports and lifespan function ONLY (lines 1-24)
  - Current imports (lines 1-10): no `logging` import.
  - Target imports: Add `import logging` after line 1 (`import json`). Add `logger = logging.getLogger(__name__)` after line 12 (`client: DefectDojoClient | None = None`).
  - Current lifespan (lines 15-23):
    ```python
    @asynccontextmanager
    async def lifespan(app: FastMCP):
        global client
        load_dotenv()
        client = DefectDojoClient()
        try:
            yield {}
        finally:
            await client._client.aclose()
    ```
  - Target lifespan:
    ```python
    @asynccontextmanager
    async def lifespan(app: FastMCP):
        global client
        load_dotenv()
        try:
            client = DefectDojoClient()
            logger.info("DefectDojo client initialized: %s", client.base_url)
            yield {}
        except ValueError as e:
            logger.error("Failed to initialize DefectDojo client: %s", e)
            raise
        finally:
            if client is not None:
                await client.aclose()
                logger.info("DefectDojo client closed")
    ```
  - Key changes: (1) `client = DefectDojoClient()` moved inside try, (2) `except ValueError` added with log, (3) finally has `if client is not None` guard, (4) `client._client.aclose()` → `client.aclose()`, (5) startup/shutdown log statements added.
  - Do NOT modify anything below line 24 in server.py. Only touch imports (lines 1-10) and lifespan (lines 15-24).

  MODIFIED: `Dockerfile` — line 8
  - Current: `# Disable cache for cleaner images in CI/CD environments`
  - Target: `# Relocate uv cache to ephemeral /tmp to reduce final image size`
  - Do NOT change any other lines in Dockerfile.

- **Verification Steps**:
  1. Run `grep -n 'logger\.' src/mcp_defectdojo/client.py` and confirm 4 log statements exist (debug, debug, warning, error)
  2. Run `grep -n 'client._client' src/mcp_defectdojo/server.py` and confirm zero matches (private access removed)
  3. Run `grep -n 'client.aclose' src/mcp_defectdojo/server.py` and confirm one match in lifespan finally block
  4. Run `grep -n 'ValueError' src/mcp_defectdojo/server.py` and confirm one match in lifespan except clause
  5. Run `grep -n 'if client is not None' src/mcp_defectdojo/server.py` and confirm one match in lifespan finally
  6. Run `grep 'Disable cache' Dockerfile` and confirm zero matches
  7. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('OK')"` to verify syntax
  8. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/client.py').read()); print('OK')"` to verify syntax
- **Done Criteria**: Client logs all API calls; lifespan handles missing env vars with logged error and uses public aclose with None guard; Dockerfile comment is accurate.
- **Dependencies**: none

### Task T2: Tool Hardening — Null Guards, Validation & Safety

- **AC**: AC-3.2.1c, AC-3.2.1d, AC-3.2.1e, AC-3.2.1f
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read** (reference only): `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/models.py`
- **Action**:

  MODIFIED: `src/mcp_defectdojo/server.py` — module-level constant and all 14 tool function bodies

  **Change 1 — Extract VALID_SEVERITIES constant:**
  - Add after the `mcp = FastMCP(...)` line: `VALID_SEVERITIES = [s.value for s in SeverityEnum]`
  - In `create_finding()`: replace `valid_severities = [s.value for s in SeverityEnum]` with `VALID_SEVERITIES` (all 3 references on lines 163-165)
  - In `update_finding()`: replace `valid_severities = [s.value for s in SeverityEnum]` with `VALID_SEVERITIES` (all 3 references on lines 190-192)

  **Change 2 — Fix ValidationError handler:**
  - In `_format_response()` at line 33: change `e.errors()[0]['msg']` to `str(e)`
  - In `_format_response()` at line 45: change `e.errors()[0]['msg']` to `str(e)`

  **Change 3 — Add null guard to all 14 tools:**
  - Add as the FIRST line of each tool function body (after the docstring): `if client is None: return "ERROR: DefectDojo client not initialized — server may not have started correctly"`
  - Apply to these 14 functions: `health_check`, `list_products`, `get_product`, `create_product`, `list_engagements`, `get_engagement`, `create_engagement`, `list_tests`, `get_test`, `create_test`, `list_findings`, `get_finding`, `create_finding`, `update_finding`
  - For `health_check`, this replaces the misleading AttributeError behavior. Remove the `except Exception as e` catch-all and replace with specific exception handling. Updated health_check:
    ```python
    @mcp.tool()
    async def health_check() -> str:
        """Check connectivity to the DefectDojo instance."""
        if client is None:
            return "UNHEALTHY: DefectDojo client not initialized — server may not have started correctly"
        try:
            await client.get_products(limit=1)
            return "OK: DefectDojo is reachable"
        except Exception as e:
            return f"UNHEALTHY: {e}"
    ```

  **Change 4 — Add missing ID validations:**
  - In `list_engagements()` (after null guard, before limit check): `if product_id <= 0: return f"ERROR: product_id must be > 0, got {product_id}"`
  - In `list_tests()` (after null guard, before limit check): `if engagement_id <= 0: return f"ERROR: engagement_id must be > 0, got {engagement_id}"`
  - In `list_findings()` (after null guard, before limit check): `if test_id is not None and test_id <= 0: return f"ERROR: test_id must be > 0, got {test_id}"`
  - In `create_finding()` (after null guard, before severity check): `if test_id <= 0: return f"ERROR: test_id must be > 0, got {test_id}"`
  - In `create_test()` (after null guard, after engagement_id check): `if test_type_id <= 0: return f"ERROR: test_type_id must be > 0, got {test_type_id}"`

  Do NOT change function signatures. Do NOT change the lifespan function (already modified by T1). Do NOT change imports.

- **Verification Steps**:
  1. Run `grep -c 'client is None' src/mcp_defectdojo/server.py` and confirm count is 15 (14 tools + 1 in lifespan from T1)
  2. Run `grep "e.errors()" src/mcp_defectdojo/server.py` and confirm zero matches (fragile pattern removed)
  3. Run `grep 'str(e)' src/mcp_defectdojo/server.py` and confirm 2 matches in _format_response
  4. Run `grep 'VALID_SEVERITIES' src/mcp_defectdojo/server.py` and confirm 5 matches (1 definition + 2 in create_finding + 2 in update_finding)
  5. Run `grep -c 'product_id <= 0' src/mcp_defectdojo/server.py` and confirm at least 2 matches (create_engagement + list_engagements)
  6. Run `grep -c 'test_type_id <= 0' src/mcp_defectdojo/server.py` and confirm 1 match (create_test)
  7. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('OK')"` to verify syntax
- **Done Criteria**: All 14 tools return descriptive error when client is None; all ID parameters validated > 0; ValidationError handler is safe; severity values use shared constant.
- **Dependencies**: T1 (T1 modifies lifespan and adds logging import to server.py; T2 must apply changes to the post-T1 version of server.py)

### Task T3: Mutation Logging & Tool Docstrings

- **AC**: AC-3.2.1h, AC-3.2.1i
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read** (reference only): `src/mcp_defectdojo/models.py`
- **Action**:

  MODIFIED: `src/mcp_defectdojo/server.py` — mutation tool bodies and all 14 tool docstrings

  **Change 1 — Add mutation logging:**
  - `logger` is already available at module level (added by T1).
  - In `create_product()`: add `logger.info("Creating product: name=%s, prod_type_id=%d", name, prod_type_id)` after the null guard and validation checks, before the `await client.create_product(...)` call.
  - In `create_engagement()`: add `logger.info("Creating engagement: product_id=%d, name=%s", product_id, name)` before the API call.
  - In `create_test()`: add `logger.info("Creating test: engagement_id=%d, test_type_id=%d", engagement_id, test_type_id)` before the API call.
  - In `create_finding()`: add `logger.info("Creating finding: test_id=%d, title=%s, severity=%s", test_id, title, severity)` before the API call.
  - In `update_finding()`: add `logger.info("Updating finding: finding_id=%d, fields=%s", finding_id, list(kwargs.keys()))` before the API call.

  **Change 2 — Expand all 14 tool docstrings:**
  Replace each tool's docstring with a more descriptive version that documents parameter constraints and return format. Use single-line or short multi-line docstrings. Here are the exact replacements:

  - `health_check`: `"""Check connectivity to the DefectDojo instance. Returns 'OK: DefectDojo is reachable' or 'UNHEALTHY: <reason>'."""`
  - `list_products`: `"""List products in DefectDojo. Args: limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""`
  - `get_product`: `"""Get a single product by ID. Args: product_id (must be > 0). Returns JSON with id, name, description, prod_type fields."""`
  - `create_product`: `"""Create a new product. Args: name, description, prod_type_id (must be > 0). Returns JSON with created product."""`
  - `list_engagements`: `"""List engagements for a product. Args: product_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""`
  - `get_engagement`: `"""Get a single engagement by ID. Args: engagement_id (must be > 0). Returns JSON with engagement fields."""`
  - `create_engagement`: `"""Create a new engagement. Args: product_id (> 0), name, target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created engagement."""`
  - `list_tests`: `"""List tests for an engagement. Args: engagement_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""`
  - `get_test`: `"""Get a single test by ID. Args: test_id (must be > 0). Returns JSON with test fields."""`
  - `create_test`: `"""Create a new test. Args: engagement_id (> 0), test_type_id (> 0), target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created test."""`
  - `list_findings`: `"""List findings, optionally filtered by test. Args: test_id (optional, > 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""`
  - `get_finding`: `"""Get a single finding by ID. Args: finding_id (must be > 0). Returns JSON with finding fields."""`
  - `create_finding`: `"""Create a new finding. Args: test_id (> 0), title, severity (Critical/High/Medium/Low/Info), description, active (default true), verified (default false). Returns JSON with created finding."""`
  - `update_finding`: `"""Update an existing finding. Args: finding_id (> 0), plus optional: title, severity (Critical/High/Medium/Low/Info), description, active, verified, false_p, duplicate, out_of_scope, is_mitigated. At least one field required. Returns JSON with updated finding."""`

  Do NOT change function signatures. Do NOT change validation logic or null guards (already done by T2). Do NOT change the lifespan function.

- **Verification Steps**:
  1. Run `grep -c 'logger.info' src/mcp_defectdojo/server.py` and confirm at least 7 matches (2 lifespan from T1 + 5 mutation tools)
  2. Run `grep 'YYYY-MM-DD' src/mcp_defectdojo/server.py` and confirm 3 matches (create_engagement, create_test docstrings + list is 0 since list tools don't take dates — wait, actually create_engagement and create_test both take dates. Let me count: create_engagement + create_test = 2 docstrings. So 2 matches)
  3. Run `grep "'items'" src/mcp_defectdojo/server.py` and confirm matches in list_* docstrings (4 tools)
  4. Run `grep 'Critical/High/Medium/Low/Info' src/mcp_defectdojo/server.py` and confirm 2 matches (create_finding, update_finding docstrings)
  5. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('OK')"` to verify syntax
- **Done Criteria**: All 5 mutation tools log invocations with key parameters; all 14 tool docstrings document parameter constraints and return format.
- **Dependencies**: T2 (T3 modifies the same tool functions that T2 hardened; T3 adds logging inside function bodies and replaces docstrings)

## Execution Strategy

### Wave 1 — Foundation (sequential)
T1 modifies client.py, Dockerfile, and server.py (imports + lifespan only).
- Task T1: Foundation — Client Logging, Lifespan & Dockerfile

### Wave 2 — Tool Hardening (sequential, depends on Wave 1)
T2 modifies server.py tool functions. Must run after T1 since T1 adds the logging import and modifies the lifespan in the same file.
- Task T2: Tool Hardening — Null Guards, Validation & Safety (depends on T1)

### Wave 3 — Polish (sequential, depends on Wave 2)
T3 modifies server.py tool function docstrings and bodies. Must run after T2 since T2 restructures all tool function bodies.
- Task T3: Mutation Logging & Tool Docstrings (depends on T2)

## Boundaries — DO NOT MODIFY

These files and directories are OUT OF SCOPE for this phase:

- `src/mcp_defectdojo/models.py` — Models are stable from Phase 3.1; no schema changes needed
- `src/mcp_defectdojo/__init__.py` — Empty file, no changes needed
- `pyproject.toml` — No new dependencies for stdlib logging; test deps deferred to Phase 3.2.2
- `uv.lock` — No dependency changes
- `.gitignore` — Finalized in Phase 2
- `deploy/` — Ansible playbooks are out of scope
- Tool function signatures — Parameter names, types, and defaults must not change (breaks MCP consumers)
- `_format_response` signature — Internal but depended on by all tools

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 (T1) complete | human-verify | Review lifespan fix and client logging before proceeding to tool changes |
| 2 | Wave 2 (T2) complete | human-verify | Review null guards and validation additions before docstring work |
| 3 | Wave 3 (T3) complete | human-verify | Review mutation logging and docstrings before verification |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Null guard copy-paste inconsistency | Medium | Medium | T2 uses identical error string for all 14 tools; verification checks count of occurrences |
| Lifespan ValueError handler swallowing startup | Low | High | Handler re-raises after logging; FastMCP will still see the exception and fail to start |
| Sequential waves slow build | Medium | Low | All 3 tasks touch server.py so parallelism is impossible; sequential is the only safe approach |
| Docstring expansion making tool descriptions too verbose for LLM agents | Low | Medium | Keep docstrings to 1-2 lines; include only constraints and return format, not full prose |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic (T1 → T2 → T3)
- [x] Total scope fits context budget (~45% estimated)
- [x] No task touches more than 5 files
- [x] No banned phrases in task descriptions

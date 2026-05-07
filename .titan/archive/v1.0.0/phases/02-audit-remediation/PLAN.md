---
phase: 02
name: Audit Remediation
goal: Fix all critical audit findings and stabilize the client/server lifecycle
branch: titan/phase-01-deployment-configuration
status: built
created: 2026-05-06T22:00:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 02 — Audit Remediation — Execution Plan

## Goal
Fix all 4 critical audit findings (no MCP auth deferred to Phase 03) and stabilize the httpx client lifecycle, error handling, and health check. After this phase, the server is production-stable with honest health reporting and proper resource cleanup.

## Context
- Audit (2026-05-06) scored D+ overall with 4 critical, 17 important, 18 minor findings.
- FastMCP supports a `lifespan` parameter accepting an `@asynccontextmanager` function with signature `(app: FastMCP) -> AsyncContextManager`. Verified in installed `mcp` package v1.27+.
- Lifespan approach: set module-level `global client` inside lifespan (Option A) to avoid changing all tool function signatures.
- `load_dotenv()` must move from client.py module level into the lifespan function in server.py.
- DefectDojoClient constructor currently crashes at import time if env vars are missing.

## Acceptance Criteria (This Phase)

**FR-009: Security Configuration**
- AC-009a: `.gitignore` excludes `.env` and `.env.*` (except `.env.example`)
- AC-009b: Dockerfile runs process as non-root user `appuser`
- AC-009c: `__init__.py` contains no dead code

**FR-010: Client Lifecycle Management**
- AC-010a: `httpx.AsyncClient` created with `timeout=httpx.Timeout(30.0, connect=5.0)`
- AC-010b: Network errors (`ConnectError`, `TimeoutException`) caught and wrapped as descriptive `RuntimeError`
- AC-010c: Inner try/except in `_request` catches `json.JSONDecodeError` only (not bare `Exception`)
- AC-010d: Unused imports (`Dict`, `List`) removed; `get_findings` param `test_id` typed `Optional[int]`

**FR-011: Server Lifespan Integration**
- AC-011a: `DefectDojoClient` created within `@asynccontextmanager` lifespan function, not at module level
- AC-011b: `await client._client.aclose()` called in lifespan `finally` block
- AC-011c: `health_check` makes actual API call to DefectDojo and returns real connectivity status
- AC-011d: Missing env vars do not crash at import time (crash deferred to lifespan startup)

## Tasks

### Task T1: Config and Container Hardening

- **AC**: FR-009 (AC-009a, AC-009b, AC-009c)
- **Mode**: agent
- **Files to Modify**: `.gitignore`, `Dockerfile`, `src/mcp_defectdojo/__init__.py`
- **Files to Create**: None
- **Files to Read**: None
- **Action**:

  MODIFIED: `.gitignore`
    Current: No `.env` exclusion pattern. File has sections for byte-compiled, venvs, IDE, TITAN, misc.
    Target: Add a "# Secrets" section after the "# Virtual environments" section with these lines:
    ```
    # Secrets
    .env
    .env.*
    !.env.example
    ```

  MODIFIED: `Dockerfile`
    Current: 19 lines, no USER directive, runs as root. ENTRYPOINT is `["uv", "run", "mcp-defectdojo"]`.
    Target: After the `RUN uv sync --frozen --no-dev` line (line 16), add:
    ```dockerfile
    RUN adduser --disabled-password --gecos "" --no-create-home appuser
    USER appuser
    ```

  MODIFIED: `src/mcp_defectdojo/__init__.py`
    Current: 2 lines — `def main() -> None:` / `print("Hello from mcp-defectdojo!")`
    Target: Empty file (or single empty line). Remove the entire `main()` function. This is dead code — the real entry point is `mcp_defectdojo.server:main`.

- **Verification Steps**:
  1. Run `grep -n "\.env" .gitignore` and confirm `.env`, `.env.*`, and `!.env.example` patterns are present
  2. Run `grep -n "USER\|adduser" Dockerfile` and confirm non-root user is created and set
  3. Run `grep -c "def main" src/mcp_defectdojo/__init__.py` and confirm output is `0`
  4. Run `docker build -t mcp-defectdojo-test .` and confirm build succeeds
- **Done Criteria**: All three config/container security fixes applied and Dockerfile builds successfully.
- **Dependencies**: None

### Task T2: Client Robustness

- **AC**: FR-010 (AC-010a, AC-010b, AC-010c, AC-010d)
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/client.py`
- **Files to Create**: None
- **Files to Read**: None
- **Action**:

  MODIFIED: `src/mcp_defectdojo/client.py`

  1. **Line 3** — Change `from typing import Any, Dict, List` to `from typing import Any, Optional`. Remove unused `Dict` and `List`.

  2. **Remove line 4** — Remove `from dotenv import load_dotenv`. The `load_dotenv()` call will move to server.py lifespan (Task T3).

  3. **Remove line 6** — Remove `load_dotenv()` module-level call.

  4. **Lines 13-14** — Change the `raise ValueError(...)` to a warning. Replace with:
     ```python
     import logging
     logger = logging.getLogger(__name__)
     ```
     Add logger at module level (after imports). In `__init__`, replace:
     ```python
     if not self.base_url or not self.api_key:
         raise ValueError("DEFECTDOJO_URL and DEFECTDOJO_API_KEY environment variables must be set.")
     ```
     with:
     ```python
     if not self.base_url or not self.api_key:
         raise ValueError("DEFECTDOJO_URL and DEFECTDOJO_API_KEY must be set. Ensure load_dotenv() is called before creating the client.")
     ```
     (Keep the ValueError here — it's now acceptable because creation is deferred to lifespan, not import time. The error message is updated to be more helpful.)

  5. **Line 22** — Add explicit timeout to `httpx.AsyncClient`:
     ```python
     self._client = httpx.AsyncClient(
         base_url=f"{self.base_url}/api/v2",
         headers=self.headers,
         timeout=httpx.Timeout(30.0, connect=5.0),
     )
     ```

  6. **Lines 24-38** — Rewrite `_request()` error handling:
     ```python
     async def _request(self, method: str, path: str, **kwargs) -> Any:
         try:
             response = await self._client.request(method, path, **kwargs)
             response.raise_for_status()
             if response.status_code != 204:
                 return response.json()
             return {}
         except httpx.HTTPStatusError as e:
             try:
                 error_data = json.loads(e.response.text)
                 error_detail = error_data.get("detail", error_data)
                 raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {json.dumps(error_detail)}")
             except json.JSONDecodeError:
                 raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {e.response.text[:500]}")
         except (httpx.ConnectError, httpx.TimeoutException) as e:
             raise RuntimeError(f"Failed to connect to DefectDojo at {self.base_url}: {e}")
     ```
     Key changes: (a) narrow inner except to `json.JSONDecodeError`, (b) add catch for network errors, (c) move `import json` to top of file.

  7. **Line 33** — Move `import json` to top of file (line 2, after `import os`). Remove the inline import inside `_request`.

  8. **Line 88** — Change `test_id: int = None` to `test_id: Optional[int] = None`.

- **Verification Steps**:
  1. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/client.py').read()); print('Syntax OK')"` — confirms valid Python
  2. Run `grep -n "Dict\|List" src/mcp_defectdojo/client.py` — confirms no `Dict` or `List` imports remain
  3. Run `grep -n "load_dotenv" src/mcp_defectdojo/client.py` — confirms no dotenv import or call
  4. Run `grep -n "Timeout" src/mcp_defectdojo/client.py` — confirms explicit timeout is set
  5. Run `grep -n "ConnectError\|TimeoutException" src/mcp_defectdojo/client.py` — confirms network error handling exists
  6. Run `grep -n "except Exception" src/mcp_defectdojo/client.py` — confirms bare Exception is gone (output should be empty)
  7. Run `grep -n "Optional\[int\]" src/mcp_defectdojo/client.py` — confirms test_id has correct type
- **Done Criteria**: `client.py` has explicit timeouts, proper error handling for HTTP and network errors, no unused imports, and correct type hints.
- **Dependencies**: None

### Task T3: Server Lifespan Integration

- **AC**: FR-011 (AC-011a, AC-011b, AC-011c, AC-011d)
- **Mode**: in-session
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: None
- **Files to Read**: `src/mcp_defectdojo/client.py` (to understand the refactored client from T2)
- **Action**:

  MODIFIED: `src/mcp_defectdojo/server.py`

  1. **Add imports** — At top of file, add:
     ```python
     from contextlib import asynccontextmanager
     from dotenv import load_dotenv
     ```

  2. **Remove line 8** — Remove `client = DefectDojoClient()`. Replace with:
     ```python
     client: DefectDojoClient | None = None
     ```

  3. **Add lifespan function** — After the `client` declaration, before tool definitions:
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

  4. **Modify FastMCP constructor** — Change line 7 from:
     ```python
     mcp = FastMCP("mcp-defectdojo")
     ```
     to:
     ```python
     mcp = FastMCP("mcp-defectdojo", lifespan=lifespan)
     ```

  5. **Rewrite `health_check`** — Change from hardcoded response to actual check:
     ```python
     @mcp.tool()
     async def health_check() -> str:
         """Check connectivity to the DefectDojo instance."""
         try:
             await client.get_products(limit=1)
             return "OK: DefectDojo is reachable"
         except Exception as e:
             return f"UNHEALTHY: {e}"
     ```

- **Verification Steps**:
  1. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('Syntax OK')"` — confirms valid Python
  2. Run `grep -n "lifespan" src/mcp_defectdojo/server.py` — confirms lifespan function defined and passed to FastMCP
  3. Run `grep -n "global client" src/mcp_defectdojo/server.py` — confirms client is set inside lifespan
  4. Run `grep -n "aclose" src/mcp_defectdojo/server.py` — confirms cleanup in finally block
  5. Run `grep -n "get_products" src/mcp_defectdojo/server.py` — confirms health_check makes a real API call
  6. Run `grep -c "DefectDojoClient()" src/mcp_defectdojo/server.py` — output is `1` (only inside lifespan, not at module level)
  7. Run `grep -n "load_dotenv" src/mcp_defectdojo/server.py` — confirms load_dotenv is called in lifespan
- **Done Criteria**: Server creates DefectDojoClient inside lifespan context, closes it on shutdown, and health_check returns real DefectDojo connectivity status.
- **Dependencies**: T2 (needs refactored client.py with dotenv removed and proper error handling)

## Execution Strategy

### Wave 1 — Foundation (parallel)
Independent tasks with no dependencies. Run as parallel titan-executor agents.
- Task T1: Config and Container Hardening (agent)
- Task T2: Client Robustness (agent)

### Wave 2 — Integration (in-session)
Depends on Wave 1 output. Requires orchestrator context for cross-file integration.
- Task T3: Server Lifespan Integration (in-session, depends on T2)

## Boundaries — DO NOT MODIFY

- `src/mcp_defectdojo/models.py` — Pydantic models are clean, no changes needed. Phase 03 scope.
- `pyproject.toml` — Entry point and dependencies must not change.
- `uv.lock` — Lock file must not be regenerated in this phase.
- Tool function signatures (parameter names, types, return types) — These are the MCP API contract for existing clients.
- Tool function names — MCP clients reference tools by name.

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 complete | human-verify | Review T1 (config/container) and T2 (client) changes before server integration |
| 2 | Wave 2 complete | human-verify | Review T3 (lifespan wiring) and confirm all tools still reference client correctly |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Lifespan function signature mismatch — FastMCP may expect different args | Low | High | Verified from installed package source: accepts `Callable[[FastMCP], AsyncContextManager]` |
| Dockerfile adduser fails on slim image | Low | Medium | `adduser` is available in Debian bookworm-slim. Verified via base image docs. |
| Tool functions reference `client` before lifespan sets it (None access) | Medium | High | Declare `client: DefectDojoClient | None = None` at module level. Tools only execute after lifespan has run. FastMCP guarantees lifespan runs before accepting requests. |
| Removing load_dotenv from client.py breaks other imports | Low | Medium | Only server.py imports client.py. load_dotenv moves to server.py lifespan, which runs before client creation. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps (T1: 4, T2: 7, T3: 7)
- [x] Boundaries are explicit (5 protected items)
- [x] Wave dependencies are acyclic (T1, T2 → T3)
- [x] Total scope fits context budget (~45% estimated)
- [x] Total tasks = 3 (within max_tasks_per_plan limit)
- [x] In-session task (T3) is in the latest wave
- [x] No wave has more than 4 parallel agent tasks (Wave 1: 2, Wave 2: 1)
- [x] All task descriptions use delta specs with exact file paths and line numbers
- [x] No banned phrases in task descriptions

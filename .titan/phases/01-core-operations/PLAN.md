---
phase: 01
name: core-operations
goal: Agents can navigate the structural hierarchy of DefectDojo (Products, Engagements, Tests).
branch: titan/phase-01-core-operations
status: draft
created: 2026-05-04T04:05:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 01 — Core Operations — Execution Plan

## Goal
Establish the MCP server foundation and enable tools for creating and reading Products, Engagements, and Tests in DefectDojo.

## Context
- **Greenfield Setup:** The project is currently empty. We must initialize the Python structure (`pyproject.toml`, `src/mcp_defectdojo/`) using `uv`.
- **Token Efficiency:** Raw DefectDojo JSON is verbose. Pydantic models must be used in `models.py` to strip responses down to essential fields before returning to the LLM.
- **Error Handling:** HTTP errors from DefectDojo (4xx, 5xx) must be caught by the client and returned as formatted string responses to the MCP agent, rather than crashing the server.

## Acceptance Criteria (This Phase)
- **FR-001:** Given valid authentication, When the agent requests to list products, Then a summary list of products is returned.
- **FR-001:** Given a product name and description, When the agent requests to create a product, Then the product is created in DefectDojo and its ID is returned.
- **FR-002:** Given a product ID, When the agent requests to create an engagement, Then the engagement is created and its ID is returned.
- **FR-003:** Given an engagement ID and test type, When the agent requests to create a test, Then the test is created and its ID is returned.

## Tasks

### Task T1: Server Foundation and Product Tools

- **AC**: FR-001
- **Mode**: agent
- **Files to Modify**: none (greenfield)
- **Files to Create**: `pyproject.toml`, `src/mcp_defectdojo/__init__.py`, `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/models.py`, `.env.example`
- **Files to Read**: none
- **Action**: 
  ADDED: `pyproject.toml` — Initialize a `uv` project named `mcp-defectdojo` with dependencies: `mcp`, `httpx`, `pydantic`, `python-dotenv`. Add an `mcp-defectdojo` script entrypoint to run `server.py`.
  ADDED: `src/mcp_defectdojo/models.py` — Create a Pydantic model `ProductSummary` (fields: `id`, `name`, `description`, `prod_type`).
  ADDED: `src/mcp_defectdojo/client.py` — Create `DefectDojoClient` class wrapping `httpx.AsyncClient`. It must load `DEFECTDOJO_URL` and `DEFECTDOJO_API_KEY` from `os.environ`. Add async methods `get_products()`, `get_product(id)`, and `create_product(name, description, prod_type_id)`. Catch `httpx.HTTPStatusError` and return the error text cleanly instead of raising.
  ADDED: `src/mcp_defectdojo/server.py` — Instantiate `FastMCP` from `mcp.server.fastmcp`. Register three tools decorated with `@mcp.tool()`: `list_products()`, `get_product(product_id: int)`, and `create_product(...)`. These tools call `DefectDojoClient` methods and return JSON strings formatted via `ProductSummary`.
  ADDED: `.env.example` — Template with `DEFECTDOJO_URL` and `DEFECTDOJO_API_KEY`.
- **Verification Steps**:
  1. Run `uv pip check` and confirm dependencies resolve.
  2. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py src/mcp_defectdojo/models.py` and confirm no syntax errors.
- **Done Criteria**: A functional Python MCP server exists with tools to list, read, and create DefectDojo Products.
- **Dependencies**: none

### Task T2: Engagement Tools

- **AC**: FR-002
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/models.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/models.py` — Add `EngagementSummary` (fields: `id`, `name`, `product_id`, `target_start`, `target_end`).
  MODIFIED: `src/mcp_defectdojo/client.py` — Add `get_engagements(product_id: int)`, `get_engagement(id: int)`, and `create_engagement(product_id: int, name: str, target_start: str, target_end: str)`. Ensure errors are caught and returned as strings.
  MODIFIED: `src/mcp_defectdojo/server.py` — Register `@mcp.tool()` for `list_engagements`, `get_engagement`, and `create_engagement`.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py src/mcp_defectdojo/models.py` and confirm no syntax errors.
  2. Run `grep "def create_engagement" src/mcp_defectdojo/server.py` to confirm the tool is exposed.
- **Done Criteria**: The server exposes tools for listing, getting, and creating Engagements.
- **Dependencies**: T1

### Task T3: Test Tools

- **AC**: FR-003
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`, `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/models.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/models.py` — Add `TestSummary` (fields: `id`, `engagement_id`, `test_type`, `title`).
  MODIFIED: `src/mcp_defectdojo/client.py` — Add `get_tests(engagement_id: int)`, `get_test(id: int)`, and `create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str)`. Ensure errors are caught and returned as strings.
  MODIFIED: `src/mcp_defectdojo/server.py` — Register `@mcp.tool()` for `list_tests`, `get_test`, and `create_test`.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py src/mcp_defectdojo/models.py` and confirm no syntax errors.
  2. Run `grep "def create_test" src/mcp_defectdojo/server.py` to confirm the tool is exposed.
- **Done Criteria**: The server exposes tools for listing, getting, and creating Tests.
- **Dependencies**: T1

## Execution Strategy

### Wave 1 — Foundation (parallel)
- [x] Task T1: Server Foundation and Product Tools

### Wave 2 — Features (parallel)
Tasks that depend on the base architecture established in Wave 1.
- [x] Task T2: Engagement Tools (depends on T1)
- [x] Task T3: Test Tools (depends on T1)

## Boundaries — DO NOT MODIFY
- `.titan/` directory (Except for state updates, do not alter architectural specs).
- `CLAUDE.md` and `AGENTS.md` (Project rules).

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 complete | human-verify | Ensure the base python project structure and FastMCP app look correct before adding more models. |
| 2 | Before ship | human-action | Configure `.env` with actual `DEFECTDOJO_URL` and `DEFECTDOJO_API_KEY` to run end-to-end tests against a live instance in `/titan:08-verify`. |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| DefectDojo API version paths change | Medium | High | Use the standard `/api/v2/` prefix. Catch all `httpx.HTTPStatusError`s and return clear strings indicating if a 404/400 occurred. |
| Context window overflow | High | High | T1, T2, and T3 strictly mandate Pydantic models to filter out verbose DefectDojo JSON before returning it to the MCP agent. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget

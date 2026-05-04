---
phase: 03
name: optimization
goal: Make the tool highly resilient and token-efficient for agents.
branch: titan/phase-03-optimization
status: draft
created: 2026-05-04T04:15:00Z
estimated_tasks: 2
estimated_waves: 2
---

# Phase 03 — Optimization — Execution Plan

## Goal
Implement robust error parsing and enforce pagination/limit constraints on list tools to optimize context window token usage.

## Context
- **Current State:** The application currently captures basic HTTP status errors but returns raw text which might be unparsed JSON. List tools return all items provided by the API's default page size (up to 100), which can be verbose.
- **Pattern Match:** Add `limit` and `offset` query parameters to list tools, defaulting `limit` to 20 to protect context.

## Acceptance Criteria (This Phase)
- **FR-010:** Provide helpful error messages back to the agent if an API call fails, allowing the agent to self-correct (e.g., "Finding ID 123 not found").
- **NFR-002:** Responses from the DefectDojo API must be stripped of unnecessary metadata before being returned to the agent to conserve context window tokens.

## Tasks

### Task T1: Error Translation Optimization [x]

- **AC**: FR-010
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/client.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/client.py` — `_request()`
    Current: returns `f"HTTP error occurred: {e.response.status_code} - {e.response.text}"`
    Target: attempt to `json.loads(e.response.text)`. If successful, extract error details (often under `"detail"` or specific field keys) and format a clean error string like `DefectDojo API Error 400: {"title": ["This field is required."]}`. Fallback to raw text if JSON parsing fails.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/client.py` and confirm no syntax errors.
- **Done Criteria**: The client translates API JSON error payloads into clean, readable strings.
- **Dependencies**: none

### Task T2: Pagination and Context Limits [x]

- **AC**: NFR-002
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/client.py` — Update list methods (`get_products`, `get_engagements`, `get_tests`, `get_findings`) to accept `limit: int = 20` and `offset: int = 0` parameters, passing them to the `params` dict.
  MODIFIED: `src/mcp_defectdojo/server.py` — Update `@mcp.tool()` definitions for `list_products`, `list_engagements`, `list_tests`, and `list_findings` to accept `limit: int = 20` and `offset: int = 0` in their signatures and pass them down to the client methods.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py` and confirm no syntax errors.
  2. Run `grep "limit: int = 20" src/mcp_defectdojo/server.py` to verify the default argument is present.
- **Done Criteria**: All list tools enforce a context-friendly default limit of 20 while allowing agents to paginate via limit/offset.
- **Dependencies**: none

## Execution Strategy

### Wave 1 — Resiliency (parallel)
- Task T1: Error Translation Optimization
- Task T2: Pagination and Context Limits

## Boundaries — DO NOT MODIFY
- Existing Pydantic models in `models.py`.

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 complete | human-verify | Structural review. |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| JSON parsing failure on HTML error pages | High | Low | Wrap error text JSON parsing in a `try/except json.JSONDecodeError` to fallback to raw text gracefully. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget

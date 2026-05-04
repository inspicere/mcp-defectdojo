---
phase: 02
name: finding-management
goal: Agents can fully interact with findings (read, create, update).
branch: titan/phase-02-finding-management
status: draft
created: 2026-05-04T04:10:00Z
estimated_tasks: 2
estimated_waves: 2
---

# Phase 02 — Finding Management — Execution Plan

## Goal
Agents can review scanner outputs, update reproducibility/status, and create new manual findings.

## Context
- **Pattern Match:** Client methods and server tools follow the `[action]_[entity]` pattern. Pydantic models follow `[Entity]Summary`.
- **Data Mapping:** Pydantic models in `models.py` use `model_config = {"populate_by_name": True}` and `Field(alias="...")` to map pythonic names (like `test_id`) to DefectDojo's payload format (like `test`).
- **Signature Clarity:** New `@mcp.tool()` functions in `server.py` must use explicit, optional arguments (`active: Optional[bool] = None`) rather than `**kwargs` so that the LLM understands the MCP tool schema.

## Acceptance Criteria (This Phase)
- **FR-004:** Given a finding ID and updated fields, When the agent requests to update the finding, Then the finding is updated in DefectDojo and the new state is returned.
- **FR-005:** Given a test ID and finding details (title, severity, description), When the agent requests to create a finding, Then the finding is created and its ID is returned.

## Tasks

### Task T1: Finding Retrieval and Creation

- **AC**: FR-005 [x]
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/models.py`, `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/models.py` — Add `FindingSummary` Pydantic model with fields: `id`, `test_id` (alias `test`), `title`, `severity`, `description`, `active`, `verified`, `mitigated`, `is_mitigated`, `out_of_scope`, `false_p`, `duplicate`.
  MODIFIED: `src/mcp_defectdojo/client.py` — Add `get_findings(test_id: int = None)`, `get_finding(id: int)`, and `create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False)`. Use standard error catching and return logic.
  MODIFIED: `src/mcp_defectdojo/server.py` — Register `@mcp.tool()` for `list_findings`, `get_finding`, and `create_finding`. Ensure they use explicit type hints and format the return data via `FindingSummary`.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py src/mcp_defectdojo/models.py` and confirm no syntax errors.
  2. Run `grep "def create_finding" src/mcp_defectdojo/server.py` to confirm tool is exposed.
- **Done Criteria**: [x] The server exposes tools for listing, getting, and creating Findings.
- **Dependencies**: none

### Task T2: Finding Update

- **AC**: FR-004 [x]
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/client.py`, `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: `src/mcp_defectdojo/models.py`
- **Action**: 
  MODIFIED: `src/mcp_defectdojo/client.py` — Add `update_finding(id: int, **kwargs)`. It should use the HTTP `PATCH` method on `/api/v2/findings/{id}/` to send only the updated fields.
  MODIFIED: `src/mcp_defectdojo/server.py` — Register `@mcp.tool()` for `update_finding`. Crucially, define explicit optional arguments in the signature (e.g., `title: Optional[str] = None`, `severity: Optional[str] = None`, `active: Optional[bool] = None`, `verified: Optional[bool] = None`, `false_p: Optional[bool] = None`, `duplicate: Optional[bool] = None`, `out_of_scope: Optional[bool] = None`, `is_mitigated: Optional[bool] = None`). Filter out `None` values and pass the remaining dict to `client.update_finding()`. Format return with `FindingSummary`.
- **Verification Steps**:
  1. Run `uv run python -m py_compile src/mcp_defectdojo/server.py src/mcp_defectdojo/client.py` and confirm no syntax errors.
  2. Run `grep "def update_finding" src/mcp_defectdojo/server.py` to confirm tool is exposed.
- **Done Criteria**: [x] The server exposes a tool for updating Findings that correctly lists optional fields in its schema.
- **Dependencies**: T1

## Execution Strategy

### Wave 1 — Base Finding Operations (parallel)
- [x] Task T1: Finding Retrieval and Creation

### Wave 2 — Finding Triage (parallel)
- [x] Task T2: Finding Update (depends on T1 so it can use FindingSummary)

## Boundaries — DO NOT MODIFY
- Existing Product, Engagement, and Test tools in `server.py` and `client.py`.
- The `DefectDojoClient` initialization and `_request` core logic.

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 complete | human-verify | [x] Review T1 code before moving to T2. |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Tool schema opacity | High | Medium | Explicitly define optional arguments in `update_finding` tool signature instead of using `**kwargs`. |
| DefectDojo PATCH semantics | Medium | Medium | Ensure `update_finding` sends a `PATCH` request (not `PUT`) so partial updates work correctly without overwriting omitted fields. |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget

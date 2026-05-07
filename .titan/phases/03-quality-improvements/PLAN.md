---
phase: "03.1"
name: Input Validation & Pagination
goal: Add input validation and pagination metadata so LLM agent consumers get reliable errors and can paginate results
branch: titan/phase-03-quality-improvements
status: built
created: 2026-05-07T01:30:00Z
estimated_tasks: 3
estimated_waves: 3
split_note: "Phase 03 split into 3.1 (Validation & Pagination) and 3.2 (Logging & Robustness). This plan covers 3.1 only."
---

# Phase 03.1 — Input Validation & Pagination — Execution Plan

## Goal
Add input validation (severity enum, limit caps, ID bounds) and pagination metadata (total count, offset, limit, has_next) to all MCP tools, resolving FR-012 and FR-013 plus related Phase 02 deferred findings.

## Context
- All 14 MCP tools currently pass inputs directly to the DefectDojo API with no validation.
- `_format_response()` discards pagination metadata (count, next, previous) from API responses.
- Phase 02 evaluation identified 5 related findings: SB-01 (dead code in _format_response), SB-05 (empty kwargs no-op), SB-06 (uncaught ValidationError), SB-07 (missing type annotations), SB-03 (no public aclose).
- DefectDojo API returns paginated responses with structure: `{"count": N, "next": url|null, "previous": url|null, "results": [...]}`.
- Valid severity values in DefectDojo: Critical, High, Medium, Low, Info.

## Acceptance Criteria (This Phase)

- **FR-012**: Given invalid input (bad severity, limit > 100, offset < 0, ID ≤ 0), When a tool is called, Then a descriptive error is returned before any API call is made.
- **FR-013**: Given a paginated list response, When a `list_*` tool returns results, Then the response includes a `pagination` object with `count`, `offset`, `limit`, and `has_next` fields.
- **SB-05**: Given `update_finding` called with no fields to change, When `kwargs` is empty, Then an explicit error message is returned (not a silent no-op).
- **SB-01/SB-06/SB-07**: Given `_format_response`, When inspected, Then dead code is removed, ValidationError is caught, and type annotations are present.

## Tasks

### Task T1: Foundation — Models & Client Hardening

- **AC**: FR-012 (partial — SeverityEnum), FR-013 (partial — PaginationMetadata), SB-03
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/models.py`, `src/mcp_defectdojo/client.py`
- **Files to Create**: None
- **Files to Read**: `src/mcp_defectdojo/server.py` (to understand usage patterns)
- **Action**:
  ADDED in `src/mcp_defectdojo/models.py`:
  1. Add `from enum import Enum` import at top of file.
  2. Add class `SeverityEnum(str, Enum)` with members: `CRITICAL = "Critical"`, `HIGH = "High"`, `MEDIUM = "Medium"`, `LOW = "Low"`, `INFO = "Info"`. Place before the existing Pydantic models.
  3. Add class `PaginationMetadata(BaseModel)` with fields: `count: int`, `offset: int`, `limit: int`, `has_next: bool`. Place after the existing Pydantic models.

  ADDED in `src/mcp_defectdojo/client.py`:
  4. Add method `async def aclose(self) -> None:` to `DefectDojoClient` class, with body: `await self._client.aclose()`. Place after `__init__` and before `_request`.
- **Verification Steps**:
  1. Run `cd /opt/mcp-defectdojo && python -c "from mcp_defectdojo.models import SeverityEnum, PaginationMetadata; print(SeverityEnum.CRITICAL.value); print(PaginationMetadata(count=5, offset=0, limit=20, has_next=False).model_dump())"` — prints "Critical" and the metadata dict.
  2. Run `grep -n "async def aclose" src/mcp_defectdojo/client.py` — finds the method.
  3. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/models.py').read()); ast.parse(open('src/mcp_defectdojo/client.py').read()); print('OK')"` — prints "OK" (no syntax errors).
- **Done Criteria**: `SeverityEnum` and `PaginationMetadata` are importable from `mcp_defectdojo.models`; `DefectDojoClient` has a public `aclose()` method.
- **Dependencies**: none

### Task T2: Input Validation (FR-012 + SB-05)

- **AC**: FR-012, SB-05
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: None
- **Files to Read**: `src/mcp_defectdojo/models.py` (for SeverityEnum import)
- **Action**:
  MODIFIED in `src/mcp_defectdojo/server.py`:
  1. Add import: `from .models import SeverityEnum` (extend existing models import line).
  2. In `list_products` (line 49): Before the client call, add validation:
     ```
     if not 1 <= limit <= 100:
         return f"ERROR: limit must be between 1 and 100, got {limit}"
     if offset < 0:
         return f"ERROR: offset must be >= 0, got {offset}"
     ```
  3. Apply identical limit/offset validation to `list_engagements` (line 69), `list_tests` (line 89), `list_findings` (line 109).
  4. In `get_product` (line 55): Add `if product_id <= 0: return f"ERROR: product_id must be > 0, got {product_id}"`. Apply same pattern to `get_engagement` (engagement_id), `get_test` (test_id), `get_finding` (finding_id).
  5. In `create_finding` (line 121): Add severity validation before client call:
     ```
     valid_severities = [s.value for s in SeverityEnum]
     if severity not in valid_severities:
         return f"ERROR: severity must be one of {valid_severities}, got '{severity}'"
     ```
  6. In `create_product` (line 61): Add `if prod_type_id <= 0: return f"ERROR: prod_type_id must be > 0, got {prod_type_id}"`.
  7. In `create_engagement` (line 81): Add `if product_id <= 0: return f"ERROR: product_id must be > 0, got {product_id}"`.
  8. In `create_test` (line 101): Add `if engagement_id <= 0: return f"ERROR: engagement_id must be > 0, got {engagement_id}"`.
  9. In `update_finding` (line 127): Add after the kwargs dict construction (line 141):
     ```
     if not kwargs:
         return "ERROR: No fields to update. Specify at least one field to change."
     if "severity" in kwargs:
         valid_severities = [s.value for s in SeverityEnum]
         if kwargs["severity"] not in valid_severities:
             return f"ERROR: severity must be one of {valid_severities}, got '{kwargs['severity']}'"
     ```
  10. In `update_finding`: Add `if finding_id <= 0: return f"ERROR: finding_id must be > 0, got {finding_id}"` at the start.
- **Verification Steps**:
  1. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('OK')"` — no syntax errors.
  2. Run `grep -c "ERROR:" src/mcp_defectdojo/server.py` — returns at least 10 (validation guards added).
  3. Run `grep "SeverityEnum" src/mcp_defectdojo/server.py` — confirms import and usage.
- **Done Criteria**: All tools reject invalid inputs with descriptive error messages before making any API call.
- **Dependencies**: T1 (requires SeverityEnum from models.py)

### Task T3: Pagination Metadata & Response Robustness (FR-013 + SB-01, SB-06, SB-07)

- **AC**: FR-013, SB-01, SB-06, SB-07
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: None
- **Files to Read**: `src/mcp_defectdojo/models.py` (for PaginationMetadata)
- **Action**:
  MODIFIED in `src/mcp_defectdojo/server.py`:
  1. Extend models import to include `PaginationMetadata`: `from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary, SeverityEnum, PaginationMetadata`.
  2. Add import: `from pydantic import ValidationError` and `from typing import Any` (extend existing typing import).
  3. Replace the entire `_format_response` function (lines 27-35) with:
     ```python
     def _format_response(result: dict[str, Any], model: type, offset: int = 0, limit: int = 20) -> str:
         if "results" in result:
             try:
                 items = [model(**item).model_dump() for item in result["results"]]
             except ValidationError as e:
                 return f"ERROR: Invalid API response data: {e.errors()[0]['msg']}"
             pagination = PaginationMetadata(
                 count=result.get("count", len(items)),
                 offset=offset,
                 limit=limit,
                 has_next=(offset + limit) < result.get("count", 0),
             ).model_dump()
             return json.dumps({"items": items, "pagination": pagination}, indent=2)
         else:
             try:
                 return json.dumps(model(**result).model_dump(), indent=2)
             except ValidationError as e:
                 return f"ERROR: Invalid API response data: {e.errors()[0]['msg']}"
     ```
  4. Update all `list_*` tool return statements to pass offset and limit to `_format_response`:
     - `list_products`: `return _format_response(res, ProductSummary, offset=offset, limit=limit)`
     - `list_engagements`: `return _format_response(res, EngagementSummary, offset=offset, limit=limit)`
     - `list_tests`: `return _format_response(res, TestSummary, offset=offset, limit=limit)`
     - `list_findings`: `return _format_response(res, FindingSummary, offset=offset, limit=limit)`
  5. Single-item tool calls (`get_product`, `get_engagement`, `get_test`, `get_finding`, `create_*`, `update_finding`) remain as `_format_response(res, Model)` — no offset/limit needed for single items.
- **Verification Steps**:
  1. Run `python -c "import ast; ast.parse(open('src/mcp_defectdojo/server.py').read()); print('OK')"` — no syntax errors.
  2. Run `grep -c "isinstance(result, str)" src/mcp_defectdojo/server.py` — returns 0 (dead code removed, SB-01).
  3. Run `grep "ValidationError" src/mcp_defectdojo/server.py` — confirms import and except clause (SB-06).
  4. Run `grep "PaginationMetadata" src/mcp_defectdojo/server.py` — confirms usage (FR-013).
  5. Run `grep "_format_response(res" src/mcp_defectdojo/server.py | grep "offset="` — confirms list tools pass pagination params.
- **Done Criteria**: All `list_*` responses include a `pagination` object with count/offset/limit/has_next; `_format_response` has type annotations, catches ValidationError, and contains no dead code.
- **Dependencies**: T1 (requires PaginationMetadata from models.py); T2 (must run after T2 to avoid merge conflicts in server.py)

## Execution Strategy

### Wave 1 — Foundation
- T1: Models & Client Hardening (models.py + client.py)

### Wave 2 — Validation
- T2: Input Validation (server.py — adds guards at top of tool functions)

### Wave 3 — Response Formatting
- T3: Pagination & Response Robustness (server.py — rewrites _format_response and updates call sites)

Note: Waves are sequential because T2 and T3 both modify server.py. T3 must run after T2 to apply cleanly.

## Boundaries — DO NOT MODIFY

- `Dockerfile` — Deployment configuration finalized in Phase 01/02. SB-10 (comment fix) deferred to Phase 3.2.
- `deploy/` — Ansible playbook, out of scope for quality layer.
- `.gitignore` — Finalized in Phase 02.
- MCP tool function signatures — Adding/removing/renaming parameters would break agent consumers. Validation operates WITHIN existing signatures.
- `pyproject.toml` — No new dependencies needed (pydantic, enum are already available).

## Checkpoints

| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 complete | human-verify | Confirm SeverityEnum and PaginationMetadata models look correct |
| 2 | All waves | human-verify | Run `python -c "from mcp_defectdojo.server import mcp"` to confirm server still loads |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Pagination metadata changes JSON response structure, breaking existing agent consumers | Medium | Medium | Response is now `{"items": [...], "pagination": {...}}` instead of bare array. Document change. Agents using this MCP server will need to parse the new structure. |
| DefectDojo returns severity values not in our enum (e.g., "Informational" instead of "Info") | Medium | Low | Use "Info" as the enum value matching DefectDojo docs. If edge cases found, add values to enum. Validation only gates INPUT, not API responses. |
| _format_response signature change breaks existing call sites | Low | High | All call sites updated in T3. Verify by parsing server.py with `ast`. |

## Deferred to Phase 3.2

The following items from Phase 02 findings are explicitly NOT in this plan:
- FR-014: Structured Logging (separate FR, own phase)
- SA-001, SA-002, SB-02: Lifespan robustness (requires logging for observability)
- SB-04: Client logging (part of FR-014)
- SB-08: Tool docstring improvements (minor)
- SB-09: Test infrastructure (separate effort)
- SB-10: Dockerfile comment fix (trivial, bundle with 3.2)

## Validation
- [x] Every AC has at least one task (FR-012→T2, FR-013→T3, SB-05→T2, SB-01/06/07→T3)
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic (T1→T2→T3)
- [x] Total scope fits context budget (~40% estimated)
- [x] Total tasks = 3
- [x] No vague descriptions — exact file paths, function names, and code shown

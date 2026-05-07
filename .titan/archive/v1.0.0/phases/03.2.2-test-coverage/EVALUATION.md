---
phase: "03.2.2"
name: Test Coverage
verdict: PASS-WITH-NOTES
evaluated: 2026-05-07T07:00:00Z
review_model: two-stage
stage_a_verdict: PASS-WITH-NOTES
stage_b_verdict: PASS-WITH-NOTES
findings_critical: 0
findings_important: 3
findings_minor: 9
---

# Phase 03.2.2 — Test Coverage — Two-Stage Adversarial Evaluation

## Combined Verdict: PASS-WITH-NOTES

## Stage A — Spec Compliance Review
**Verdict:** PASS-WITH-NOTES

### Findings

**SA-01** (MINOR) — Specification Compliance
- Location: tests/conftest.py
- AC Reference: AC-3.2.2b
- Description: AC mentions "mock httpx transport" fixture but transport mocking uses per-test `@respx.mock` decorators instead. PLAN.md line 146 explicitly documents this design choice.
- Evidence: conftest.py has no transport fixture; respx is applied per-test in test_client.py
- Recommendation: No code change required; functional outcome achieved.

**SA-02** (MINOR) — Specification Compliance
- Location: tests/test_models.py
- AC Reference: AC-3.2.2c
- Description: "Reject invalid data" tests exist only for ProductSummary and FindingSummary. EngagementSummary, TestSummary, and PaginationMetadata lack explicit rejection tests.
- Evidence: Only `test_product_summary_missing_field` and `test_finding_summary_missing_required` test invalid data
- Recommendation: Low risk — models.py is 100% covered via other paths. Note for future hardening.

**SA-03** (MINOR) — Specification Compliance
- Location: tests/test_server.py (validation + happy path sections)
- AC Reference: AC-3.2.2e
- Description: 5 tool functions lack explicit server-level happy path tests (get_engagement, list_tests, get_test, create_test, get_finding) + create_finding. Plan only specified 9 happy path tests.
- Evidence: Coverage shows 36 missed lines in server.py, mostly from untested happy paths
- Recommendation: Acknowledged plan limitation. Server.py still meets 80% threshold.

**SA-04** (MINOR) — Specification Compliance
- Location: tests/test_server.py:120 (null guard parametrize data)
- AC Reference: AC-3.2.2e
- Description: create_finding null guard test omits `active` and `verified` kwargs that PLAN.md specified. No functional impact since null guard fires before those fields are used.
- Evidence: PLAN.md line 222 includes active/verified; test omits them; test passes regardless.
- Recommendation: Cosmetic; no change required.

### AC Verification

| AC ID | Criterion | Verified | Evidence |
|-------|-----------|----------|----------|
| AC-3.2.2a | pytest discovers and runs tests | ✓ | 77 passed in tests/ directory |
| AC-3.2.2b | conftest provides fixtures | ✓ | All 7 fixtures present and functional |
| AC-3.2.2c | Models tested valid/invalid/alias | ✓ | 11 tests, 100% model coverage |
| AC-3.2.2d | Client init + methods + errors | ✓ | 26 tests, 100% client coverage |
| AC-3.2.2e | Server tools tested comprehensively | ✓ | 40 tests, 80% server coverage |
| AC-3.2.2f | Coverage ≥ 80% | ✓ | 88% total |

## Stage B — Code Quality Review
**Verdict:** PASS-WITH-NOTES

### Findings

**SB-01** (IMPORTANT) — Test Coverage
- Location: tests/test_server.py:49-56 (test_lifespan_success)
- Description: Docstring claims test verifies `aclose` was called on exit, but no assertion exists for this. The lifespan finally block (server.py:30-32) calling `await client.aclose()` has zero test coverage.
- Evidence: Comment says "we just verify aclose was called" then never makes the assertion
- Recommendation: Patch DefectDojoClient with AsyncMock and assert aclose was awaited after context exit.

**SB-02** (IMPORTANT) — Test Coverage
- Location: tests/test_server.py — missing happy path tests
- Description: 6 tool functions lack server-level happy path tests: get_engagement, list_tests, get_test, create_test, get_finding, create_finding. Their `_format_response(...)` return paths (lines 128, 155, 165, 178, 204, 217) are unexecuted.
- Evidence: Coverage missing lines confirm these paths are dark
- Recommendation: Add one happy-path test per function following existing patterns.

**SB-03** (IMPORTANT) — Test Coverage
- Location: tests/test_server.py — validation branches
- Description: Multiple validation branches are unexercised: list_engagements limit/offset (lines 114, 116), list_tests limit/offset (lines 150-153), list_findings test_id/limit/offset (lines 188-192), get_engagement/get_test/get_finding ID guards, update_finding finding_id and severity guards.
- Evidence: ~15 missing lines from validation code paths in coverage report
- Recommendation: Add tests for: list_engagements(1, limit=200), list_tests(1, limit=0), get_engagement(0), get_test(0), get_finding(0), update_finding(-1), update_finding(1, severity="Bad").

**SB-04** (MINOR) — Code Quality
- Location: tests/test_client.py:161, 196, 233, 283, 301
- Description: `import json` repeated 5 times inside function bodies rather than once at module level.
- Evidence: Each create/update test function imports json inline
- Recommendation: Move to module-level import.

**SB-05** (MINOR) — Code Quality
- Location: tests/test_server.py:37-41 (patched_client fixture)
- Description: Direct attribute assignment to `server_module.client` instead of `mock.patch` or `monkeypatch.setattr`. Brittle if test parallelism is ever added.
- Evidence: `server_module.client = mock` / `server_module.client = None`
- Recommendation: Use `monkeypatch.setattr(server_module, 'client', mock)` for guaranteed cleanup.

**SB-06** (MINOR) — Domain-Specific
- Location: tests/test_client.py:269 (test_get_finding)
- Description: Mock response for get_finding has only 4 fields (`id`, `test`, `title`, `severity`) — missing 7 required FindingSummary fields. If this response were passed to `_format_response`, it would error.
- Evidence: Mock shape doesn't match full API contract; test only checks `result["id"]`
- Recommendation: Use full finding shape from sample_finding fixture to match real API responses.

**SB-07** (MINOR) — Domain-Specific
- Location: pyproject.toml / src/mcp_defectdojo/models.py:26
- Description: PytestCollectionWarning emitted because `TestSummary` model class name starts with "Test".
- Evidence: Warning appears in every test run
- Recommendation: Add `filterwarnings = ["ignore::pytest.PytestCollectionWarning"]` to pytest config.

**SB-08** (MINOR) — Test Coverage
- Location: tests/test_server.py — missing create_product validation
- Description: `create_product` has `prod_type_id <= 0` guard at server.py:99 with no test.
- Evidence: Line 99 in coverage missing list; no test calls create_product with invalid prod_type_id
- Recommendation: Add `test_create_product_zero_prod_type_id`.

## Dimension Summary

| Dimension | Stage | Rating | Key Observations |
|-----------|-------|--------|-----------------|
| Specification Compliance | A | PASS | All 6 ACs met; 4 minor gaps in exhaustive coverage |
| Architectural Compliance | A | PASS | Source files untouched; test structure follows conventions |
| Code Quality | B | PASS | Clean code; minor import style issue and fixture pattern |
| Domain-Specific | B | PASS | Mock shapes mostly realistic; one partial mock noted |
| Test Coverage | B | ISSUES | 80% server threshold met but 6 tools lack happy-path tests; 3 IMPORTANT gaps |

## Overall Assessment

The test suite establishes a solid foundation with 77 tests across 3 files achieving 88% overall coverage. The mocking strategies (respx for HTTP, AsyncMock for server logic) are appropriate and correctly applied. All acceptance criteria are satisfied. The IMPORTANT findings (SB-01 through SB-03) represent coverage gaps where additional tests would bring server.py from 80% to ~95%, particularly for tool functions that currently only have null-guard tests. These are tracked for a future pass but do not block phase completion since the 80% threshold is met.

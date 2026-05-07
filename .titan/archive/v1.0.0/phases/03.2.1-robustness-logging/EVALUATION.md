---
phase: "03.2.1"
name: Robustness & Logging
verdict: PASS-WITH-NOTES
evaluated: 2026-05-07T05:00:00Z
review_model: two-stage
stage_a_verdict: PASS-WITH-NOTES
stage_b_verdict: PASS-WITH-NOTES
findings_critical: 0
findings_important: 2
findings_minor: 9
---

# Phase 03.2.1 — Robustness & Logging — Two-Stage Adversarial Evaluation

## Combined Verdict: PASS-WITH-NOTES

## Stage A — Spec Compliance Review
**Verdict:** PASS-WITH-NOTES

### Findings

**SA-01** (MINOR) — Specification Compliance
- **Location:** `src/mcp_defectdojo/client.py:34`
- **AC Reference:** AC-3.2.1g
- **Description:** The pre-request log only logs method and path (no status — not yet available). The post-response log at line 37 includes all three. AC is satisfied by the combination.
- **Evidence:** Line 34: `logger.debug("API request: %s %s", method, path)` — no status. Line 37: `logger.debug("API response: %s %s → %d", method, path, response.status_code)` — has all three.
- **Recommendation:** No change needed. Informational observation.

**SA-02** (MINOR) — Specification Compliance
- **Location:** `src/mcp_defectdojo/client.py:34,37`
- **AC Reference:** AC-3.2.1g
- **Description:** API call logging uses DEBUG level which may not be emitted in production with default log config. Mutation logging uses INFO (visible). Plan explicitly specified DEBUG for client-level logging.
- **Evidence:** Lines 34, 37: `logger.debug(...)` vs mutation tools: `logger.info(...)`
- **Recommendation:** Acceptable. Can promote to INFO later if audit requirements change.

**SA-03** (MINOR) — Specification Compliance
- **Location:** `src/mcp_defectdojo/server.py:26-28`
- **AC Reference:** AC-3.2.1a
- **Description:** The ValueError handler logs AND re-raises. The server still fails to start, but the failure is now observable via logs. This is intentional fail-fast semantics per the plan design.
- **Evidence:** Lines 26-28: `except ValueError as e: logger.error(...); raise`
- **Recommendation:** No change needed. Correct behavior.

### AC Verification
| AC ID | Criterion | Verified | Evidence |
|-------|-----------|----------|----------|
| AC-3.2.1a | Missing env vars logged | ✓ | server.py:27 — logger.error before re-raise |
| AC-3.2.1b | Public aclose with None guard | ✓ | server.py:30-32 |
| AC-3.2.1c | 14 tools null guard | ✓ | 14 `client is None` checks counted |
| AC-3.2.1d | str(e) in ValidationError | ✓ | server.py:44,56 |
| AC-3.2.1e | ID params validated > 0 | ✓ | All required IDs have guards |
| AC-3.2.1f | VALID_SEVERITIES constant | ✓ | server.py:37 + 4 references |
| AC-3.2.1g | API call logging | ✓ | client.py:34,37,42,50 |
| AC-3.2.1h | Mutation logging | ✓ | 5 logger.info in mutation tools |
| AC-3.2.1i | Tool docstrings | ✓ | All 14 expanded |
| AC-3.2.1j | Dockerfile comment | ✓ | Accurate description |

## Stage B — Code Quality Review
**Verdict:** PASS-WITH-NOTES

### Findings

**SB-01** (IMPORTANT) — Code Quality / Domain-Specific
- **Location:** `src/mcp_defectdojo/server.py`: all tool functions (lines 72-246)
- **Description:** `RuntimeError` from `client._request()` propagates unhandled through tool functions, causing MCP `isError=True` responses instead of tool-level error strings. FastMCP catches it (lowlevel/server.py:583-584) and wraps in `CallToolResult(isError=True)`, which differs semantically from a normal string return with "ERROR:" prefix.
- **Evidence:** client.py raises RuntimeError on API errors (lines 46, 48, 51). Tool functions don't catch it. Domain convention: "Tools return strings, not exceptions."
- **Recommendation:** Wrap `await client.xxx()` calls with `try/except RuntimeError as e: return f"ERROR: {e}"` or create a decorator. Ensures all errors stay in the tool-response plane.

**SB-02** (IMPORTANT) — Code Quality
- **Location:** `src/mcp_defectdojo/server.py:238`
- **Description:** `locals()` usage in `update_finding` is fragile — any local variable introduced before line 238 will silently leak into kwargs and be sent to the API.
- **Evidence:** `kwargs = {k: v for k, v in locals().items() if k != 'finding_id' and v is not None}`
- **Recommendation:** Replace with explicit field list iteration or direct dict construction from named parameters.

**SB-03** (MINOR) — Code Quality
- **Location:** `src/mcp_defectdojo/server.py:22-32` (lifespan)
- **Description:** Only `ValueError` is caught from `DefectDojoClient()`. Other potential exceptions (e.g., httpx config errors on malformed URLs) would propagate without logging.
- **Recommendation:** Consider broadening to `except (ValueError, httpx.InvalidURL) as e:` for completeness.

**SB-04** (MINOR) — Domain-Specific
- **Location:** `src/mcp_defectdojo/server.py:131-138` (`create_engagement`), line 168 (`create_test`)
- **Description:** Date parameters (target_start, target_end) are passed without format validation. LLM agents could pass non-YYYY-MM-DD strings, resulting in API errors.
- **Recommendation:** Add regex check: `re.match(r'^\d{4}-\d{2}-\d{2}$', target_start)`.

**SB-05** (MINOR) — Code Quality
- **Location:** `src/mcp_defectdojo/server.py` (14 tool functions)
- **Description:** The null-guard pattern is repeated verbatim 14 times with the same error message.
- **Recommendation:** Extract to a helper function or decorator for DRY maintenance.

**SB-06** (MINOR) — Domain-Specific
- **Location:** `src/mcp_defectdojo/server.py:51`
- **Description:** JSON responses use `indent=2` which adds whitespace tokens. For LLM consumers, compact JSON would be more token-efficient.
- **Recommendation:** Consider `separators=(',', ':')` without indent for production.

**SB-07** (MINOR) — Test Coverage
- **Location:** Project-wide
- **Description:** No tests exist for any project code.
- **Recommendation:** Tracked for Phase 3.2.2. Not blocking.

**SB-08** (MINOR) — Code Quality
- **Location:** `Dockerfile:9`
- **Description:** UV cache in /tmp is built by root but container runs as appuser. Cache won't be writable at runtime (likely not needed with --frozen).
- **Recommendation:** Consider `RUN rm -rf /tmp/uv-cache` after sync to reduce image size.

## Dimension Summary
| Dimension | Stage | Rating | Key Observations |
|-----------|-------|--------|-----------------|
| Specification Compliance | A | PASS | 10/10 ACs met; minor observations on log levels |
| Architectural Compliance | A | PASS | Module boundaries respected, patterns followed |
| Code Quality | B | PASS-WITH-NOTES | RuntimeError propagation and locals() fragility |
| Domain-Specific | B | PASS-WITH-NOTES | Date validation gap; indent adds tokens |
| Test Coverage | B | N/A (deferred) | Tests planned for Phase 3.2.2 |

## Overall Assessment
All 10 acceptance criteria are fully satisfied with zero deviations from the plan. The two IMPORTANT findings (unhandled RuntimeError propagation and fragile locals() usage) are real maintenance risks but don't affect correctness for current deployment. The RuntimeError issue should be prioritized in the next iteration as it affects how LLM consumers experience API errors through the MCP interface.

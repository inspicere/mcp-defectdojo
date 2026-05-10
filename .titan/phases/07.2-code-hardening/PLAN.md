---
phase: 7.2
name: Code Hardening
goal: Fix 3 source code findings from the v2.2 audit
branch: titan/phase-7.2-code-hardening
status: approved
created: 2026-05-10T23:30:00Z
estimated_tasks: 3
estimated_waves: 1
---

# Phase 7.2 — Code Hardening — Execution Plan

## Goal
Fix all 3 source code findings from the v2.2 full audit: HTTPSLogHandler accepts http://, close_finding partial success not handled, health_check leaks error details.

## Context
- The v2.2 audit identified 3 low-severity source code findings (Vikunja #406, #407, #408)
- `_sanitize_api_error()` already exists in client.py as a pattern for error sanitization
- All fixes are in `src/mcp_defectdojo/` — no CI or config changes

## Acceptance Criteria (This Phase)
- AC-7.2.1: HTTPSLogHandler emits a warning when configured with http:// scheme (Vikunja #406)
- AC-7.2.2: close_finding returns partial success when close succeeds but note fails (Vikunja #407)
- AC-7.2.3: health_check sanitizes error messages, not exposing internal details (Vikunja #408)

## Tasks

### Task T1: Warn on HTTP scheme in HTTPSLogHandler

- **AC**: AC-7.2.1 (Vikunja #406)
- **Mode**: in-session
- **Files to Modify**: `src/mcp_defectdojo/audit_logging.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: In `HTTPSLogHandler.__init__()` (line 227), after the scheme check that already rejects non-http/https schemes, add a warning log when the scheme is `http` (not `https`). Use `import warnings` and emit: `warnings.warn("AUDIT_LOG_HTTPS_URL uses http:// — log data will be transmitted unencrypted. Use https:// in production.", stacklevel=2)`. This preserves backward compatibility (http still works) while alerting operators.
- **Verification Steps**:
  1. `grep -n 'warnings.warn' src/mcp_defectdojo/audit_logging.py` shows the warning
  2. `grep -n 'import warnings' src/mcp_defectdojo/audit_logging.py` shows the import
  3. `cd /home/terrabot/mcp-defectdojo && uv run pytest tests/ -q --tb=short` passes
- **Done Criteria**: HTTPSLogHandler warns when http:// is used but still allows it.
- **Dependencies**: none

### Task T2: Handle close_finding partial success

- **AC**: AC-7.2.2 (Vikunja #407)
- **Mode**: in-session
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: In `close_finding()` (lines 474-486), wrap the `add_finding_note` call in a separate try/except. If close succeeds but note fails, return the close result with a `"warning"` field indicating the note failed. Change from:
  ```python
  res = await client.close_finding(...)
  if note is not None:
      await client.add_finding_note(finding_id, note)
  ```
  To:
  ```python
  res = await client.close_finding(...)
  if note is not None:
      try:
          await client.add_finding_note(finding_id, note)
      except RuntimeError as e:
          res["_warning"] = f"Finding closed but note failed: {e}"
  ```
- **Verification Steps**:
  1. `grep -n '_warning' src/mcp_defectdojo/server.py` shows the partial success handling
  2. `cd /home/terrabot/mcp-defectdojo && uv run pytest tests/ -q --tb=short` passes
- **Done Criteria**: close_finding returns partial success when close works but note fails.
- **Dependencies**: none

### Task T3: Sanitize health_check error messages

- **AC**: AC-7.2.3 (Vikunja #408)
- **Mode**: in-session
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: none
- **Files to Read**: none
- **Action**: In `health_check()` (line 151), change the error return from `f"UNHEALTHY: {e}"` to a sanitized version that classifies the error type without exposing internals. Replace:
  ```python
  except Exception as e:
      return f"UNHEALTHY: {e}"
  ```
  With:
  ```python
  except Exception as e:
      logger.warning("Health check failed", extra={"error": str(e)})
      return "UNHEALTHY: Unable to connect to DefectDojo"
  ```
  The raw error is logged server-side for debugging but the MCP response only shows a generic message.
- **Verification Steps**:
  1. `grep -n 'UNHEALTHY:' src/mcp_defectdojo/server.py` shows only the generic message
  2. `cd /home/terrabot/mcp-defectdojo && uv run pytest tests/ -q --tb=short` passes
- **Done Criteria**: health_check never exposes raw exception text to clients.
- **Dependencies**: none

## Execution Strategy

### Wave 1 — All Tasks (sequential in-session)
Lightweight scope — 3 small code edits. Execute sequentially in-session.

## Boundaries — DO NOT MODIFY

- `.forgejo/` — CI workflows are out of scope
- `Dockerfile` — container image is out of scope
- `pyproject.toml` — project config is out of scope
- `.titan/` — TITAN state files updated only after completion

## Checkpoints

None — scope is trivial and all tasks have automated verification (tests).

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Existing tests check exact health_check error message | Low | Low | Update any test assertions that match exact error text |
| close_finding tests mock both calls | Low | Low | Check existing test expectations |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget
- [x] Total tasks ≤ 3

# TITAN Audit Report

- **Date:** 2026-05-07T08:00:00Z
- **Scope:** All source files (4), test files (4), config, Dockerfile, dependencies
- **Dimensions:** Security, Performance, Code Quality, Domain (MCP Server)
- **Dependency Scan:** `pip-audit` — no known vulnerabilities found

## Summary
| Dimension | Critical | Important | Minor | Score |
|-----------|----------|-----------|-------|-------|
| Security | 0 | 5 | 6 | B- |
| Performance | 0 | 1 | 3 | A- |
| Code Quality | 0 | 2 | 5 | B |
| Domain (MCP) | 0 | 2 | 2 | B |
| **Overall** | **0** | **10** | **16** | **B-** |

## Security Findings

### Important

**SEC-01: No MCP-level authentication or authorization (A01)**
- **File:** `src/mcp_defectdojo/server.py` (entire file)
- All 14 tools (including write operations) are accessible without authentication. Any connected MCP client inherits the full privilege of the API key.
- **Fix:** Document the trust model. For network-exposed deployments, restrict to stdio transport or implement tool-level authorization. Consider read-only API keys for read-only consumers.

**SEC-02: Unvalidated kwargs via locals() (A03)**
- **File:** `src/mcp_defectdojo/server.py:238`
- `update_finding` uses `locals()` to build the kwargs dict. Any future local variable would silently leak into the API request.
- **Fix:** Replace with explicit field dict:
  ```python
  fields = {"title": title, "severity": severity, "description": description, ...}
  kwargs = {k: v for k, v in fields.items() if v is not None}
  ```

**SEC-03: No URL validation / SSRF potential (A10)**
- **File:** `src/mcp_defectdojo/client.py:11`
- `DEFECTDOJO_URL` is used as-is with no validation. No scheme check, no hostname validation.
- **Fix:** Validate URL scheme (require http/https), reject `file://`, internal metadata IPs, and embedded credentials.

**SEC-04: No TLS enforcement (A02)**
- **File:** `src/mcp_defectdojo/client.py:23-27`
- HTTP is accepted without warning; API key transmitted in cleartext.
- **Fix:** Log a warning when HTTP is used, or enforce HTTPS. Document the risk for homelab use.

**SEC-05: Single shared API key for all operations (A07)**
- **File:** `src/mcp_defectdojo/client.py:12,17-18`
- One key for both read and write operations. Compromised key gives full write access.
- **Fix:** Consider separate read/write keys or use DefectDojo RBAC for least-privilege API keys.

### Minor

**SEC-06:** API key stored as plain instance attribute (`client.py:12`) — low risk, ensure `__repr__` never exposes it.

**SEC-07:** Error messages leak internal details (`client.py:46-51`) — base URL and full API error bodies forwarded to MCP client.

**SEC-08:** No date format validation on `target_start`/`target_end` (`server.py:131,168`) — arbitrary strings passed to API.

**SEC-09:** No string length limits on `name`, `title`, `description` — potential for resource exhaustion via large payloads.

**SEC-10:** No upper-bound version pins in `pyproject.toml:11-16` — mitigated by lockfile, but `pyproject.toml` alone does not constrain.

**SEC-11:** No token rotation or expiry handling (`client.py:10-18`) — key read once at startup, requires restart to rotate.

## Performance Findings

### Important

**PERF-01: Client lifecycle — closed client not nullified**
- **File:** `src/mcp_defectdojo/server.py:13`
- After lifespan exit, the global `client` is closed but the reference is not set to `None`. Subsequent calls would use a closed httpx client instead of getting the "not initialized" error.
- **Fix:** Set `client = None` in the `finally` block after `aclose()`.

### Minor

**PERF-02:** Double decode in error handler (`client.py:43-44`) — `e.response.text` then `json.loads()` decodes twice. Use `e.response.json()` instead.

**PERF-03:** `VALID_SEVERITIES` is a list, not a set (`server.py:37`) — membership check is O(n) instead of O(1). Negligible with 5 items, but `frozenset` is idiomatic.

**PERF-04:** Pydantic model create-and-dump for every result item (`server.py:41-43`) — acceptable at 100-item cap, no action needed.

## Code Quality Findings

### Important

**CQ-01: 14x duplicated null-guard pattern**
- **File:** `src/mcp_defectdojo/server.py:61-246`
- Every tool repeats `if client is None: return "ERROR: ..."`. Maintenance burden — 14 locations to update.
- **Fix:** Extract a `@require_client` decorator.

**CQ-02: Client methods return `-> Any`**
- **File:** `src/mcp_defectdojo/client.py:32`
- All client methods return `-> Any`. Static analysis gets no type information.
- **Fix:** Change to `-> dict[str, Any]`.

### Minor

**CQ-03:** `id` parameter shadows Python built-in (`client.py:57,72,88`) — rename to `product_id`, `engagement_id`, etc.

**CQ-04:** Inline `import json` in 4 test functions (`test_client.py:161,196,230,284`) — move to module top.

**CQ-05:** Empty `__init__.py` with no `__all__` — fine for MCP server, note if library use is planned.

**CQ-06:** `FindingSummary.severity` typed as `str` not `SeverityEnum` (`models.py:39`) — asymmetry between create validation and read model.

**CQ-07:** Test docstrings claim assertions that don't exist (e.g., `test_lifespan_success` claims aclose verification but doesn't assert it).

## Domain (MCP Server) Findings

### Important

**DOM-01: Unhandled RuntimeError propagation from client**
- **File:** `src/mcp_defectdojo/server.py:58-252`
- HTTP errors from DefectDojo raise `RuntimeError` which propagates uncaught through tool handlers. Only `health_check` has try/except. Errors become opaque `isError=True` responses instead of structured error strings.
- **Fix:** Wrap all client calls in `try: ... except RuntimeError as e: return f"ERROR: {e}"`.

**DOM-02: Missing date validation on create operations**
- **File:** `src/mcp_defectdojo/server.py:131-139,168-178`
- `target_start` and `target_end` accept any string. Bad dates only fail at the DefectDojo API level with cryptic errors.
- **Fix:** Validate with `date.fromisoformat()` before sending.

### Minor

**DOM-03:** Error responses indistinguishable from success at MCP protocol level (`server.py`) — all tools return plain strings. Consider `ToolError` or `is_error=True` for error cases.

**DOM-04:** No auto-pagination mechanism — LLM must manually loop through pages, which is token-expensive and error-prone.

## Dependency Audit

```
$ uvx pip-audit --path /opt/mcp-defectdojo
No known vulnerabilities found
```

All pinned versions (fastmcp, httpx, mcp, pydantic, python-dotenv, cryptography, certifi) are current.

## Container Security

- Dockerfile runs as non-root user (`appuser`) — GOOD
- `--frozen` flag ensures reproducible builds — GOOD
- No secrets baked into image — GOOD

## Secrets Scan

- No hardcoded secrets in source — CLEAR
- No secrets in git history — CLEAR
- `.gitignore` properly excludes `.env` — CLEAR
- Test fixture `test-api-key-12345` is clearly a test value — NOT FLAGGED

## What Could NOT Be Checked

1. **DefectDojo API key permissions** — cannot verify actual key privilege level on defectdojo-01
2. **Network exposure model** — unclear if MCP server will be stdio-only or SSE-exposed
3. **FastMCP framework internals** — transport-level security not audited
4. **Container runtime args** — Dockerfile reviewed, `docker run` flags not checked
5. **MCP SSE transport auth** — if deployed via SSE (like other homelab MCP servers), transport auth not audited

## Recommended Actions (Priority Order)

1. **DOM-01:** Wrap client calls in try/except — prevents opaque errors to LLM agents
2. **SEC-02:** Replace `locals()` with explicit field dict — eliminates latent injection vector
3. **PERF-01:** Nullify client reference after close — prevents using closed client
4. **DOM-02 / SEC-08:** Add date format validation — prevents cryptic API errors
5. **SEC-03/04:** Add URL validation and TLS warning — hardens deployment config
6. **CQ-01:** Extract `@require_client` decorator — reduces 14x duplication
7. **SEC-01/05:** Document trust model, consider least-privilege API keys

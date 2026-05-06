# TITAN Audit Report — mcp-defectdojo

- **Date:** 2026-05-06
- **Scope:** All source files (`src/mcp_defectdojo/`), `Dockerfile`, `pyproject.toml`, `.gitignore`
- **Dimensions:** Security, Performance, Domain (MCP), Code Quality
- **Lines Audited:** 278 (4 Python source files) + 19 (Dockerfile)

## Summary

| Dimension | Critical | Important | Minor | Score |
|-----------|----------|-----------|-------|-------|
| Security | 2 | 6 | 4 | D |
| Performance | 1 | 2 | 2 | C |
| Domain (MCP) | 1 | 5 | 7 | C+ |
| Code Quality | 0 | 4 | 5 | C+ |
| **Overall** | **4** | **17** | **18** | **D+** |

---

## Critical Findings

### SEC-C1: No MCP authentication or authorization
**server.py — entire file**

The FastMCP server has zero access control. Any client that can reach the transport (stdio or SSE) can call all 14 tools, including mutating operations (`create_product`, `create_finding`, `update_finding`). There is no user identification, bearer token, or permission model.

**Fix:** Implement MCP-level authentication — require a bearer token or API key for MCP clients. Restrict write operations to authorized callers.

### SEC-C2: `.env` not in `.gitignore`
**.gitignore**

The `.gitignore` does not exclude `.env` files. Any `git add .` will commit secrets (DEFECTDOJO_API_KEY). This is a ticking time bomb.

**Fix:** Add `.env` and `.env.*` (except `.env.example`) to `.gitignore`. Takes 30 seconds.

### DOM-C1: health_check is a static lie
**server.py:21-23**

`health_check()` returns hardcoded `"200 OK"` without verifying DefectDojo connectivity, API key validity, or client initialization. Monitoring tools and agents will always see "healthy" even when DefectDojo is unreachable.

**Fix:** Call `await client.get_products(limit=1)` inside a try/except and return actual status.

### PERF-C1: httpx.AsyncClient is never closed
**client.py:22 / server.py:8**

The `DefectDojoClient` creates an `httpx.AsyncClient` in `__init__` but never calls `aclose()`. Over time this leaks TCP connections and file descriptors. The module-level instantiation (`client = DefectDojoClient()` at server.py:8) also prevents testing without env vars and fails the entire import if config is missing.

**Fix:** Defer client creation to FastMCP's lifespan context. Create on startup, close on shutdown.

---

## Important Findings

### Security

#### SEC-I1: No TLS enforcement on DEFECTDOJO_URL
**client.py:10**

`DEFECTDOJO_URL` is read from environment with no scheme validation. If set to `http://`, the API token transmits in cleartext. No SSRF protection either — a manipulated env var redirects all API calls (and the token) to an attacker-controlled server.

**Fix:** Validate URL scheme is `https://` in production. Add `verify=True` explicitly to httpx.

#### SEC-I2: No input validation on tool parameters
**server.py:100 (severity), server.py:28/48/68/88 (limit), client.py:44-95 (IDs)**

- `severity` accepts arbitrary strings — DefectDojo only accepts Critical/High/Medium/Low/Info.
- `limit` has no upper bound — `limit=999999` causes massive responses.
- Integer IDs have no positive-integer validation.

**Fix:** Add severity enum, cap `limit` at 100, validate IDs > 0.

#### SEC-I3: Verbose error messages leak API internals
**client.py:31-38**

Full DefectDojo error response body is forwarded to MCP callers. Could expose internal stack traces, database details, or API structure.

**Fix:** Sanitize error messages for callers. Log full details server-side only.

#### SEC-I4: Zero logging or audit trail
**entire project**

No `logging` module usage anywhere. No tool invocations logged, no errors recorded, no mutation trail. Impossible to detect abuse or debug production issues.

**Fix:** Add structured logging for all tool invocations (especially mutating ones) and API errors.

#### SEC-I5: Dockerfile runs as root
**Dockerfile (no USER directive)**

Container processes run as root. A compromised MCP server grants root inside the container.

**Fix:** Add `RUN useradd -r -s /bin/false appuser && USER appuser`.

#### SEC-I6: API token persists in memory indefinitely
**client.py:11,16-17**

Token stored as plain string attribute for process lifetime. No rotation mechanism without restart.

**Fix:** Consider reading token per-request or supporting a refresh callback. Low priority for internal use.

### Performance

#### PERF-I1: No timeout configuration on httpx client
**client.py:22**

No explicit `timeout` parameter. Default httpx timeout (5s) may be insufficient for large DefectDojo instances. Behavior is coupled to httpx version defaults.

**Fix:** Set `timeout=httpx.Timeout(30.0, connect=5.0)`.

#### PERF-I2: Double serialization in _format_response
**server.py:15**

Response flows: JSON → dict (httpx) → Pydantic model → dict (model_dump) → JSON string (json.dumps with indent=2). Three transformations per item, plus indent=2 wastes tokens.

**Fix:** Use `model.model_dump_json()` directly. Use compact separators.

### Domain (MCP)

#### DOM-I1: Pagination metadata silently discarded
**server.py:13-15**

`_format_response` extracts only `result["results"]`, discarding `count`, `next`, `previous`. Agents cannot determine total results or whether more pages exist.

**Fix:** Return `{"total": count, "offset": X, "limit": Y, "items": [...]}`.

#### DOM-I2: Missing search/filter capabilities
**server.py — list tools**

`list_products` has no name filter. `list_findings` filters only by `test_id`. Agents can't query "all critical active findings" without paging through everything.

**Fix:** Add name filter for products, severity/active/verified filters for findings.

#### DOM-I3: Missing update tools for products, engagements, tests
**server.py**

Only `update_finding` exists. No update operations for products, engagements, or tests. Agents can't correct mistakes after creation.

**Fix:** Add PATCH-based update tools for all entity types.

#### DOM-I4: Network errors propagate as raw exceptions
**client.py:24-38**

Only `httpx.HTTPStatusError` is caught. `ConnectError`, `TimeoutException`, `ReadError` produce opaque stack traces instead of agent-friendly messages.

**Fix:** Catch `httpx.RequestError` and wrap with clear message.

#### DOM-I5: Module-level client blocks import on missing config
**server.py:8 / client.py:13-14**

`ValueError` raised at import time if env vars are missing. Makes testing impossible without full config. FastMCP can't even register tools.

**Fix:** Defer instantiation to lifespan context (also fixes PERF-C1).

### Code Quality

#### CQ-I1: Bare `except Exception` swallows its own RuntimeError
**client.py:37-38**

The inner `try/except` catches `Exception`, which includes the `RuntimeError` raised on line 36. If the well-formatted error is raised, the bare except catches and re-wraps it with less context.

**Fix:** Narrow to `except (json.JSONDecodeError, KeyError, TypeError):`.

#### CQ-I2: Dead code in `__init__.py`
**__init__.py:1-2**

`main()` prints "Hello from mcp-defectdojo!" — never called. Conflicts with the real entry point `server:main`. Maintenance hazard.

**Fix:** Remove or re-export `server.main`.

#### CQ-I3: Unused imports
**client.py:3**

`Dict` and `List` imported from `typing` but never used.

**Fix:** Change to `from typing import Any`.

#### CQ-I4: Missing type hint on `get_findings` parameter
**client.py:88**

`test_id: int = None` should be `test_id: int | None = None`.

**Fix:** Add `Optional` or union type.

---

## Minor Findings

| # | Dimension | File:Line | Description |
|---|-----------|-----------|-------------|
| 1 | Security | Dockerfile:1 | Base image uses mutable tag — no digest pinning |
| 2 | Security | Dockerfile:9 | UV cache not cleaned — increases image size |
| 3 | Security | pyproject.toml | No `pip-audit` in CI — dependency CVE scanning missing |
| 4 | Security | README vs client.py | Env var name mismatch: `DEFECTDOJO_API_TOKEN` vs `DEFECTDOJO_API_KEY` |
| 5 | Domain | server.py:7 | FastMCP missing `description` parameter for agent discovery |
| 6 | Domain | server.py:100 | `severity` valid values not documented in tool description |
| 7 | Domain | server.py:60 | Date format (YYYY-MM-DD) not documented for engagement dates |
| 8 | Domain | server.py:15 | `indent=2` JSON is token-wasteful for LLM consumption |
| 9 | Domain | models.py | Missing fields: tags, findings_count, status, engagement_type, cwe, cvssv3 |
| 10 | Domain | models.py | No product_type listing tool — agents can't discover valid prod_type IDs |
| 11 | Domain | server.py:126 | `mcp.run()` hardcodes stdio — no SSE transport for Docker deployment |
| 12 | Quality | server.py:120 | `locals()` usage for kwargs is fragile |
| 13 | Quality | models.py:4 | `ProductSummary` missing `model_config` that other models have |
| 14 | Quality | pyproject.toml:4 | Placeholder description: "Add your description here" |
| 15 | Quality | server.py:10 | `_format_response` missing type hints |
| 16 | Quality | models.py:34 | Redundant `mitigated` + `is_mitigated` fields |
| 17 | Domain | server.py | No scan import/reimport tools — DefectDojo's primary use case |
| 18 | Domain | server.py | No delete operations (may be intentional — document in DECISIONS.md) |

---

## What Could NOT Be Checked

1. **pip-audit / CVE scan** — tool not available in environment
2. **Runtime SSRF testing** — requires live DefectDojo instance
3. **MCP protocol-level fuzzing** — transport-layer attacks
4. **DefectDojo API token permissions** — principle of least privilege verification
5. **Network segmentation** — whether MCP server is exposed beyond intended boundary
6. **Memory safety under load** — large paginated responses
7. **Race conditions** — concurrent tool calls sharing single httpx client

---

## Recommended Actions (Priority Order)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | Add `.env` to `.gitignore` | 1 min | Prevents secret leakage |
| 2 | Add `USER` directive to Dockerfile | 1 min | Container runs non-root |
| 3 | Fix error handling (`except` clause + network errors) | 15 min | Agent-friendly errors |
| 4 | Add httpx timeout + close lifecycle | 30 min | Fixes resource leak + hangs |
| 5 | Implement real health check | 15 min | Honest monitoring |
| 6 | Add structured logging | 30 min | Audit trail + debugging |
| 7 | Add input validation (severity enum, limit cap) | 30 min | Prevents misuse |
| 8 | Include pagination metadata in responses | 15 min | Agents know result totals |
| 9 | Clean up dead code + unused imports | 5 min | Code hygiene |
| 10 | Add MCP authentication | 2-4 hrs | Full access control |

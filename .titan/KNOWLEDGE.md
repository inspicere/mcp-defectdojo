# TITAN Knowledge Base

> Accumulated project knowledge, patterns, and learnings.
> Updated automatically during verify phases and manually via /titan:learn.

## Project Facts
- Type: greenfield
- Domain: mcp server
- Initialized: 2026-05-04T02:06:49Z

## Patterns Discovered
- Module-level client instantiation blocks import when env vars are missing, making testing impossible
- FastMCP lifespan context is the correct place for client creation/teardown
- `except Exception` in error handlers catches its own re-raised exceptions, creating confusing wrapping

## Key Learnings

### Full Audit (2026-05-06)
- 39 findings across 4 dimensions: Security (D), Performance (C), Domain/MCP (C+), Code Quality (C+)
- 4 critical, 17 important, 18 minor — overall score D+
- Critical findings: no MCP auth, `.env` not in `.gitignore`, fake health check, httpx client never closed
- Previous audit report (`.titan/AUDIT.md` root) claimed auto-fixes applied — source code did not reflect those changes
- Accurate audit written to `.titan/phases/01-deployment-configuration/AUDIT.md`
- No test suite exists — zero test coverage is a significant gap

### Security Patterns
- `.env` exclusion from `.gitignore` is a common miss in scaffolded projects — always verify
- MCP servers inherit the trust model of their transport; stdio is local-only but SSE exposes to network
- Dockerfile without USER directive runs as root — easy fix, high impact

### Architecture Observations
- httpx.AsyncClient should be managed via lifespan (create on startup, aclose on shutdown)
- Double serialization path (JSON -> dict -> Pydantic -> dict -> JSON) wastes cycles and tokens
- Pagination metadata (`count`, `next`, `previous`) discarded in `_format_response` — agents can't paginate

## Phase 02 — Audit Remediation (2026-05-07)

### Patterns
- Lifespan context manager with `global client` + module-level `None` declaration is effective for deferred initialization in FastMCP
- Moving `load_dotenv()` from client to server lifespan centralizes env loading and prevents import-time crashes
- Narrowing `except Exception` to specific exception types (JSONDecodeError, ConnectError, TimeoutException) produces clearer error chains

### Learnings
- All 3 tasks matched plan exactly — zero deviations. Precise delta specs in PLAN.md (exact file, exact line, exact change) eliminate ambiguity for executor agents
- Two-stage review found 13 findings (8 important, 5 minor) despite all 11 ACs passing — confirms that AC satisfaction and code quality are orthogonal concerns
- Private attribute access across module boundaries (`client._client.aclose()`) is a recurring encapsulation gap — add public `aclose()` methods to wrapper classes
- Pydantic model instantiation from external API data needs ValidationError handling — API responses don't always match expected schema

### Anti-Patterns
- Declaring `logger = logging.getLogger(__name__)` without any log statements — either use it or don't import it
- `isinstance(result, str)` guard in _format_response was dead code from day one — defensive checks that can't fire add confusion
- Silent no-op operations (empty PATCH body) give LLM agents no feedback — always return an explicit error for degenerate inputs

## Phase 03.1 — Input Validation & Pagination (2026-05-07)

### Patterns
- Precise delta specs in PLAN.md continue to produce zero-deviation builds — 3/3 tasks matched plan exactly for a second consecutive phase
- Input validation guards using early-return string errors (not exceptions) are idiomatic for MCP tools — agents receive the error as a tool response rather than a transport failure
- `_format_response` with offset/limit passthrough centralizes pagination metadata without changing tool function signatures

### Learnings
- Plan under-specification cascades: FR-012 said "ID <= 0" generically, but the plan only applied validation to get_*/create_* tools — list_* filter params (product_id, engagement_id, test_id) were missed. Both review stages caught this independently, validating the two-stage approach
- Adding a public method (aclose) without updating its only call site creates immediate dead code — plans should specify both "add method" and "update callers" as atomic
- Two-stage review found 11 unique findings (after dedup) vs. 7 per stage individually — ~57% overlap confirms the stages catch different things

### Anti-Patterns
- `e.errors()[0]['msg']` in ValidationError handlers is fragile — use `str(e)` or guard for empty list
- Module-level `client: X | None = None` without null guards on consumers means any pre-lifespan call produces an opaque AttributeError instead of a descriptive error

## Technology Notes
- FastMCP: supports SSE and stdio transports; lifespan context for resource management
- httpx: requires explicit `aclose()` or use as async context manager; default timeout is 5s
- tenacity: retry decorator; use `retry_if_exception_type` for targeted retries on 5xx/timeout

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

## Technology Notes
- FastMCP: supports SSE and stdio transports; lifespan context for resource management
- httpx: requires explicit `aclose()` or use as async context manager; default timeout is 5s
- tenacity: retry decorator; use `retry_if_exception_type` for targeted retries on 5xx/timeout

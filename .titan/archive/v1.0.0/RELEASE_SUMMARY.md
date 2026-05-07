# Release v1.0.0 — mcp-defectdojo

## What Was Built

### Phase 01 — Deployment Configuration
- MCP server scaffolding with FastMCP framework
- 14 tools covering products, engagements, tests, and findings
- DefectDojo API client with async httpx
- Dockerfile with non-root user, health check endpoint
- Tasks: 3/3 completed
- Verdict: PASS

### Phase 02 — Audit Remediation
- Fixed 4 critical security findings from initial audit
- Input validation on all tool parameters
- Structured error handling with ToolError exceptions
- Tasks: 3/3 completed
- Verdict: PASS

### Phase 03 — Quality Improvements (split into 03, 03.2.1, 03.2.2)
- **03.1 — Input Validation & Pagination**: Pagination metadata, limit/offset validation, ID validation
- **03.2.1 — Robustness & Logging**: RuntimeError propagation fix, structured logging, URL validation, TLS warning
- **03.2.2 — Test Coverage**: Full test suite (4 test files), pytest-asyncio + respx infrastructure
- Resolved all 10 important audit findings: decorator extraction, typed returns, explicit field dicts, ToolError signaling, error sanitization, date validation, MCP authentication
- Tasks: 9/9 completed across sub-phases
- Verdict: PASS

## Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | FastMCP over raw MCP SDK | Higher-level API, built-in auth support, less boilerplate |
| 2 | httpx over aiohttp | Better typing, timeout config, native async context manager |
| 3 | Pydantic models for response shaping | Type safety, validation, consistent serialization |
| 4 | ToolError for all error paths | MCP protocol compliance — sets is_error=True in responses |
| 5 | Container/Ansible deployment | Consistent with Laima homelab infrastructure |
| 6 | StaticTokenVerifier for MCP auth | Built-in FastMCP feature, auto-skips on stdio transport |
| 7 | Phase 03 split into 3 sub-phases | Scope exceeded single-phase budget |

## Known Limitations
- No auto-pagination mechanism — LLM must manually loop through pages (DOM-04)
- Single shared API key for all operations (SEC-05)
- No rate limiting on MCP tool calls (SEC-09 area)
- Error messages may leak API structure details to MCP client

## Metrics
- Phases completed: 5 (01, 02, 03.1, 03.2.1, 03.2.2)
- Total tasks: 15 planned, 15 completed, 0 deferred
- Audit score: B- overall (0 critical, 10 important, 16 minor)
- All 10 important findings resolved before ship
- Knowledge items captured: 5+ patterns, architecture decisions documented

## Cost Summary
- Cost tracking: not enabled

## Deferred to Future
- DOM-04: Auto-pagination mechanism — token-expensive for LLM agents (Vikunja #259)
- SEC-05: Separate read/write API keys — requires DefectDojo RBAC setup (Vikunja #260)
- SEC-09/SEC-10: String length limits, version pinning — low risk, tracked

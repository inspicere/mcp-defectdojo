# TITAN Decision Log

> Every non-trivial decision with rationale. Future sessions consult this first.

| # | Date | Decision | Rationale | Revisitable? |
|---|------|----------|-----------|-------------|
| 1 | 2026-05-04 | Domain: mcp server | User selection during initialization | Yes — /titan:settings |
| 2 | 2026-05-04 | Profile: balanced | User selection during initialization | Yes — /titan:settings |

| 3 | 2026-05-04 | Tech Stack: Python/FastMCP/httpx | Defaulted to Python as it is standard for security tools. | Yes |
| 4 | 2026-05-04 | Package Management: uv | Chosen to enforce strict lockfiles and hash-checking for supply chain security. | Yes |
| 5 | 2026-05-04 | Deployment: Container/Ansible | Consistent with Laima infra patterns (Dockerfile + Ansible playbook). | Yes |
| 6 | 2026-05-06 | Audit report accuracy | Previous auto-generated audit claimed fixes applied; re-audited against actual source code. Authoritative report: `.titan/phases/01-deployment-configuration/AUDIT.md` | No |
| 7 | 2026-05-07 | Phase 03 split into 3.1 (Validation & Pagination) + 3.2 (Logging & Robustness) | Scope exceeded 3-task budget: 3 FRs + 13 deferred findings across multiple functions in 3 files. Split by feature cohesion — 3.1 covers user-facing quality (FR-012, FR-013), 3.2 covers operational quality (FR-014, tests, robustness). | No |
| 8 | 2026-05-07 | Phase 3.2 split into 3.2.1 (Robustness & Logging) + 3.2.2 (Test Coverage) | 14 deferred findings + FR-014 + test suite exceeded 3-task budget. Split by dependency: 3.2.1 fixes code, 3.2.2 tests it. All 3 tasks in 3.2.1 touch server.py so waves are sequential. | No |
| 9 | 2026-05-07 | Structured logging uses stdlib `logging`, not `structlog` | No new dependency needed; `logger = logging.getLogger(__name__)` already exists in client.py. Can migrate to structlog later if needed. | Yes |
| 10 | 2026-05-08 | Per-tool auth via FastMCP `auth` param, not custom middleware | FastMCP provides `@mcp.tool(auth=check_fn)` which automatically skips auth on stdio transport. Cleaner than a custom decorator or global middleware. | No |
| 11 | 2026-05-08 | Custom mutation-only rate limiter instead of FastMCP global RateLimitingMiddleware | FastMCP's built-in rate limiter applies to all requests. We only want to limit mutations (create/update), not reads. Custom MutationRateLimiter in security.py provides per-caller, mutation-specific limiting. | Yes |
| 12 | 2026-05-08 | FR-027 (security headers) deferred to reverse proxy layer | FastMCP manages the HTTP app internally. Security headers (X-Frame-Options, CSP, etc.) are properly handled at the reverse proxy (nginx/traefik) layer, not in the application. | No |
| 13 | 2026-05-10 | v2.2.0 feature expansion via 4 parallel worktree-isolated subagents | 4 independent feature sets (scan import, metadata, lifecycle, filters) had zero cross-dependencies, allowing parallel development in isolated worktrees. All merged cleanly to main. | No |
| 14 | 2026-05-10 | Scan import uses base64 file content via MCP params, not file paths | MCP tools cannot access client filesystem; base64 encoding with 50MB decoded size limit is the standard pattern for file transfer over MCP. | No |
| 15 | 2026-05-10 | close_finding maps reasons to DefectDojo boolean fields | DefectDojo uses separate boolean fields (is_mitigated, false_p, out_of_scope, duplicate) rather than a single status enum. close_finding abstracts this into a single `reason` parameter. | No |
| 16 | 2026-05-10 | API error sanitization at client boundary | Error responses sanitized in `_request()` and `_multipart_request()` using generic messages per HTTP status code. Full detail logged at DEBUG. Prevents leaking DefectDojo field names and validation rules to MCP clients. | No |
| 17 | 2026-05-10 | note_type parameter defaults to None, not 0 | DefectDojo has no note_type with pk=0. Changed from `int = 0` to `int | None = None` with conditional payload inclusion. Foreign key defaults should never be 0. | No |

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
| 18 | 2026-05-10 | RBAC: static token-role mapping over OAuth/OIDC | See DEC-018 below. | No |
| 19 | 2026-05-10 | RBAC: hierarchical roles over flat permission sets | See DEC-019 below. | No |
| 20 | 2026-05-10 | RBAC: environment variables for role definitions | See DEC-020 below. | No |

---

## DEC-018: Static Token-Role Mapping over OAuth/OIDC

**Context:** RBAC design requires a mechanism to authenticate callers and resolve their permissions. Options considered: (a) OAuth2/OIDC integration with an external IdP, (b) JWT-based self-issued tokens with role claims, (c) static token-role mapping via environment variables.

**Decision:** Use static token-role mapping via environment variables (`MCP_ROLE_<NAME>=<token>:<role>`).

**Rationale:**
- Single-tenant deployment — one DefectDojo instance with 2-5 MCP callers, not a multi-tenant SaaS.
- No external Identity Provider exists in the Laima homelab (no Keycloak, no Auth0).
- FastMCP's `StaticTokenVerifier` already implements this pattern — we extend, not replace.
- Environment variables integrate cleanly with Vault secret injection (existing deployment pattern).
- Operational simplicity — no token refresh, no JWKS endpoint, no clock-skew issues.

**Consequences:**
- Adding/removing callers requires container restart (env var reload).
- No token expiration — revocation requires replacing the token in Vault and restarting.
- Acceptable for <10 callers; would not scale to 100+ without migration to JWT/OIDC.

---

## DEC-019: Hierarchical Roles over Flat Permission Sets

**Context:** Permission model options: (a) flat per-tool permission bitmask (each caller gets explicit list of allowed tools), (b) hierarchical roles where higher roles inherit lower role permissions, (c) hybrid with roles + per-caller overrides.

**Decision:** Use hierarchical roles (admin > writer > scanner > reader) with fixed permission sets per role.

**Rationale:**
- 4 roles cover all known use cases: CI scanners (scanner), security analysts (writer), automation admin (admin), dashboards/reports (reader).
- Simpler mental model for operators — "this token is a scanner" vs "this token can import_scan, reimport_scan, list_findings, get_finding, ...".
- Fewer configuration errors — impossible to accidentally grant `create_product` without `list_products`.
- Role hierarchy means fewer env vars to manage (one per caller, not one per permission).

**Consequences:**
- No fine-grained exceptions (can't give a writer scan_mgmt but deny finding_mgmt without creating a new role).
- If a 5th use case emerges that doesn't fit the hierarchy, a new role must be added.
- Acceptable: 4 roles with clear semantics is easier to audit than arbitrary permission combinations.

---

## DEC-020: Environment Variables for Role Definitions

**Context:** Role-token binding storage options: (a) config file (YAML/JSON), (b) environment variables, (c) database/external store.

**Decision:** Use environment variables with naming convention `MCP_ROLE_<NAME>=<token>:<role>`.

**Rationale:**
- Consistency: all existing configuration (DEFECTDOJO_URL, DEFECTDOJO_API_KEY, MCP_AUTH_TOKEN, LOG_LEVEL) uses env vars.
- Vault integration: Vault's env_template and container env injection already handle secret rotation for env vars.
- Container-friendly: no file mounts needed, works with Docker, Podman, systemd, and Kubernetes.
- Backward-compatible: existing `MCP_AUTH_TOKEN`/`MCP_READ_TOKEN` continue working (mapped to admin/reader).

**Consequences:**
- Role definitions are immutable after startup — no hot-reload without restart.
- Token values visible in `docker inspect` output (acceptable: same as current MCP_AUTH_TOKEN pattern; Vault handles rotation).
- Naming convention must be documented clearly to avoid collisions (MCP_ROLE_ prefix is unique).

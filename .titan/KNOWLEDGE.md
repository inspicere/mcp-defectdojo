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

## Phase 03.2.1 — Robustness & Logging (2026-05-07)

### Patterns
- Precise delta specs in PLAN.md produce zero-deviation builds for a third consecutive phase (3/3 tasks matched plan exactly across Phases 02, 03.1, and 03.2.1)
- Stdlib `logging.getLogger(__name__)` with level differentiation (DEBUG for client internals, INFO for mutations) gives observability without noise
- Public `aclose()` wrapper on client + `if is not None` guard in lifespan finally = safe shutdown in all failure modes

### Learnings
- `locals()` for kwargs construction is a maintenance footgun — any new local variable silently leaks into API calls. Explicit field enumeration is safer.
- FastMCP catches unhandled exceptions from tool functions and wraps them in `CallToolResult(isError=True)` — this is semantically different from returning an error string. Tools should catch all expected exceptions and return strings to maintain uniform error surface for LLM consumers.
- Two-stage review found 2 IMPORTANT + 9 MINOR issues despite 10/10 ACs passing — confirms the pattern that AC satisfaction and code quality remain orthogonal concerns even after multiple phases.

### Anti-Patterns
- `RuntimeError` propagation through MCP tool functions creates split error paths (some errors are strings, some are isError=True) — confusing for LLM agent consumers
- `json.dumps(indent=2)` wastes tokens in LLM-facing responses — compact JSON is more appropriate for MCP tools

## Phase 03.2.2 — Test Coverage (2026-05-07)

### Patterns
- `respx` as httpx-native mock transport (decorator-per-test) + `AsyncMock` for server-layer isolation is an effective dual-strategy: tests HTTP correctness at the client level, logic correctness at the server level
- Parametrized null-guard tests with (function, kwargs, expected_substring) tuples ensure all tools are tested without test code explosion
- `paginated_response()` helper in conftest.py (not a fixture) avoids unnecessary fixture overhead for simple data construction

### Learnings
- Plan-specified 9 happy path tests left 5 tools without server-level integration coverage. For future test plans: specify one happy path per public function explicitly, or note the gap as deliberate
- `TestSummary` as a Pydantic model name triggers PytestCollectionWarning — class names starting with "Test" collide with pytest discovery heuristics. Rename models or filter in pytest config
- Direct assignment to module globals (`server_module.client = mock`) works for yield fixtures with cleanup but is fragile — `monkeypatch.setattr` provides guaranteed teardown
- Inline `import json` within test functions is a common code-gen pattern (agents generate tests function-by-function) — consolidate to module level during review

### Anti-Patterns
- Docstrings claiming assertions that don't exist (test_lifespan_success claims to verify aclose but doesn't assert it) — misleading for future maintainers
- Partial mock responses (e.g., 4-field finding dict) that don't match the real API shape — these tests pass but would fail if piped through model validation

## Pre-Ship Audit (2026-05-07)

### Results
- Overall score improved from D+ (Phase 01) to B- (pre-ship): 0 critical (was 4), 10 important (was 17), 16 minor (was 18)
- All 4 critical findings from Phase 01 audit resolved through Phases 02-03
- Dependencies clean (pip-audit), no secrets in git history, container security good

### Remaining Important Findings
- DOM-01: RuntimeError propagation in 13/14 tools (Vikunja #235)
- SEC-02: locals() kwargs injection vector in update_finding (Vikunja #236)
- PERF-01: Closed client reference not nullified after shutdown
- DOM-02/SEC-08: No date format validation on create operations (Vikunja #237)
- SEC-01: No MCP-level auth (Vikunja #180)
- SEC-03: No URL validation on DEFECTDOJO_URL (SSRF potential)
- SEC-04: No TLS enforcement
- SEC-05: Single shared API key
- CQ-01: 14x duplicated null-guard pattern
- CQ-02: Client methods return -> Any

### Patterns
- Audit score improvement tracks linearly with phase completion — each phase addressed a distinct quality dimension
- `pip-audit` as a dependency scan tool integrates cleanly into TITAN audit workflow
- Pre-ship audit as a gate before /titan-ship catches regressions and validates remediation completeness

## Deployment (2026-05-07)

### Production Deployment
- Deployed to mcp-01 (192.168.86.127:3500) as Docker container
- Pushed to Forgejo: main branch (32 commits) + v1.0.0 tag
- Service account: `svc-mcp` (Writer role, user ID 3) — least privilege, no superuser access
- API token stored in HashiCorp Vault at `secret/mcp/defectdojo_api_key`
- Verified: list_products returns 200 (23 products), list_users returns 403 (correct denial)

### Docker Networking on mcp-01
- **Root cause of container networking failure:** nftables `forward` chain had `policy drop` with no rules, and `iptables` was not installed. Docker containers could not reach any LAN hosts.
- **Fix:** Added Docker support to nftables role — forward chain rules for Docker subnets (172.17.0.0/16, 172.18.0.0/16) + NAT masquerade table.
- **Critical lesson:** `flush ruleset` in nftables wipes Docker's iptables-nft rules (tables `ip filter`, `ip nat`, `ip raw`). After any nftables reload on a Docker host, the Docker daemon MUST be restarted (`systemctl restart docker`) to rebuild its DNAT/NAT rules. This is a known limitation of mixing nftables with Docker's iptables backend.

### Git Cleanup
- Removed tracked `__pycache__` files (committed before gitignore rule existed)
- Added `.coverage` and `htmlcov/` to `.gitignore`

## Production Validation (2026-05-08)

### Bug Fix: create_finding Missing Required Fields
- DefectDojo API requires `numerical_severity` and `found_by` on POST /findings/
- Added `_SEVERITY_TO_NUMERICAL` mapping (Critical→S0, High→S1, Medium→S2, Low→S3, Info→S4)
- Added `found_by: [1]` (Manual Pen Test type) as default
- Committed as `3fb12d3`, deployed to mcp-01

### Validation Results (32 tests, all pass)
- All 14 tools tested with valid inputs, invalid inputs, boundary conditions
- Pagination: limit/offset bounds enforced (1-100, >=0), last page has_next=false
- ID validation: <=0 rejected on all tools, non-existent IDs return 404
- Date validation: non-ISO dates rejected on create_engagement, create_test
- Severity validation: invalid values rejected on create_finding and update_finding
- update_finding: empty update rejected, multi-field update works, DefectDojo business logic enforced (false_p on verified finding rejected)
- svc-mcp Writer role: cannot create_product (403) — expected least-privilege behavior

### DefectDojo Findings Created
- #1017 (Laima Infrastructure): nftables forward chain blocking Docker outbound — Medium, mitigated
- #1018 (mcp-defectdojo): MCP server running with admin API token — Medium, mitigated

## Phase 4.1 — Structured Log Infrastructure (2026-05-08)

### Patterns
- StructuredJsonFormatter as a custom `logging.Formatter` subclass produces single-line JSON per log entry — compatible with Loki/ELK/Splunk ingestion without preprocessing
- RedactingFilter as a `logging.Filter` subclass intercepts log records before formatting — secrets are redacted regardless of formatter or handler
- `configure_logging()` as a single entry point centralizes handler/formatter/filter setup and reads LOG_LEVEL from env var with INFO default

### Learnings
- RedactingFilter must inspect `extra` dict values, not just the message string — structured logging puts sensitive data in extra fields (e.g., `request_params` containing API tokens)
- Exception tracebacks must be explicitly included in JSON output via `self.formatException(record.exc_info)` — the default JSON formatter drops them silently
- 10 tests cover: JSON format validity, log level configuration, redaction of secrets in messages and extra dicts, exception traceback inclusion

### Anti-Patterns
- Redacting only the message string while passing raw secrets in extra fields — structured logging shifts data from messages to structured fields

## Phase 4.2 — Audit Coverage & Identity (2026-05-08)

### Patterns
- `audit_tool` decorator wraps all 14 tool functions uniformly — generates request_id (UUID), extracts caller_id from FastMCP Context, measures duration via `time.perf_counter()`, logs success/error outcome
- `contextvars.ContextVar` for request_id propagation from server layer to client layer — avoids passing request_id through every function signature
- FastMCP `Context` object provides `request_context.meta.client_id` for caller identity — falls back to "anonymous" with WARNING log when absent

### Learnings
- Decorator approach eliminates duplicated audit boilerplate across 14 tools — single change point for audit format evolution
- `ctx: Context = None` parameter on all tools allows both decorated (with context) and direct (without context) invocation — backward compatible with tests
- ContextVar-based request_id propagation means client.py reads the correlation ID without any API change — zero coupling between layers
- RedactingFilter must recurse into nested dict/list values in extra fields — `request_params` can contain nested dicts with secrets
- 10 tests cover: audit field presence, caller identity extraction, anonymous access warning, request_id propagation, duration tracking

### Anti-Patterns
- Manual audit log calls in individual tools alongside a decorator — creates duplicate log entries. Decorator should be the single source of audit logging.

## Phase 5 — Access Control & Hardening (2026-05-08)

### Patterns
- FastMCP's per-tool `auth` parameter (`@mcp.tool(auth=check_fn)`) is the correct way to enforce scopes — automatically skips auth on stdio transport, enforces on HTTP/SSE
- Custom `scope_check(scope)` function that returns True when token is None provides backward compatibility for servers that may run without auth configured
- `_make_client(base_url, api_key)` factory function cleanly supports dual API key mode — each httpx.AsyncClient gets its own Authorization header at construction time
- `_select_client(method)` routing by HTTP method (GET→read, POST/PATCH→write) is simple and correct for DefectDojo's REST API

### Learnings
- FastMCP has built-in `AuthMiddleware`, `require_scopes()`, `restrict_tag()`, and `RateLimitingMiddleware` — always check framework capabilities before building custom solutions
- When adding new secret env vars, the RedactingFilter must be updated immediately — SB-01 caught 3 missing secrets that would have leaked to structured logs
- Module-level rate limiter construction depends on load_dotenv() being called first (via _build_auth) — implicit ordering dependency worth documenting
- TLS enforcement with ALLOW_INSECURE_HTTP override pattern: reject by default, log CRITICAL when overridden — makes insecure configs visible in audit logs
- Test fixtures using http:// URLs must set ALLOW_INSECURE_HTTP=true after TLS enforcement is added — affects conftest.py

### Anti-Patterns
- Setting `self.api_key` in dual-key mode where it's never used — creates a vestigial attribute
- `defaultdict(deque)` for per-caller rate limiting without cleanup — empty deques accumulate; acceptable for few callers but won't scale

## Phase 6 — Log Integrity & Export (2026-05-08)

### Patterns
- `IntegrityChainFormatter` subclasses `StructuredJsonFormatter` — adds retention_class and integrity_hmac fields without changing the base JSON format
- HMAC chain: `hmac(key, f"{previous_hmac}|{json_without_hmac}").hexdigest()` — compute HMAC over data *before* adding the HMAC field to avoid circular dependency
- `WatchedFileHandler` for audit log files — compatible with external logrotate (re-opens file on inode change)
- `SessionCounter` as a simple module-level singleton — appropriate for single-event-loop asyncio context
- Separate `IntegrityChainFormatter` instances for stderr and file handlers — each produces an independently verifiable chain

### Learnings
- When verifying HMAC chain: `pop("integrity_hmac")` from parsed JSON, recompute, compare — the pop pattern correctly mirrors the computation order
- `secrets.token_bytes(32)` as default HMAC key provides security within a single server session but doesn't allow cross-restart verification. `AUDIT_HMAC_KEY` env var enables persistent verification.
- Every new secret env var must be added to `RedactingFilter._SECRET_ENV_VARS` — SB-02 caught AUDIT_HMAC_KEY missing
- `_RETENTION_MAP` dict lookup with `.get(event_type, "debug")` default ensures every log entry gets a retention_class even for unknown event types

### Anti-Patterns
- Docstring removal during module rewrite — even in a "minimal comments" project, security infrastructure benefits from brief class-level docstrings

## Container Deployment (2026-05-09)

### Dockerfile Fixes
- `pyproject.toml` references README.md in build backend — COPY must include it or `uv sync` fails
- `uv sync` creates root-owned caches in /tmp and /root — must `rm -rf /tmp/uv-cache /root/.cache/uv` before switching to non-root USER
- `ENV UV_NO_CACHE=1` prevents runtime cache writes (deps already installed during build)
- `--no-sync` on `uv run` entrypoint prevents runtime dependency sync attempts that fail as non-root

### TLS Deployment
- Two legs in MCP communication chain: (1) MCP server → DefectDojo backend, (2) Claude Code → MCP server
- Both legs secured via existing Caddy reverse proxy on proxy-01 with Cloudflare DNS-01 wildcard TLS
- `flush_interval -1` required on Caddy route for SSE/streaming support
- `local=/internal.homelab.equipment/` in dnsmasq blocks upstream DNS forwarding — Caddy-proxied subdomains need explicit `address=` directives in dnsmasq config to resolve locally

### Anti-Patterns
- Running `uv run` without `--no-sync` in containers where the user lacks write permissions to the cache directory

## Post-TLS Audit Remediation (2026-05-09)

### Results
- Post-TLS 12-dimension audit: 0 critical, 0 high, 2 medium, 5 low, 7 info
- All 7 actionable findings remediated in 2 commits (`c215f7e`, `dc3daa5`)
- Zero open findings remaining

### Learnings
- `pip-audit` added as dev dependency and CI step — catches CVEs in transitive deps before shipping
- `_TRUNCATE_FIELDS` must include `title` alongside `description` — finding titles can contain sensitive system identifiers and vulnerability names
- Docker base image SHA256 digest pinning prevents silent image mutation between builds — use `@sha256:...` suffix on FROM line
- CI matrix with multiple Python versions (3.12, 3.13) catches forward-compatibility regressions at zero runtime cost
- CHANGELOG.md is required for operator usability in regulated environments — version history should not live only in git
- `uv` version pinning in CI (e.g., `version: "0.7"`) prevents surprise build breakage from upstream releases

## Technology Notes
- FastMCP: supports SSE, streamable-http, and stdio transports; lifespan context for resource management; built-in AuthMiddleware and per-tool auth
- httpx: requires explicit `aclose()` or use as async context manager; default timeout is 5s
- tenacity: retry decorator; use `retry_if_exception_type` for targeted retries on 5xx/timeout
- pytest-asyncio: `asyncio_mode = "auto"` eliminates need for `@pytest.mark.asyncio` on every test
- respx: httpx-native mocking; use `@respx.mock` decorator per test, NOT as a shared fixture (incompatible with fixture-scoped httpx clients)

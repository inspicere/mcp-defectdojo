# Project Audit — mcp-defectdojo

**Audit date:** 2026-05-09
**Domain overlays applied:** service-api, application (Python)
**Components reviewed:**
- Source: `server.py` (384 lines), `client.py` (184), `audit_logging.py` (252), `security.py` (41), `models.py` (52)
- Tests: 7 files, 2029 lines, 182 tests
- Config: `pyproject.toml`, `Dockerfile`, `.gitignore`
- No CI/CD config, no README, no .env.example

**Dimensions covered:** all 12

## Executive summary

mcp-defectdojo is a FastMCP server that proxies 14 tools to a DefectDojo vulnerability management API. It is deployed in an NCUA-regulated financial services environment on a homelab network. The codebase is small (914 lines of source), well-tested (182 tests, ~95% line coverage), and has already been through two rounds of TITAN audit (v1.0 D+, v2.0 B). Security posture is good for internal deployment: TLS enforced, per-tool scope auth, rate limiting, HMAC-chain audit log, structured JSON logging with secret redaction. The most significant remaining risks are operational: no documentation for operators, no CI pipeline, and full request payloads (including vulnerability descriptions) logged at INFO level. Overall risk posture: **Moderate** — appropriate for a homelab deployment, needs documentation and CI before broader exposure.

## Findings summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 2 |
| Medium | 6 |
| Low | 8 |
| Info | 5 |

## Findings by dimension

### 1. Security

**[Medium] SSRF — private/loopback IP addresses not blocked in URL validation**
- **Location:** `client.py:45-58`
- **Observation:** URL validation checks scheme, hostname presence, embedded credentials, and TLS. Does not block RFC 1918, loopback (127.0.0.0/8), link-local (169.254.0.0/16), or IPv6 loopback.
- **Risk:** An operator who sets `DEFECTDOJO_URL=https://169.254.169.254` could use the server to reach cloud metadata endpoints. Requires operator-level access to the env var, but defense-in-depth expects the application to reject known-bad targets.
- **Recommendation:** Add hostname validation against private ranges, or document as accepted risk for internal-only deployment.

**[Medium] No startup warning when auth disabled on network transport (partially addressed)**
- **Location:** `server.py:63-69`
- **Observation:** The recent audit fix added a CRITICAL log when `MCP_AUTH_TOKEN` is absent and transport is `sse`/`http`. However, `FASTMCP_TRANSPORT` is only read from env in `lifespan()` — if the transport is set via the `mcp.run()` call directly, the check won't fire.
- **Risk:** An operator could run the server on SSE transport without auth and see no warning if transport was set programmatically.
- **Recommendation:** Acceptable for current deployment (transport is always set via env var). Document the deployment requirement.

**[Low] TLS certificate verification relies on httpx default**
- **Location:** `client.py:19-23`
- **Observation:** `httpx.AsyncClient()` created without explicit `verify=True`. httpx defaults to True, but this is implicit.
- **Risk:** A future httpx version or environment-level configuration could change this behavior.
- **Recommendation:** Add `verify=True` explicitly.

**[Low] Token comparison timing safety unverified in FastMCP**
- **Location:** `server.py:37-46` (via FastMCP StaticTokenVerifier)
- **Observation:** Auth tokens are stored as dict keys in `StaticTokenVerifier`. Dict lookup is a hash comparison, not `hmac.compare_digest()`. In theory this creates a timing oracle, but in practice dict hash lookups have constant time for the comparison step.
- **Risk:** Theoretical. Dict hash comparison does not leak byte-by-byte information like string `==` would.
- **Recommendation:** Track upstream; no action required.

**[Info] `self.api_key` set but unused in dual-key mode**
- **Location:** `client.py:37`
- **Observation:** In dual-key mode, `self.api_key = write_key` is set but never read — the actual keys are embedded in the httpx client headers during construction.
- **Risk:** None — vestigial attribute, not a security issue.
- **Recommendation:** Remove in future cleanup.

### 2. Reliability & failure modes

**[Low] No circuit breaker for DefectDojo upstream**
- **Location:** `client.py:84-107`
- **Observation:** Every tool call makes a direct HTTP request to DefectDojo. If DefectDojo is slow or down, all tool calls block until the 30s timeout.
- **Risk:** A degraded DefectDojo instance causes MCP tool latency to spike to 30s per call. No backpressure or fast-fail.
- **Recommendation:** Acceptable for current low-volume deployment. Add circuit breaker if request volume increases.

**[Low] MutationRateLimiter never evicts empty deques**
- **Location:** `security.py:24,30-33`
- **Observation:** After a caller's sliding window expires, the deque is drained but the key persists in `_windows`. With many unique caller IDs, the dict grows without bound.
- **Risk:** Negligible for current deployment (few callers). Would matter in multi-tenant SSE deployment.
- **Recommendation:** Add `if not window: del self._windows[caller_id]; return` after the drain loop.

**[Info] Graceful shutdown implemented correctly**
- **Location:** `server.py:70-76`
- **Observation:** `lifespan()` finally block emits session summary, then closes the httpx client and nullifies the reference. Correct pattern.

### 3. Performance & overhead

**[Info] Performance characteristics are appropriate for workload**
- **Observation:** Async throughout, httpx connection pooling with 30s timeout and 5s connect timeout, no N+1 patterns, no O(n²) loops. The `inspect.signature()` caching and IntegrityChainFormatter `_build_data()` refactoring from the pre-ship audit resolved the two main performance issues. RedactingFilter now caches secrets at init time. Performance is not a concern for this workload.

### 4. Privacy & data handling

**[High] Full finding descriptions logged in audit records**
- **Location:** `audit_logging.py:165-182`
- **Observation:** `request_params` includes every argument except `ctx`. For `create_finding` and `update_finding`, this includes the full `description` field (up to 10,000 characters). Security finding descriptions may contain PII (reporter names, employee IDs), sensitive infrastructure details, or proprietary vulnerability data.
- **Risk:** In an NCUA-regulated environment, audit logs may be subject to discovery or examination review. Logging full vulnerability descriptions creates a second copy of sensitive data outside the DefectDojo access control boundary. This data is also subject to the audit log's retention policy, which may differ from DefectDojo's.
- **Recommendation:** Truncate `description` in `request_params` to a character count summary (e.g., `"<2847 chars>"`). Log `title`, `severity`, `test_id`, `finding_id` — the control metadata — in full.

**[Low] Session summary includes tool call counts**
- **Location:** `audit_logging.py:129-135`
- **Observation:** `requests_by_tool` in the session summary reveals which tools were called and how many times. This is operational data, not PII, but in a regulatory context it could reveal investigation patterns.
- **Risk:** Low — operational metadata, no PII.
- **Recommendation:** Acceptable. Document in operator guide.

### 5. Configuration robustness

**[Medium] No .env.example documenting all configuration variables**
- **Location:** Project root
- **Observation:** The project uses 11 env vars (`DEFECTDOJO_URL`, `DEFECTDOJO_API_KEY`, `DEFECTDOJO_READ_API_KEY`, `DEFECTDOJO_WRITE_API_KEY`, `MCP_AUTH_TOKEN`, `MCP_READ_TOKEN`, `ALLOW_INSECURE_HTTP`, `AUDIT_HMAC_KEY`, `AUDIT_LOG_FILE`, `LOG_LEVEL`, `FASTMCP_TRANSPORT`, `FASTMCP_HOST`, `FASTMCP_PORT`, `MUTATION_RATE_LIMIT`, `MUTATION_RATE_WINDOW`). None are documented in a `.env.example` or README.
- **Risk:** Operators must read source code to discover configuration options. In a regulated environment, undocumented configuration is an examination finding.
- **Recommendation:** Create `.env.example` with all variables, their types, defaults, and whether they're required or optional.

**[Medium] Mutation rate limiter reads env vars at module scope before lifespan**
- **Location:** `server.py:84-87`
- **Observation:** `_mutation_limiter = MutationRateLimiter(max_mutations=int(os.environ.get(...)))` executes at import time. `load_dotenv()` is called in `_build_auth()` (line 35) and `lifespan()` (line 61). The ordering works because `_build_auth()` is called at module scope (line 79), before the limiter construction. But this is fragile — reordering the module-level statements could silently break rate limit configuration.
- **Risk:** Medium — implicit dependency on statement ordering. If someone moves `_build_auth()` below the limiter, env vars won't be loaded.
- **Recommendation:** Acceptable given single-file module. Document the ordering dependency in a comment.

**[Info] Sensible defaults throughout**
- **Observation:** LOG_LEVEL defaults to INFO, MUTATION_RATE_LIMIT defaults to 60/60s, TLS required by default, auth open-by-default (correct for stdio transport). All defaults are safe.

### 6. Observability & logging

**[Info] Comprehensive structured logging infrastructure**
- **Observation:** Structured JSON output via StructuredJsonFormatter, HMAC integrity chain, per-tool audit records with correlation ID, caller identity, duration, outcome. Secret redaction covers all 6 env var secrets plus Token header patterns. Retention metadata classifies entries for downstream policy. WatchedFileHandler for logrotate compatibility. Session summary on shutdown. This dimension is the strongest part of the project — well above average for a tool of this size.

**[Low] No metrics emission (RED signals)**
- **Location:** Project-wide
- **Observation:** The server emits structured logs but no Prometheus/StatsD/OTEL metrics. Rate, errors, and duration are available in log records but not in a metrics-native format.
- **Risk:** Low for current deployment (single-instance homelab). Would matter for production alerting.
- **Recommendation:** Accept for v2.0. Consider OTEL integration in a future milestone.

### 7. Compatibility & versioning

**[Medium] `pyproject.toml` version is `0.1.0` despite shipping as v2.0.0**
- **Location:** `pyproject.toml:3`
- **Observation:** `version = "0.1.0"` while the git tag is `v2.0.0`. The package version and release version are divergent.
- **Risk:** If the package is ever installed from PyPI or a local registry, the version reported by `pip show` will be wrong.
- **Recommendation:** Update to `version = "2.0.0"` to match the release tag.

**[Low] `requires-python = ">=3.12"` — no upper bound**
- **Location:** `pyproject.toml:9`
- **Observation:** No upper bound on Python version. Unlikely to be an issue in practice.
- **Risk:** A future Python release with breaking changes would not be caught by version specifier.
- **Recommendation:** Acceptable. Test against new Python releases as they come.

### 8. Documentation

**[High] No README, no operator documentation, no configuration reference**
- **Location:** Project root
- **Observation:** The project has no README.md (beyond pyproject.toml's placeholder `readme = "README.md"`), no operator runbook, no architecture overview, no configuration reference, no deployment guide. The only documentation is in `.titan/` (internal development framework), CLAUDE.md (AI assistant instructions), and tool docstrings.
- **Risk:** In an NCUA-regulated environment, undocumented systems are an examination finding. No operator can deploy, configure, or troubleshoot this system without reading source code. The threat model (what's trusted, what's not, what auth is required when) is not documented anywhere except code.
- **Recommendation:** Create: (1) README.md with project purpose, prerequisites, install, configuration reference; (2) a deployment section covering Docker, env vars, auth setup; (3) a security model section covering auth, TLS, rate limiting, audit logging.

**[Medium] Tool docstrings are functional but terse**
- **Location:** `server.py` tool functions
- **Observation:** Each tool has a one-line docstring describing args and return format. These are adequate for LLM consumers. They don't document error conditions, auth requirements, or side effects.
- **Risk:** An LLM consumer won't know that `create_finding` requires write scope, or what error message to expect for rate limiting.
- **Recommendation:** Add auth scope requirement and rate limit information to write tool docstrings.

### 9. Testability & test coverage

**[Medium] No CI pipeline**
- **Location:** Project root (no `.github/workflows/`, no `.forgejo/workflows/`)
- **Observation:** 182 tests exist but run only locally. No CI automation, no PR gating, no automated test on push.
- **Risk:** Regressions can be introduced without detection. Tests are only as useful as the frequency with which they're run.
- **Recommendation:** Add a Forgejo Actions workflow that runs `uv run pytest` on push.

**[Low] PytestCollectionWarning on every test run**
- **Location:** `models.py:26`
- **Observation:** `TestSummary` class name triggers pytest collection warning. Cosmetic but noisy.
- **Risk:** Noise obscures real warnings.
- **Recommendation:** Rename to `DDTestSummary` or add `__test__ = False` class attribute.

**[Info] Test quality is high**
- **Observation:** Tests use respx for HTTP mocking (high fidelity), AsyncMock for server-layer isolation, parametrized error tests for coverage breadth, and dedicated test files per feature area. Coverage is ~95% line coverage. Happy paths, error paths, boundary conditions, and security scenarios are all tested.

### 10. Dependency & supply chain

**[Low] Dockerfile base image not pinned by SHA digest**
- **Location:** `Dockerfile:1`
- **Observation:** `FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim` uses a mutable tag. The image could change between builds.
- **Risk:** Low — `uv.lock` pins all Python dependencies with hashes, so the application code is reproducible. The OS layer could drift.
- **Recommendation:** Pin by digest for production builds.

**[Info] Supply chain posture is good**
- **Observation:** `uv sync --frozen` in Dockerfile ensures lockfile is respected. `uv.lock` pins all dependencies with integrity hashes. `pip-audit` clean (0 CVEs). 5 direct dependencies, all well-maintained (FastMCP, httpx, mcp, pydantic, python-dotenv). No `setup.py` (uses PEP 621 `pyproject.toml` with uv build backend). Authlib deprecation warning in FastMCP is tracked.

### 11. Data integrity

**[Info] HMAC integrity chain correctly implemented**
- **Observation:** Each log entry includes an HMAC-SHA256 computed over the previous entry's HMAC concatenated with the current entry's JSON. Tamper detection tested. Retention metadata attached. Two independent chains (stderr, file) using the same key. `AUDIT_HMAC_KEY` missing now produces a CRITICAL warning. The chain is correct within a session; cross-restart verification requires the persistent key.

**[Low] `found_by: [1]` hardcoded in create_finding**
- **Location:** `client.py:179`
- **Observation:** Assumes test type ID 1 exists on the target DefectDojo instance. No validation, no configurability.
- **Risk:** Silently attributes findings to the wrong scanner on instances where ID 1 is different.
- **Recommendation:** Make configurable via env var or expose as optional tool parameter.

### 12. Usability

**[Medium] No `.env.example` or quickstart**
- **Location:** Project root
- **Observation:** A new operator cannot determine what env vars to set without reading source code. No quickstart guide, no example configuration.
- **Risk:** First-run experience is poor. Operator will get `ValueError` without guidance on what to fix.
- **Recommendation:** Create `.env.example` and add quickstart section to README.

**[Low] `pyproject.toml` description is placeholder**
- **Location:** `pyproject.toml:4`
- **Observation:** `description = "Add your description here"` — default scaffold text.
- **Risk:** Cosmetic, but visible if the package is ever published or inspected.
- **Recommendation:** Update to "MCP server for DefectDojo vulnerability management".

**[Info] Error messages are clear and actionable**
- **Observation:** ToolError messages include the field name, expected range, and actual value. Validation errors reference the specific field. Rate limit errors suggest retrying. This is good LLM-consumer ergonomics.

## Cross-cutting issues

**[Medium] Configuration surface is undocumented and spread across three files**
- `server.py` reads: `FASTMCP_TRANSPORT`, `FASTMCP_HOST`, `FASTMCP_PORT`, `MCP_AUTH_TOKEN`, `MCP_READ_TOKEN`, `MUTATION_RATE_LIMIT`, `MUTATION_RATE_WINDOW`
- `client.py` reads: `DEFECTDOJO_URL`, `DEFECTDOJO_API_KEY`, `DEFECTDOJO_READ_API_KEY`, `DEFECTDOJO_WRITE_API_KEY`, `ALLOW_INSECURE_HTTP`
- `audit_logging.py` reads: `LOG_LEVEL`, `AUDIT_HMAC_KEY`, `AUDIT_LOG_FILE`
- No single reference document lists all 14 variables, their types, defaults, and interactions.

**[Low] Module-level `load_dotenv()` ordering**
- `_build_auth()` calls `load_dotenv()` and is invoked at module scope (line 79). `_mutation_limiter` is constructed at module scope (line 84). The limiter reads env vars that were loaded by `_build_auth()`. This ordering dependency is implicit and fragile. A reorder of the module-level statements would silently break rate limit configuration.

## Recommended remediation order

1. **[High] Documentation** — Create README.md with configuration reference, security model, deployment guide, quickstart. This is the highest-impact improvement for operator usability and regulatory compliance. (~1 hour)

2. **[High] Privacy — truncate descriptions in audit logs** — Change `request_params` construction in `audit_tool` to truncate `description` fields. Prevents sensitive vulnerability data from being duplicated in audit logs. (~15 minutes)

3. **[Medium] Configuration — create .env.example** — Document all 14 env vars with types, defaults, and descriptions. (~30 minutes)

4. **[Medium] Compatibility — update pyproject.toml version** — Change `0.1.0` to `2.0.0`. (~1 minute)

5. **[Medium] CI — add Forgejo Actions workflow** — Run tests on push to catch regressions. (~15 minutes)

6. **[Medium] Tool docstrings** — Add auth scope and rate limit info to write tool docs. (~15 minutes)

7. **[Low] Remaining items** — TLS verify=True, TestSummary rename, found_by configurability, pyproject description, image digest pinning. Track in backlog.

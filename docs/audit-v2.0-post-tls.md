# Project Audit — mcp-defectdojo

**Audit date:** 2026-05-09
**Domain overlays applied:** service-api, infrastructure, application (Python)
**Components reviewed:**
- `src/mcp_defectdojo/server.py` — MCP tool definitions, auth, lifespan
- `src/mcp_defectdojo/client.py` — httpx-based DefectDojo API client
- `src/mcp_defectdojo/audit_logging.py` — structured JSON logging, HMAC integrity chain, redaction
- `src/mcp_defectdojo/models.py` — Pydantic response models
- `src/mcp_defectdojo/security.py` — rate limiter, field validation
- `src/mcp_defectdojo/__init__.py` — empty
- `Dockerfile` — production container image
- `.forgejo/workflows/test.yml` — CI pipeline
- `pyproject.toml` — build config and dependencies
- `README.md` — project documentation
- `.env.example` — configuration template
- `.gitignore`, `LICENSE`, `uv.lock`
- 7 test files (182 tests, 96% coverage)

**Dimensions covered:** all 12

## Executive summary

mcp-defectdojo is a well-structured MCP server that proxies DefectDojo's REST API through 14 tools with per-tool scope enforcement, mutation rate limiting, TLS enforcement, and HMAC-chained audit logging. After the v2.0 hardening phases and the TLS deployment completed this session, the project has no critical or high findings. The remaining items are low-severity improvements: a README typo, missing vulnerability scanning in CI, and minor Docker image hygiene. Overall risk posture: **Low**.

## Findings summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 0 |
| Medium | 2 |
| Low | 5 |
| Info | 7 |

## Findings by dimension

### 1. Security

**[Info] Auth disabled when no MCP_AUTH_TOKEN is set**
- **Location:** `src/mcp_defectdojo/server.py:26-30`
- **Observation:** `scope_check` returns `True` when `ctx.token is None`, granting full access when no auth token is configured.
- **Risk:** By design — the server logs a CRITICAL warning on startup when auth is disabled on a network transport (line 65-69). Internal homelab deployment currently runs without auth.
- **Recommendation:** No code change needed. Setting `MCP_AUTH_TOKEN` in the docker-compose environment on mcp-01 would close this gap when ready.

**[Info] Connection error messages may include internal URLs**
- **Location:** `src/mcp_defectdojo/client.py:107`
- **Observation:** `raise RuntimeError(f"Failed to connect to DefectDojo: {e}")` passes the full httpx exception. In test (`test_request_connect_error_no_url_leak`), the mock uses a string-only ConnectError, but real httpx errors may embed the URL.
- **Risk:** Low — the URL points to an internal DefectDojo instance, and the error surfaces only to authenticated MCP callers. No external exposure.
- **Recommendation:** No change needed for internal use. If the server were exposed externally, sanitize `str(e)` to remove URL components.

### 2. Reliability & failure modes

**[Info] No retry logic on API calls**
- **Location:** `src/mcp_defectdojo/client.py:84-107`
- **Observation:** Each API call makes a single attempt. Transient failures (network blip, DefectDojo restart) surface immediately to the caller.
- **Risk:** Acceptable for a read-through proxy — the MCP client can retry at a higher level. Adding retries here could mask upstream issues.
- **Recommendation:** No change needed. If transient failures become an operational issue, add retries on idempotent (GET) requests only.

**[Info] Rate limiter windows not pruned for idle callers**
- **Location:** `src/mcp_defectdojo/security.py:24`
- **Observation:** `_windows` dict grows one deque per unique `caller_id`, never pruned. Expired timestamps within each deque are cleared, but empty deques persist.
- **Risk:** Negligible — in practice, there are 1-2 callers. No memory concern.
- **Recommendation:** No change needed.

### 3. Performance & overhead

No issues observed. The server is a thin proxy with Pydantic validation. Structured logging adds minimal overhead. The asyncio lock on the rate limiter serializes only write-path checks.

### 4. Privacy & data handling

**[Medium] Finding titles logged verbatim in audit records**
- **Location:** `src/mcp_defectdojo/audit_logging.py:175-183`
- **Observation:** `_TRUNCATE_FIELDS` only includes `description`. The `title` parameter of `create_finding` and `update_finding` is logged in full within `request_params`.
- **Risk:** Finding titles may contain vulnerability names, system identifiers, or other operationally sensitive information. In a regulated environment, audit logs shipped to a SIEM could expose this data more broadly than intended.
- **Recommendation:** Add `"title"` to `_TRUNCATE_FIELDS`, or apply a shorter length cap (e.g., first 50 chars).

### 5. Configuration robustness

**[Low] README quickstart references wrong filename**
- **Location:** `README.md:17`
- **Observation:** Quickstart says `cp env.example .env` but the file is `.env.example`.
- **Risk:** First-time setup fails with "file not found."
- **Recommendation:** Change to `cp .env.example .env`.

### 6. Observability & logging

No issues observed. Structured JSON logging with correlation IDs, retention class tagging, HMAC integrity chain, configurable log level, secret redaction, and optional file export are all implemented and tested.

### 7. Compatibility & versioning

**[Low] CI tests only one Python version**
- **Location:** `.forgejo/workflows/test.yml`
- **Observation:** The test job runs on `ubuntu-latest` with `uv` installing the default Python. No matrix testing against Python 3.12 and 3.13.
- **Risk:** A Python 3.13 regression or deprecation could ship undetected. Low probability given the minimal stdlib surface.
- **Recommendation:** Add a `strategy.matrix` with `python-version: ["3.12", "3.13"]` if the Forgejo runner supports it.

**[Low] No CHANGELOG**
- **Location:** project root
- **Observation:** No CHANGELOG.md or release notes file. Version history exists only in git.
- **Risk:** Users and operators can't quickly assess what changed between versions.
- **Recommendation:** Create `CHANGELOG.md` with at least the v2.0.0 entry.

### 8. Documentation

**[Low] Quickstart env file path incorrect**
- **Location:** `README.md:17`
- **Observation:** Same as finding 5.1.
- **Risk:** Same as above.
- **Recommendation:** Same as above.

### 9. Testability & test coverage

**[Info] All tests use mocks — no integration tests**
- **Location:** `tests/`
- **Observation:** All 182 tests mock the DefectDojo API via `respx` or `AsyncMock`. No tests hit a real DefectDojo instance.
- **Risk:** Contract drift between the mock and real DefectDojo API could cause runtime failures. Low probability given the stable DefectDojo v2 API.
- **Recommendation:** No change needed. If the test environment gains a DefectDojo instance, add a small integration test suite gated by `@pytest.mark.integration`.

**[Low] CI uses `version: "latest"` for uv**
- **Location:** `.forgejo/workflows/test.yml:14`
- **Observation:** `version: "latest"` means CI installs whatever uv version is current. A breaking uv release could fail CI unexpectedly.
- **Risk:** Build instability, though uv is generally backward-compatible.
- **Recommendation:** Pin to a specific uv version (e.g., `version: "0.7"`).

### 10. Dependency & supply chain

**[Medium] No automated vulnerability scanning**
- **Location:** `.forgejo/workflows/test.yml`, `pyproject.toml`
- **Observation:** No `pip-audit`, `safety`, or equivalent vulnerability scanner in CI. The project depends on `httpx`, `pydantic`, `fastmcp`, and their transitive deps (71 packages total in the container).
- **Risk:** A known CVE in a transitive dependency would not be detected until manual review. For an NCUA-regulated environment, automated scanning is expected.
- **Recommendation:** Add a CI step: `uv run pip-audit --require-hashes -r requirements.txt` or equivalent. Add `pip-audit` to dev dependencies.

**[Info] Docker base image not pinned by digest**
- **Location:** `Dockerfile:1`
- **Observation:** `FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim` uses a tag, not a digest. The tag is mutable — a push to the same tag changes the base image silently.
- **Risk:** Low for a homelab deployment. In a regulated environment, digest pinning ensures reproducibility.
- **Recommendation:** Pin by digest: `FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:<digest>`.

### 11. Data integrity

**[Info] HMAC chain formatter state is not thread-safe**
- **Location:** `src/mcp_defectdojo/audit_logging.py:62-77`
- **Observation:** `IntegrityChainFormatter._previous_hmac` is instance state mutated on each `format()` call without locking.
- **Risk:** None in practice — Python's asyncio event loop is single-threaded, and logging formatters are called synchronously within the event loop. No concurrent mutation is possible.
- **Recommendation:** No change needed.

### 12. Usability

No issues observed. Docker deployment is documented and working. `.env.example` provides a complete template. Error messages are specific and actionable (ToolError with field names, validation ranges, severity options). Health check tool enables quick connectivity verification.

## Cross-cutting issues

**[Info] `_TRUNCATE_FIELDS` frozenset recreated per invocation**
- **Location:** `src/mcp_defectdojo/audit_logging.py:175`
- **Observation:** The frozenset `{"description"}` is defined inside the `wrapper` function of `audit_tool`, so it's reconstructed on every tool call.
- **Risk:** No functional impact. Negligible performance overhead (frozenset construction is fast).
- **Recommendation:** Move to module level if cleaning up in a future pass.

## Recommended remediation order

1. **[Medium] Add vulnerability scanning to CI** (dimension 10) — highest regulatory exposure. Add `pip-audit` as a dev dependency and a CI step. Prevents shipping known-vulnerable transitive deps.
2. **[Medium] Add `title` to audit log truncation** (dimension 4) — quick one-line fix. Limits sensitive data in audit logs.
3. **[Low] Fix README quickstart path** (dimension 5/8) — `cp env.example .env` → `cp .env.example .env`. User-facing and easy.
4. **[Low] Pin uv version in CI** (dimension 9) — prevents surprise CI breakage.
5. **[Low] Add Python 3.13 to CI matrix** (dimension 7) — forward-compatibility assurance.
6. **[Low] Add CHANGELOG.md** (dimension 7) — operational hygiene.
7. **[Low] Pin Docker base image by digest** (dimension 10) — reproducibility.

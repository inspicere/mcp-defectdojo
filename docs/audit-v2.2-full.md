# Project Audit — mcp-defectdojo

**Audit date:** 2026-05-10
**Version audited:** v2.2.0 (post bug-fix commits `ef932f7`, `b9b1e8d`)
**Remediation complete:** 2026-05-10 (v2.2.1) — all 6 actionable findings resolved
**Domain overlays applied:** service-api, infrastructure, application (Python)
**Components reviewed:**
- `src/mcp_defectdojo/server.py` — MCP tool definitions (23 tools), auth, lifespan
- `src/mcp_defectdojo/client.py` — httpx-based DefectDojo API client, error sanitization, multipart upload
- `src/mcp_defectdojo/audit_logging.py` — structured JSON logging, HMAC integrity chain, redaction, SIEM forwarding
- `src/mcp_defectdojo/models.py` — Pydantic response models (ImportScanResult, FindingNote, etc.)
- `src/mcp_defectdojo/security.py` — rate limiter, field validation
- `src/mcp_defectdojo/siem.py` — syslog and HTTPS log forwarding
- `src/mcp_defectdojo/__init__.py` — empty
- `Dockerfile` — production container image (pinned by digest)
- `.forgejo/workflows/test.yml` — CI test pipeline (Python 3.12+3.13 matrix)
- `.forgejo/workflows/security.yml` — CI security scanning (Semgrep, Trivy, Gitleaks)
- `pyproject.toml` — build config and dependencies
- `README.md` — project documentation
- `.env.example` — configuration template
- `.gitignore`, `LICENSE`, `uv.lock`
- `CHANGELOG.md` — version history
- 12 test files (302 tests, ~95% coverage)

**Dimensions covered:** all 12

## Executive summary

mcp-defectdojo v2.2.0 is a well-structured MCP server with 23 tools covering DefectDojo CRUD, scan import/reimport, finding lifecycle management, and metadata queries. Security posture includes per-tool scope enforcement, mutation rate limiting, TLS enforcement, HMAC-chained audit logging, SIEM forwarding, error sanitization, and secret redaction. The previous audit (v2.0 post-TLS, 2026-05-09) identified 2 medium, 5 low, and 7 info findings — all remediated.

This v2.2 audit covers the 9 new tools, 96 new tests, CI/CD workflow changes, and full re-evaluation of all 12 dimensions. Overall risk posture: **Low**. One medium finding relates to CI infrastructure (TLS verification disabled for DefectDojo uploads), not application code.

## Findings summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 0 |
| Medium | 1 |
| Low | 5 |
| Info | 6 |

## Prior audit findings — status

All findings from the v2.0 post-TLS audit (2026-05-09) have been verified as resolved:

| Finding | Status | Resolution |
|---------|--------|------------|
| [Medium] No automated vulnerability scanning | Resolved | `pip-audit` added to CI (commit `c215f7e`) |
| [Medium] Finding titles logged verbatim | Resolved | `title` added to `_TRUNCATE_FIELDS` (commit `c215f7e`) |
| [Low] README quickstart wrong filename | Resolved | Fixed to `cp .env.example .env` (commit `c215f7e`) |
| [Low] CI uses `version: "latest"` for uv | Resolved | Pinned to specific version (commit `c215f7e`) |
| [Low] CI tests one Python version | Resolved | Python 3.12+3.13 matrix added (commit `dc3daa5`) |
| [Low] No CHANGELOG | Resolved | `CHANGELOG.md` created (commit `dc3daa5`) |
| [Low] Docker base image not pinned by digest | Resolved | Pinned by sha256 digest (commit `dc3daa5`) |

## Findings by dimension

### 1. Security

**[Medium] CI security workflow disables TLS certificate verification for DefectDojo API uploads**
- **Location:** `.forgejo/workflows/security.yml` (curl upload steps)
- **Observation:** The CI security workflow uses `curl -sk` when uploading Semgrep, Trivy, and Gitleaks scan results to `https://defectdojo.example.internal`. The `-k` flag disables TLS certificate verification.
- **Risk:** The `DD_API_TOKEN` is transmitted in an `Authorization` header over a connection that does not verify server identity. An attacker with network access between the CI runner and DefectDojo could MITM the connection and capture the API token. Medium severity because it requires network-level access within the homelab.
- **Recommendation:** Add the internal CA certificate to the CI container trust store and remove `-k`, or pass `--cacert /path/to/ca.pem` to curl.

**[Info] Auth disabled when no MCP_AUTH_TOKEN is set**
- **Location:** `src/mcp_defectdojo/server.py`
- **Observation:** `scope_check` returns `True` when `ctx.token is None`, granting full access. The server logs a CRITICAL warning on startup when auth is disabled on a network transport.
- **Risk:** By design for internal homelab. Setting `MCP_AUTH_TOKEN` closes this gap.
- **Recommendation:** No code change needed.

### 2. Reliability & failure modes

**[Low] `close_finding` performs non-atomic two-step operation**
- **Location:** `src/mcp_defectdojo/server.py` (`close_finding` tool)
- **Observation:** `close_finding` first closes the finding (PATCH), then optionally adds a note (POST). If the close succeeds but the note fails, the finding is closed without the reason note. The response does not indicate partial success.
- **Risk:** Low — the finding is still correctly closed. The missing note is an inconvenience, not a data integrity issue.
- **Recommendation:** Wrap the two operations and return a response indicating partial success if the note fails.

**[Low] `health_check` could surface raw exception details**
- **Location:** `src/mcp_defectdojo/server.py` (`health_check` tool)
- **Observation:** The `health_check` tool catches `Exception` and returns `f"Error: {e}"`. While `_sanitize_api_error()` handles HTTP errors, unexpected exception types (e.g., SSL errors, DNS failures) could surface raw error details including internal hostnames.
- **Risk:** Low — `health_check` is a read-only diagnostic tool, and the information surfaces only to authenticated MCP callers.
- **Recommendation:** Sanitize the exception message to remove URLs and hostnames before returning.

**[Info] No retry logic on API calls**
- **Location:** `src/mcp_defectdojo/client.py`
- **Observation:** Each API call makes a single attempt. Acceptable for a read-through proxy.
- **Recommendation:** No change needed.

### 3. Performance & overhead

No issues observed.

### 4. Privacy & data handling

**[Info] `_TRUNCATE_FIELDS` frozenset recreated per invocation**
- **Location:** `src/mcp_defectdojo/audit_logging.py`
- **Observation:** The frozenset `{"description", "title"}` is defined inside the `wrapper` function. Negligible performance impact.
- **Recommendation:** Move to module level if cleaning up in a future pass.

### 5. Configuration robustness

**[Low] `HTTPSLogHandler` accepts `http://` scheme for audit log forwarding**
- **Location:** `src/mcp_defectdojo/audit_logging.py` (`HTTPSLogHandler.__init__`)
- **Observation:** The handler validates that the URL scheme is `http` or `https`, but does not warn or reject `http://`. Audit logs containing HMAC chains, caller identities, and request parameters could be transmitted in cleartext.
- **Risk:** Low — the handler name implies HTTPS-only, and the configuration variable is `AUDIT_LOG_HTTPS_URL`. An operator choosing `http://` is making a deliberate (if inadvisable) choice.
- **Recommendation:** Log a WARNING when `http://` is used, or restrict to `https://` only.

### 6. Observability & logging

No issues observed. Structured JSON logging, correlation IDs, retention class tagging, HMAC integrity chain, secret redaction, SIEM forwarding (syslog + HTTPS), and session summary are all implemented and tested.

### 7. Compatibility & versioning

No issues observed. CI tests Python 3.12 and 3.13. CHANGELOG.md is current.

### 8. Documentation

No issues observed. README accurately reflects 23 tools, security model, SIEM integration, and deployment options.

### 9. Testability & test coverage

**[Info] All tests use mocks — no integration tests**
- **Location:** `tests/`
- **Observation:** All 302 tests mock the DefectDojo API. No tests hit a real instance. Low risk given stable DefectDojo v2 API.
- **Recommendation:** No change needed.

**[Info] Rate limiter windows not pruned for idle callers**
- **Location:** `src/mcp_defectdojo/security.py`
- **Observation:** `_windows` dict grows one deque per unique caller_id. In practice, 1-2 callers. No memory concern.
- **Recommendation:** No change needed.

### 10. Dependency & supply chain

**[Low] Gitleaks binary downloaded in CI without SHA256 hash verification**
- **Location:** `.forgejo/workflows/security.yml` (Gitleaks download step)
- **Observation:** The Gitleaks tarball is downloaded from GitHub releases and extracted without verifying a SHA256 hash. By contrast, Trivy's download includes hash verification.
- **Risk:** Low — the download uses HTTPS from GitHub, but a compromised GitHub release could inject a malicious binary into the CI pipeline.
- **Recommendation:** Add SHA256 hash verification matching the approach used for Trivy.

**[Low] CI test workflow installs uv via `curl | sh` without integrity verification**
- **Location:** `.forgejo/workflows/test.yml` (uv install step)
- **Observation:** `curl -LsSf https://astral.sh/uv/install.sh | sh` downloads and executes a script without hash or signature verification.
- **Risk:** Low — the script is served over HTTPS from a well-known domain, but supply chain best practice is to pin by hash.
- **Recommendation:** Pin the uv installer script or use a pre-built action with version pinning.

**[Info] HMAC chain formatter state is not thread-safe**
- **Location:** `src/mcp_defectdojo/audit_logging.py`
- **Observation:** No concurrent mutation is possible in asyncio single-threaded event loop.
- **Recommendation:** No change needed.

### 11. Data integrity

No issues observed. HMAC-SHA256 chain provides tamper-evident audit records.

### 12. Usability

No issues observed. Docker deployment documented, `.env.example` complete, error messages specific and actionable.

## Recommended remediation order

1. **[Medium] Fix CI security workflow TLS verification** (dimension 1) — Add internal CA cert to CI container and remove `curl -sk`. Prevents API token exposure during scan uploads. DefectDojo finding created.
2. **[Low] Add Gitleaks SHA256 hash verification in CI** (dimension 10) — Match Trivy's hash-check pattern for supply chain integrity.
3. **[Low] Restrict HTTPSLogHandler to HTTPS-only or warn on HTTP** (dimension 5) — One-line change to log WARNING or reject `http://` scheme.
4. **[Low] Handle close_finding partial success** (dimension 2) — Return response indicating if note attachment failed after successful close.
5. **[Low] Sanitize health_check error messages** (dimension 2) — Strip URLs/hostnames from unexpected exception messages.
6. **[Low] Pin uv install in CI test workflow** (dimension 10) — Add integrity verification for the uv installer script.

## Remediation status (v2.2.1 — 2026-05-10)

All 6 actionable findings resolved across Phase 7.1 (CI hardening) and Phase 7.2 (code hardening):

| # | Finding | Resolution | Phase |
|---|---------|-----------|-------|
| 1 | CI `curl -sk` TLS bypass | Removed `-k`, added `--cacert` with internal CA | 7.1 T1 |
| 2 | Gitleaks no SHA256 verification | Added hash verification matching Trivy pattern | 7.1 T2 |
| 3 | HTTPSLogHandler accepts http:// | Warns when http:// scheme configured | 7.2 T1 |
| 4 | close_finding partial success | Returns `_warning` field when note fails | 7.2 T2 |
| 5 | health_check raw exceptions | Generic response to clients, raw logged server-side | 7.2 T3 |
| 6 | uv install unverified | Pinned to v0.11.5 with version-locked URL | 7.1 T3 |

**Zero open findings remaining.** Tagged v2.2.1.

# Changelog

All notable changes to mcp-defectdojo are documented in this file.

## [3.2.6] — 2026-05-20

Phase 14.2 — deferred cleanup (QLT-01 + PERF-03 + PERF-08 + 8 minor SEC/DOM). Patch release, drains the remaining v3.2 audit-finding backlog. Tests 647 → 669 (+22). Suite runtime 52s → 18.87s (-33s, ~65% reduction). `pip-audit` carry-forward only (PYSEC-2025-183 / pyjwt 2.12.1 — disputed by supplier, not directly imported).

### Distribution (2026-05-21)

Published to PyPI and the official MCP Registry, making the server publicly installable for the first time.

- **PyPI**: https://pypi.org/project/mcp-defectdojo/3.2.6/ — `uvx mcp-defectdojo` or `pip install mcp-defectdojo`. `pyproject.toml` gained PEP 639 `license`/`license-files`, 7 keywords, 12 classifiers, and a `[project.urls]` block (Homepage / Repository / Issues / Changelog).
- **MCP Registry**: https://registry.modelcontextprotocol.io/?search=mcp-defectdojo — server name `io.github.inspicere/mcp-defectdojo@3.2.6`, package `pypi:mcp-defectdojo@3.2.6` with `runtimeHint: uvx`, transport `stdio`. New `server.json` manifest committed at project root.
- **Ownership verification**: HTML comment `<!-- mcp-name: io.github.inspicere/mcp-defectdojo -->` added to top of `README.md`; the registry verifies PyPI ownership by reading this marker from the rendered package description. Order matters — PyPI release must contain the marker BEFORE registry publish.
- **README**: new "Common Pitfalls" section (7 items, Symptom → Cause → Fix) covering the DOM-22 HMAC trap, network transport without auth, plain-HTTP local DefectDojo, the `create_product` 403 from inherited DefectDojo user permissions, mutation rate limit on bulk imports, the untrusted-content envelope, and stale `MCP_AUTH_TOKEN` after RBAC enablement.
- **Registry description cap**: 100 chars (vs. PyPI's no-cap); server.json description tightened from 161 → 84 chars in `99006ad` after first publish attempt failed with HTTP 422.
- **Tooling**: `mcp-publisher 1.7.9` installed at `/usr/local/bin/mcp-publisher` (Linux amd64, curl install — no Homebrew on Linux).
- **Credentials**: PyPI token stored in Vault at `secret/pypi` (project-scoped, named `mcp-defectdojo`, rotated immediately after first publish). Published via pipe pattern: `vault kv get -field=token secret/pypi | UV_PUBLISH_TOKEN=$(cat) uv publish`.
- **Commits**: `90b3aeb` (PyPI metadata + Common Pitfalls + server.json), `99006ad` (registry description ≤100 chars).

### Code Quality

- **QLT-01**: `update_finding` decomposed into 4 helpers — `_resolve_caller_role_for_gate`, `_compute_cascade_post_state`, `_compute_cascade_cause`, `_emit_gate_audit_event`. Main handler body ~75 LOC. All 19 pre-existing `update_finding` tests pass unmodified. Cyclomatic complexity remains at 23 (radon grade D) — body-LOC target met; CC target <10 deferred to v3.3 as SA-001 (Vikunja #650) pending a second-pass extraction of `_validate_update_fields` + `_run_cascade_gate`, or formal deviation acceptance.

### Performance

- **PERF-03**: audit-log file writes are now async via `QueueHandler` + `QueueListener`. The `WatchedFileHandler` is owned by the listener thread; the application-side `QueueHandler` enqueues records non-blockingly. AUD-01 single-chain HMAC + SB-1 per-handler `RedactingFilter` preserved on the destination handler. Stdlib `QueueHandler.enqueue()` uses `put_nowait()`; on `queue.Full` the failure is silently swallowed via `Handler.handleError()` — tracked as SB-003 / Vikunja #654 for a structured `audit_drop` event in v3.3.
- **PERF-08**: 6+2 slow tests now use a mock clock instead of real `time.sleep()`. Combined with PERF-03's async writes, the full suite runs in 18.87s (vs 52s baseline).

### Security (minor hardening)

- **SEC-06**: role-resolution default flipped to fail-CLOSED. Unrecognized / missing role identifiers map to the least-privileged role rather than reader.
- **SEC-07**: `_BARE_TOOL_MENTION_RE` added as a soft signal — flags but does not block when prose mentions an MCP tool name without a confirming token.
- **SEC-08**: `exc_info` tracebacks routed through the redactor before logging — private `_redacted_exc_text` attribute set on the LogRecord. Known follow-up: `_redacted_exc_text` currently surfaces as a duplicate JSON field on error records (SB-001 / Vikunja #652).
- **SEC-09**: `_TOKEN_PATTERN` broadened to match `Token`, `Bearer`, `APIKey`, `apikey` prefixes (case-insensitive), with `(?!\[REDACTED)` lookahead to avoid double-redaction.
- **SEC-10**: `transition_cause` field now multi-cause — emits the full set of triggering conditions instead of a single elif-selected cause.

### Domain (minor)

- **DOM-19**: `has_jira` removed from `list_findings` projection (was schema-lying — field never populated on list endpoint).
- **DOM-21**: structured `note_attach_failure` audit event added; `_warning` shape on `close_finding` / `reopen_finding` documented. Correlation fields (caller_id, request_id, caller_role) still missing — tracked as SB-002 / Vikunja #653.
- **DOM-22**: `AUDIT_HMAC_KEY` now fails CLOSED on network transports (`streamable-http`, `sse`). Server refuses to boot if the key is unset; opt-out via `REQUIRE_AUDIT_HMAC_KEY=false` (not recommended). Closes the ephemeral-key window where the HMAC chain didn't survive process restart.

### Tests

- 669/669 pass
- T1 added 0 new tests (all 19 existing `update_finding` tests preserved)
- T2 added regression tests for QueueListener wiring + mock-clock scaffolding
- T3 added per-finding tests for the 8 minor items

### Verification

Two-stage adversarial review: Stage A (Spec Compliance) PASS-WITH-NOTES, Stage B (Code Quality) PASS-WITH-NOTES. Combined: **PASS-WITH-NOTES** (0 critical, 5 IMPORTANT, 9 MINOR). ACs: 12/12 achieved, 1 partial (AC-14.2.1 CC threshold).

### Deferred to v3.3

- 13 Phase 14.2 follow-up findings tracked at Vikunja #650–#662 (5 P3 IMPORTANT + 8 P5 MINOR)
- DOM-23 (FindingSummary narrative fields — needs DECISIONS entry first)
- DOM-24 (cert pinning for DefectDojo + HTTPS log forwarder — operational complexity)
- PYSEC-2025-183 acceptance documentation (`pip-audit --ignore-vuln` in CI or SECURITY.md entry)
- Production RBAC migration (`MCP_ROLE_*` env vars — separate maintenance window)
- DefectDojo finding closure #3285..#3293 (mitigated in v3.2.0 code; needs DD API session)
- Forgejo historical-tag reconciliation (5 pre-v3.2 tags, optional)

### Operations

- Production redeploy to mcp-01 surfaced DOM-22's fail-CLOSED enforcement against the previously-ephemeral HMAC key. Migration to a Vault-managed persistent key landed alongside the release: `secret/mcp.audit_hmac_key` (64-char hex) is now rendered into `/opt/mcp/.env` by `laima/ansible/playbooks/vault-migrate-mcp.yml`. Live `integrity_hmac` chain values confirmed populating on production traffic post-deploy.

## [3.2.5] — 2026-05-18

Phase 14 — code-quality + performance housekeeping. Patch release. No observable behavior change. Tests 638 → 647 (+9). `pip-audit` clean (includes idna 3.13 → 3.15 bump for CVE-2026-45409).

### Code Quality

- **QLT-02**: new `@_translate_client_errors` decorator in `audit_logging.py` wraps 23 mutation tool handlers that previously had inline `try: ... except RuntimeError as e: raise ToolError(str(e))` boilerplate. Decorator stacks `@mcp.tool(auth=...) → @_translate_client_errors → @audit_tool → @_require_client → async def` and asserts `inspect.iscoroutinefunction(func)` at decoration time. 2 sites in `close_finding` / `reopen_finding` inner note-add blocks intentionally retain inline `try/except` because their except clauses are NON-RAISE (they augment the response with `_warning` instead of raising).
- **QLT-03**: new `_validate_tag_list(tags: list[str] | None) -> None` helper in `server.py` extracted from inline blocks duplicated across `import_scan` + `reimport_scan` + `add_finding_tags`. Single source of truth for the tag-validation chain (length → no_secrets → allowlist → no_prompt_injection).
- **QLT-04**: `client.close_finding` PATCH body construction rewritten as a state-map loop over `(("false_p", false_p), ("out_of_scope", out_of_scope), ("duplicate", duplicate))`. The 4-branch if/elif chain is gone. Multi-truthy-flag semantics preserved (regression-tested via new `test_close_finding_multiple_flags_clear_is_mitigated`).
- **QLT-06**: 3 bare `except Exception:` sites tightened to specific classes: `client.py:_sanitize_api_error` → `(ValueError, json.JSONDecodeError)`; `server.py:health_check` → `(RuntimeError, httpx.HTTPError)`; `server.py:_decode_file` → `(binascii.Error, ValueError)`. `CancelledError`, `MemoryError`, `KeyboardInterrupt` no longer swallowed.

### Performance

- **PERF-01**: `_SECRET_PATTERNS` consolidated into a single pre-compiled alternation regex `_SECRET_ALTERNATION_RE` with NAMED capture groups (one per class). A single `re.search` / `re.sub` walk identifies every match + its class via `m.lastgroup`. Replaces N=25 individual `pattern.search` calls in the hot path. `redact_response_text`, `RedactingFilter._redact_str`, and `validate_no_secrets` all use the alternation.
- **PERF-07**: `validate_no_secrets` uses the same alternation regex — one regex scan replaces 25 per call site.
- **PERF-02 / PERF-09 (Phase 14 Wave 3 correction)**: An initial attempt to move `RedactingFilter` from per-handler to root-logger attachment was reverted on Stage B re-review (commit `a76b01e`). Python's `Logger.callHandlers()` walks the parent chain to dispatch records to ancestor *handlers* but does NOT invoke ancestor *logger filters* — so a root-only attachment would silently bypass redaction for every record emitted via a child logger (the entire production path). RedactingFilter is now confirmed attached to each handler (stderr/file/syslog/HTTPS). The PERF-01 algorithmic win (single regex scan per filter invocation) is preserved.

### SB-3 — Named inner groups for placeholder gate

The 4 lowercase assignment patterns now use NAMED inner capture groups: `(?P<password_value>\S{12,})`, `(?P<passwd_value>...)`, `(?P<token_value>...)`, `(?P<secret_value>...)`. The SB-001 placeholder gate (DEC-026) looks up the value substring by name (`m.group("password_value")`) instead of via fragile outer+1 index math. Two import-time assertions enforce: (a) every gated class has a registered inner group, and (b) every registered inner group exists in the compiled alternation. Future additions of new gated classes fail loudly at module import if the mapping is incomplete.

### Dependencies

- **idna**: 3.13 → 3.15 (CVE-2026-45409). Transitive dependency bumped via `uv lock --upgrade-package idna`.

### Tests

- +3 decorator behavior tests for `_translate_client_errors`
- +2 alternation regex tests (per-class parity + every-handler RedactingFilter attachment)
- +1 production-fidelity child-logger redaction regression test (catches the would-be PERF-09 root-only-filter regression)
- +2 `_validate_tag_list` helper tests (invalid tag, None/empty no-op)
- +1 multi-truthy-flag `close_finding` regression test

### Deferred to v3.3 (Phase 14.2)

- QLT-01 (`update_finding` decomposition — 173 LOC into helpers)
- PERF-03 (`WatchedFileHandler` → `QueueHandler` + `QueueListener` for async file writes)
- PERF-08 (mock-clock in 6 slow tests using real `time.sleep()`)
- SEC-06..10 (5 minor security findings: fail-open role default, soft-pattern tool mentions, exc_info redaction, `_TOKEN_PATTERN` literal-only, transition_cause elif single-cause)
- DOM-19/21/22 (3 minor domain findings: has_jira schema-lies-vs-implementation, close/reopen note-attach `_warning` shape, ephemeral AUDIT_HMAC_KEY warning vs fail-close)
- DOM-23 (FindingSummary narrative fields — needs DECISIONS entry)
- DOM-24 (cert pinning — operational complexity)

## [3.2.0] — 2026-05-18

Batch ship of v3.2 audit-remediation epic — Phases 10/11/12/13. Closes the v3.1.0 pre-ship audit's remaining Important findings + Phase 9 verification follow-ups, in a chained branch lineage merged to `main` as a single integration. 560 → 638 tests (+78). `pip-audit` clean. All 4 phase EVALUATIONs PASS-WITH-NOTES, 0 critical.

### Phase 10 — Audit Log Integrity (v3.2.1, FR-035 / AC-10.1..AC-10.9)

- **AUD-02**: cross-session HMAC chain restoration. `_restore_chain_tail()` seeds `IntegrityChainFormatter._previous_hmac` from the prior process's last `integrity_hmac` field on startup; emits `event_type=lifecycle, chain_event=chain_start` with `prior_tail_status ∈ {resumed, no_prior_file, empty_file, unreadable}` and `resumed_from_prior` boolean. Cross-restart audit chain continuity is now examination-defensible end-to-end.
- **AUD-03**: `RedactingFilter` extended with a third catalog-based redaction pass over `security._SECRET_PATTERNS`, emitting `[REDACTED:<class>]` markers across all log paths — reaching parity with the read-path `redact_response_text()` semantics. Pre-existing env-var literal redaction and the legacy `"Token \S+"` regex continue unchanged.
- **AUD-04**: SIEM forwarder failure visibility. `SyslogForwardHandler._worker` and `HTTPSLogHandler._flush` now emit structured `audit_forward_failure` log events instead of bare `print(..., file=sys.stderr)`. Field shape canonicalized per DEC-025: syslog events carry `consecutive_failures` + circuit-breaker metadata; HTTPS events carry `reason=type(e).__name__` (bounded exception class — not `str(e)` — to prevent response-body leakage).
- **AUD-05**: SIGTERM-resilient session shutdown. `emit_session_shutdown(reason)` idempotency helper with `threading.Lock` guard called from both lifespan `finally:` AND `atexit` (uvicorn translates SIGTERM → `sys.exit()` → `atexit` fires). Single session-shutdown record reaches all sinks even when the FastMCP lifespan does not run cleanly.

### Phase 11 — Secret/Injection Pattern Hardening (v3.2.2, FR-036 / AC-11.1..AC-11.7)

- **SEC-01**: Unicode-resilient prompt-injection detector. `_normalize_for_injection_check()` NFKC-normalizes + Cf-strips + folds 8 Cyrillic homoglyphs (а/А, е/Е, о/О, р/Р, с/С, у/У, х/Х, і/І) before pattern matching. Zero-width spaces (U+200B/200C/200D/FEFF), fullwidth Latin (U+FF21–FF5A), and Cyrillic look-alikes no longer slip past the existing IGNORE / SYSTEM / TOOL_CALL / TOOL_COLON patterns. Input value is NOT mutated for the caller — `validate_no_prompt_injection` returns None or raises ToolError without rewriting strings.
- **SEC-02 + SEC-03**: `_SECRET_PATTERNS` catalog expanded by 11 real-world token classes — `github_pat_finegrained`, `vault_token` (hvs.* / hvb.*), `vault_legacy_token` (s.*), `anthropic_api_key` (sk-ant-*), `openai_project_key` (sk-proj-*), `stripe_live_key` (sk_live_* / rk_live_*), `twilio_account_sid` (AC[a-f0-9]{32}), `twilio_api_key_sid` (SK[a-f0-9]{32}), `sendgrid_api_key` (SG.*.*), `ed25519_private_key`, `ecdsa_private_key`. Each has at least one positive-match regression test. NCUA examiners and SIEM platforms now see the token families they expect to be redacted.
- **SB-001**: vulnerability-prose false positives eliminated. Lowercase `password=`/`passwd=`/`token=`/`secret=` patterns now require value `\S{12,}` (≥12 non-whitespace chars) + `is_placeholder_value()` gate (matches `<...>`, `YOUR_*_HERE`, `${VAR}`, `placeholder`/`example`/`anything`/`hunter2`/`password\d*` case-insensitive). Vulnerability description text like `"attacker can supply password=anything to bypass auth"` no longer triggers false redaction or write-side rejection. Gate applied at all three sites (`validate_no_secrets`, `RedactingFilter._redact_str`, `redact_response_text`). DEC-026 records the trade-off and operator escape hatch.

### Phase 12 — RBAC + Envelope + Operability (v3.2.3, FR-037 / AC-12.1..AC-12.7)

- **RBAC-01**: handler-level `permission_check_now()` extended to all 7 remaining mutation tools (`close_finding`, `reopen_finding`, `add_finding_note`, `add_finding_tags`, `remove_finding_tags`, `import_scan`, `reimport_scan`). All 12 mutation tools now have the DEC-022 belt-and-suspenders defense against future FastMCP dispatcher regressions. Parametrized 12-tool deny test monkeypatches `permission_check` to a no-op pass-through and asserts every mutation tool still denies a reader-role caller.
- **API-01**: `list_finding_notes` returns the universal `{items, pagination}` envelope contract via `_format_response()` / new `_format_unpaginated_list_response()` helper. Per-note `entry` field continues to be F-002 wrapped via `_UNTRUSTED_FIELDS` (entry added). DEC-027 records the F-002 wrap symmetry side effect on `add_finding_note`'s write-echo (entry field now `{"value": ..., "_warning": ...}` on the write response too — disable via `UNTRUSTED_CONTENT_WRAPPING=off`).
- **OP-01**: `httpx.Limits(max_connections=20, max_keepalive_connections=10)` applied to all `DefectDojoClient` constructions (single-key and dual-key modes via shared `_make_client`). A single caller can no longer DoS DefectDojo via concurrent in-flight requests. Tests cover both modes via `httpx.AsyncClient.__init__` capture (version-stable, no private-attr access).
- **OP-02**: `@mcp.custom_route("/health", methods=["GET"])` registered, returns `200 {"status": "ok"}`. Matches the existing Dockerfile HEALTHCHECK target. Unauthenticated (FastMCP convention), verified to stay open even with `MCP_AUTH_TOKEN` configured (orchestrator-friendly).
- **CFG-01**: `UNTRUSTED_CONTENT_WRAPPING` documented in README `Optional — Security` config table.

### Phase 13 — Phase 9 Minor Follow-ups (v3.2.4, FR-038 / AC-13.1..AC-13.10)

- **SA-002 / AC-13.1**: `update_finding`'s state-transition gate extended to handle the two-call `verified+inactive` mutex. Both orderings (`active=false` then later `verified=true`, AND `verified=true` then later `active=false`) rejected via post-state computation against the gate's live `get_finding` snapshot. Mutex check narrowed to fire only when `"verified" in kwargs or "active" in kwargs` so unrelated cascade-field updates on legacy-inconsistent records are not impacted.
- **SA-005 / SB-007 / AC-13.2**: `_wrap_untrusted` is now idempotent. Double-application returns the original envelope unchanged — no nested `{"value": {"value": ..., "_warning": ...}, "_warning": ...}`.
- **SB-002 / AC-13.3**: rate-limit moved BEFORE the state-transition gate's pre-flight `get_finding` GET. A rate-limited caller can no longer drive N×GET/min against DefectDojo via `update_finding` spam. `record_finding_read(finding_id)` called after the gate GET so the read-history audit trail reflects the gate input.
- **SB-003 / AC-13.4**: caller-role probe `except` clause broadened from `RuntimeError` to `(RuntimeError, AttributeError, TypeError, KeyError)`. Future FastMCP token-shape regressions fail closed (treated as no engagement_mgmt) rather than surfacing as 500s. Parametrized tests cover all 4 exception classes.
- **SB-005 / AC-13.5**: explicit `"X" in kwargs` semantics in the cascade gate (3 sites: `false_p`, `duplicate`, `out_of_scope`). Decoupled from the upstream None-filter step.
- **SA-001 / AC-13.6**: tag-validator error-message unified. `_CONTROL_CHAR_RE` removed; the Unicode-category branch (`unicodedata.category(ch)[0] == "C"`) is the single source of truth and covers ASCII Cc (0x00–0x1F, 0x7F) too. All control / line-break rejections emit `"tag must not contain control or line-break characters"`. Cross-file test update applied to `test_finding_lifecycle.py::test_add_finding_tags_rejects_control_chars` (4 parameterized cases).
- **SB-006 / AC-13.7**: Unicode-category tests in `tests/test_security.py` use explicit `"\uXXXX"` Python escapes + `assert "\uXXXX" in fixture` invariant assertions, guarding against future re-indenters / formatters silently stripping the literal byte.
- **SA-004 / AC-13.8**: new `test_authenticated_tier_70_parallel_under_gather` — 70 concurrent `_check_mutation_rate_limit` calls under one authenticated token via `asyncio.gather` split exactly 60 successes + 10 ToolError-rate-limit. Confirms `MutationRateLimiter`'s `asyncio.Lock`-backed check-and-append is atomic.
- **SB-004 / AC-13.9**: `scripts/scrub_legacy_secrets.py` gains `--rate-per-second` (default 5.0), `--checkpoint` (default `.scrub-checkpoint`), `--checkpoint-interval` (default 10). HTTP 429 responses handled as recoverable with exponential 1.0s→60.0s backoff over 5 retries per finding. Checkpoint atomically written (`tmp + os.replace`) every N findings; on startup, last-id is read and findings ≤ checkpoint are skipped. **SB-001 (Stage B IMPORTANT, post-verify fix)**: `_iter_findings` now passes `ordering=id` so the `<= resume_after` skip is correct (DefectDojo's default ordering is unspecified and previously could silently skip findings on production resume).

### Post-Verification Cleanup (in-session, all phase EVALUATION findings addressed before ship)

- Phase 12: 10 MINOR findings resolved across 3 cleanup commits (envelope helper extraction, docstring fixes, version-stable httpx limits test + dual-key + health-with-auth).
- Phase 13: 1 IMPORTANT + 10 MINOR findings resolved across 3 cleanup commits (scrub hardening: `ordering=id` + log 429 backoff + log unparseable checkpoint; gate refinements: `resolve_identity` + TOCTOU comment + narrow mutex; test coverage: broaden-except parametrized + `_wrap_untrusted` corners + `monkeypatch` limiter teardown).

### Added

- `_format_unpaginated_list_response(items, model)` helper in `server.py` — universal envelope for lists with no upstream pagination.
- `is_placeholder_value(s)` helper + `_PLACEHOLDER_VALUE_RE` in `security.py` (exported).
- `_PLACEHOLDER_GATED_CLASSES` frozenset (the 4 lowercase assignment class names).
- `_HOMOGLYPH_FOLD_TABLE` in `security.py` for the 8 Cyrillic → Latin folds.
- `_normalize_for_injection_check()` in `security.py`.
- `_restore_chain_tail()` + `chain_start` lifecycle event in `audit_logging.py`.
- `emit_session_shutdown(reason)` idempotency helper with `threading.Lock` guard.
- `@mcp.custom_route("/health", methods=["GET"])` HTTP route handler.
- `UNTRUSTED_CONTENT_WRAPPING` env var (existed as a code switch since Phase 9; now documented in README).
- DEC-025, DEC-026, DEC-027 in `.titan/DECISIONS.md`.

### Changed

- `pyproject.toml` version bump 3.1.0 → 3.2.0.
- `_UNTRUSTED_FIELDS` includes `"entry"` — `add_finding_note` write-echo also wraps the entry field (DEC-027).
- `_make_client` in `client.py` passes `limits=httpx.Limits(20, 10)` on construction.
- `IntegrityChainFormatter` formatter instance is now shared across all log handlers (carried over from v3.1.0's AUD-01 hotfix; no behavior change in v3.2.0 — listing here for completeness).

### Removed

- `_CONTROL_CHAR_RE` constant in `security.py` (Unicode-category branch is now the single source of truth — AC-13.6).
- Bespoke per-`entry` redaction + wrap comprehensions in `list_finding_notes` (replaced by `_format_unpaginated_list_response`).

## [3.1.0] — 2026-05-16

### Audit Log Integrity

- **AUD-01**: `IntegrityChainFormatter` is now attached as a single shared instance across all configured handlers (stderr, file, syslog, HTTPS forwarder). Previously each handler held its own `_previous_hmac` state, so the on-disk and SIEM-forwarded chains diverged silently whenever any one sink dropped records (queue back-pressure, circuit-breaker open, batch failure) — producing four independent chains with no canonical ordering. The tamper-evident chain now has a single authoritative sequence regardless of which sinks succeed. Per-record memoization (cached on the `LogRecord`) ensures every handler emits the byte-identical formatted line. A `threading.RLock` defends against future threaded-handler regressions. Identified by the v3.0.1 pre-ship audit (Critical finding — see `.titan/phases/09-red-team-remediation-2/AUDIT.md`); independently surfaced by three audit dimensions (security, performance, domain).
- New regression test `test_integrity_chain_shared_across_handlers` asserts that two handlers sharing one formatter receive identical lines and the resulting chain re-verifies end-to-end.

### Phase 9 — Red Team Engagement 119 — Remediation Wave 2 (2026-05-14 → 2026-05-16)

- TITAN Phase 9 planned (`.titan/phases/09-red-team-remediation-2/PLAN.md`) — 6 tasks, 4 waves, branch `titan/phase-9-red-team-remediation-2`. Targets all 11 still-open engagement-119 findings (2 Critical, 2 High, 7 Medium) including 3 residual bypasses (F-016/F-017/F-018) filed in Phase 2 verification.
- T1 investigation completed (`.titan/phases/09-red-team-remediation-2/INVESTIGATION-T1.md`) — root cause for F-001 / F-014 identified as a deployment misconfiguration (`MCP_ROLE_CLAUDE` set to bare token without `:role` suffix) combined with a silent fail-open in `build_rbac_auth()`. Prior STATE.md hypothesis (FastMCP `initialize`-bypass) corrected: FastMCP's `_get_tool` enforces `tool.auth` on every `tools/call`.
- **T1 shipped** (commit `16c2345`) — `build_rbac_auth()` now raises `RuntimeError` when `MCP_ROLE_*` env vars are present but none parse and no legacy fallback is set (DEC-021 fail-closed default). New `permission_check_now()` helper added at handler entry of the 5 highest-impact mutation tools (`create_product`, `create_engagement`, `create_test`, `create_finding`, `update_finding`) as belt-and-suspenders against future FastMCP dispatch regressions (DEC-022). 14 new RBAC tests; 472 passing (+16 net).
- T3 investigation completed (`.titan/phases/09-red-team-remediation-2/INVESTIGATION-T3.md`) — root cause for F-004 identified as bucket-key derivation: `_caller_id(ctx)` read `ctx.client_id` which FastMCP sources from MCP-client-controlled `_meta.client_id`. Limiter itself was correctly atomic; key was forgeable.
- **T3 shipped** (commit `6a2295f`) — new `resolve_identity(ctx)` helper sources `authenticated_caller_id` from `get_access_token().client_id` (trusted bearer-token-bound). Two-tier limiters: per-token bucket at 60/min for authenticated callers, single shared bucket at 10/min (configurable via `OPEN_ACCESS_MUTATION_RATE_LIMIT`) for all unauthenticated traffic. `Retry-After: <N>s` semantics added to rate-limit errors. Audit log additive: new `authenticated_caller_id` field alongside legacy `caller_id` (no breaking change for SIEM). Open-access tool-call warning replaces the prior "Anonymous tool access" warning. 8 new identity/limiter tests, 3 new audit tests; 484 passing (+12 net) (DEC-023).
- README updated: new `OPEN_ACCESS_MUTATION_RATE_LIMIT` env var documented; new "Audit Log Field Trust Model" section explicitly labels each field trusted/untrusted; Write Tools section describes two-tier limiting and `Retry-After` semantics.
- Remaining Phase 9 work: T2 (F-002 stored prompt injection), T4 (F-005/F-016 + F-006/F-017 paired residuals), T5 (F-008/F-018 state-transition gate + F-007 has_jira), T6 (verify-F00X battery + DefectDojo finding closure + cleanup of probe artifact product id=8 on rt DefectDojo).

### Security — Red Team Engagement Remediation (engagement 119)

- **F-013**: `import_scan` / `reimport_scan` returned HTTP 415 because the shared httpx client carried a `Content-Type: application/json` default that leaked into multipart POSTs. Removed the JSON default; httpx now sets the correct header per call (`json=...` → JSON, `files=...` → multipart with boundary).
- **F-008**: `update_finding` no longer lets a `finding_mgmt` caller clear `is_mitigated` to reopen a mitigated finding. Added `reopen_finding` tool requiring `engagement_mgmt` permission for the reopen flow.
- **F-015**: `update_finding` rejects mutually exclusive state combinations in the same request (`active=true + is_mitigated=true`, and `verified=true + active=false`).
- **F-003**: `FindingNote.author` accepts the nested `{id, username, first_name, last_name}` object DefectDojo actually returns (new `NoteAuthor` model). Previously raised `ValidationError` leaking schema and Pydantic version to callers.
- **F-012**: `client.get_finding_notes` extracts the `notes` key from the DefectDojo `{finding_id, notes:[...]}` wrapper (previously fell back to wrapping the envelope into a single bogus note).
- **F-011**: `client.remove_finding_tags` normalizes the empty-body success response (`{}`) into `{"tags": []}` so the response model no longer raises on successful removals.
- **F-005**: New `validate_no_secrets()` rejects values containing recognizable credential patterns (AWS keys, GitHub PATs, Slack tokens, PEM private keys, `*_API_KEY=`/`*_SECRET=`/`*_TOKEN=`/`*_PASSWORD=` assignments, bearer tokens) on every write tool that accepts user-controlled text.
- **F-006 / F-010**: `validate_tag()` rejects tag values containing any control character (0x00–0x1F, 0x7F) — closes newline-injection and ANSI-escape vectors.
- **F-009**: `validate_tag()` rejects tags containing commas, which DefectDojo silently splits server-side into multiple tags.

### Added

- `reopen_finding` MCP tool — `engagement_mgmt`-gated remediation-reversal path, complement to `close_finding`. Total tool count now 24.
- `NoteAuthor` Pydantic model for DefectDojo's nested note-author shape.
- `validate_tag()` and `validate_no_secrets()` in `security.py` with comprehensive test coverage.

## [3.0.0] — 2026-05-11

### Added
- **Role-Based Access Control (RBAC)**: 4-role permission model replacing binary read/write scopes
  - Roles: `admin` (all permissions), `writer` (engagement/finding/scan management), `scanner` (scan management + read), `reader` (read-only)
  - 6 permission groups: `system`, `metadata_read`, `product_mgmt`, `engagement_mgmt`, `finding_mgmt`, `scan_mgmt`
  - New `MCP_ROLE_<NAME>=<token>:<role>` env var format for fine-grained token-role binding
  - Permission denial audit logging with caller_id, tool_name, required_permission, caller_role
  - Deny-by-default: all 23 tools require explicit permission assignment
- `tests/test_rbac.py`: 55 RBAC-specific tests covering all 14 acceptance criteria
- `MutationRateLimiter` stale caller eviction (prevents unbounded memory growth)
- Integration test for session summary in lifespan teardown

### Changed
- **BREAKING**: Auth model upgraded from binary scopes (`read`/`write`) to role-based permissions. Existing `MCP_AUTH_TOKEN` maps to `admin` role and `MCP_READ_TOKEN` maps to `reader` role for backward compatibility.
- Lifespan security warning now correctly detects `MCP_ROLE_*` env vars (no longer triggers false alarm for RBAC-only deployments)
- `ROLE_PERMISSIONS` uses `frozenset` to enforce immutability at the language level
- `MCP_ROLE_*` env var parsing uses `rsplit(":", 1)` to correctly handle tokens containing colons

## [2.2.1] — 2026-05-10

### Fixed
- `add_finding_note` sending `note_type: 0` which DefectDojo rejected as invalid pk — changed to `int | None = None`, only included when explicitly set
- API error messages leaking DefectDojo field names and validation rules to MCP clients — added `_sanitize_api_error()` with generic messages per HTTP status code (400→"Invalid request parameters", 404→"Resource not found", etc.)
- `HTTPSLogHandler` accepting non-HTTP URL schemes (e.g., `file://`) — added scheme validation for defense in depth

### Security (CI hardening)
- Removed `curl -sk` TLS bypass in DefectDojo upload steps — CI now uses `--cacert` with internal CA certificate (Medium finding resolved)
- Added SHA256 hash verification for Gitleaks binary download in security workflow
- Pinned uv installer to version 0.11.5 in test workflow for supply chain integrity

### Improved
- `HTTPSLogHandler` logs WARNING when configured with `http://` scheme (defense in depth)
- `close_finding` returns result with `_warning` field on partial success (note attachment failure after successful close)
- `health_check` sanitizes error messages — returns generic response to clients, raw error logged server-side only

## [2.2.0] — 2026-05-10

### Added
- `import_scan` tool: upload scanner results (225+ scan types) via multipart form upload with base64 file content (50MB max)
- `reimport_scan` tool: re-upload results to existing test with `close_old_findings` support
- `list_product_types` tool: enumerate product types for use in `create_product`
- `list_test_types` tool: enumerate test types for use in `create_test`
- `close_finding` tool: close findings with reason (mitigated/false_positive/out_of_scope/duplicate) and optional note
- `add_finding_note` tool: attach notes to findings
- `list_finding_notes` tool: read notes on a finding
- `add_finding_tags` / `remove_finding_tags` tools: tag management on findings
- `ImportScanResult`, `ProductTypeSummary`, `TestTypeSummary`, `FindingNote` Pydantic models
- `_multipart_request` client method for multipart form uploads
- `_decode_file` helper for base64 file validation
- 96 new tests (302 total)

### Changed
- `list_findings` enhanced from 3 to 18 filter parameters (product_id, engagement_id, severity, active, verified, duplicate, false_p, out_of_scope, is_mitigated, risk_accepted, has_jira, tags, outside_of_sla, component_name, title)

### Fixed
- CI test workflow: Python install switched from apt to `uv python install` (node:22-slim lacks python3.X packages)
- CI security workflow: DefectDojo upload `scan_date` removed to avoid UTC/timezone "future date" errors
- CI security workflow: Gitleaks step uses `set +e` exit code handling instead of `continue-on-error: true`

## [2.1.0] — 2026-05-10

### Added
- SIEM log forwarding via syslog (TCP/UDP/TCP+TLS with RFC 5424 framing)
- SIEM log forwarding via HTTPS webhook with batching and background delivery
- `AUDIT_LOG_HTTPS_TOKEN` added to secret redaction list
- SIEM integration documentation in README

## [2.0.0] — 2026-05-09

### Added
- Structured JSON audit logging with correlation IDs and retention class tagging
- HMAC-SHA256 integrity chain for tamper-evident audit log records
- Per-tool audit decorator capturing caller identity, request params, and outcomes
- Scope-based access control (read/write) with per-tool enforcement
- Mutation rate limiting (configurable window and max calls)
- TLS enforcement for DefectDojo API connections (with explicit opt-out)
- Secret redaction in all log output (API keys, auth tokens, HMAC keys)
- Log export to file with configurable path
- Session summary logging on shutdown (tool call counts, error rates)
- `pip-audit` vulnerability scanning in CI
- Python 3.13 CI test matrix

### Changed
- Switched to streamable-http MCP transport (from SSE)
- Docker base image pinned by digest for reproducibility
- Finding titles truncated in audit logs for privacy

### Fixed
- Dockerfile runtime permission errors (cache dirs, uv sync)
- README quickstart env file path
- `uv` version pinned in CI workflow

## [1.0.0] — 2026-05-07

### Added
- 14 MCP tools: products, engagements, tests, findings (CRUD + list)
- Health check tool for connectivity verification
- Pydantic response models with strict validation
- Input validation (date formats, severity values, numeric ranges)
- Pagination with configurable limits
- Structured logging for client operations
- Docker container deployment
- 182 unit tests at 96% coverage
- MIT license

### Fixed
- URL validation and TLS warnings
- Null client reference after close
- `locals()` removed from error context (security)
- Bearer auth for MCP transport

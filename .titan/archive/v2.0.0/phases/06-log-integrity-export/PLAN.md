---
phase: 6
name: Log Integrity & Export
status: planned
tasks: 3
waves: 2
created: 2026-05-08
---

# Phase 6 — Log Integrity & Export

## Goal
Ensure audit logs are tamper-evident, exportable, and carry retention metadata — closing the loop on regulatory evidence requirements for NCUA/FFIEC examinations.

## Features
- FR-028: Structured log export (dedicated file, JSON-lines, logrotate-compatible)
- FR-029: Log integrity checksums (rolling HMAC-SHA256 chain)
- FR-030: Session audit summary (shutdown summary log entry)
- FR-031: Retention metadata (retention_class field per log entry)
- FR-032: Audit log test suite

## Architecture Notes

Current logging architecture (from Phases 4.1/4.2):
- `StructuredJsonFormatter` formats log records as JSON
- `RedactingFilter` strips secrets before emission
- `configure_logging()` sets up root logger with StreamHandler to stderr
- `audit_tool` decorator emits structured audit records for every tool call

Phase 6 extends this by:
1. Adding a second handler (FileHandler) for dedicated audit log file
2. Adding HMAC-SHA256 chain to StructuredJsonFormatter for tamper evidence
3. Adding `retention_class` field to log records based on event_type
4. Emitting a session summary in the lifespan teardown
5. All changes in `audit_logging.py` — no changes to server.py tool logic

Key design decisions:
- File handler uses `logging.handlers.RotatingFileHandler` (or WatchedFileHandler for external logrotate)
- HMAC key from `AUDIT_HMAC_KEY` env var (or auto-generated if not set)
- Chain: each entry's HMAC includes the previous entry's HMAC
- Retention classes: "security_audit" (tool calls, auth events), "operational" (lifecycle, API calls), "debug" (everything else)

## Tasks

### T1: Log Export, Integrity Chain & Retention Metadata
**Wave:** 1
**Files:** `src/mcp_defectdojo/audit_logging.py`
**Features:** FR-028, FR-029, FR-031

**Changes to `audit_logging.py`:**

1. Add imports: `hashlib`, `hmac`, `logging.handlers`

2. Create `IntegrityChainFormatter(StructuredJsonFormatter)`:
   - Subclass of StructuredJsonFormatter
   - Maintains `_previous_hmac` state (starts as empty string)
   - `__init__(self, hmac_key: bytes)` — stores the HMAC key
   - Override `format()`:
     a. Call `super().format(record)` to get JSON string
     b. Parse JSON, add `retention_class` field based on `event_type`:
        - "audit" or "security_warning" → "security_audit"
        - "lifecycle" or "api_request" or "api_response" or "api_error" or "connection_error" → "operational"
        - Everything else → "debug"
     c. Compute HMAC-SHA256: `hmac.new(key, f"{previous_hmac}|{json_str}".encode(), hashlib.sha256).hexdigest()`
     d. Add `integrity_hmac` field to the JSON
     e. Update `_previous_hmac` to the new HMAC
     f. Return the updated JSON string

3. Create `SessionCounter`:
   - Simple counter class that tracks: total_requests, requests_by_tool (dict), error_count, start_time
   - `record(tool_name, outcome)` method to increment counters
   - `summary()` method returns dict with counts and uptime

4. Module-level `_session_counter = SessionCounter()` instance

5. Update `audit_tool` decorator to call `_session_counter.record(func.__name__, outcome)` after each tool call

6. Update `configure_logging()`:
   - Accept optional `audit_log_file` parameter (default from `AUDIT_LOG_FILE` env var)
   - Accept optional `hmac_key` parameter (default from `AUDIT_HMAC_KEY` env var, or generate random)
   - If `audit_log_file` is set:
     a. Create `logging.handlers.WatchedFileHandler(audit_log_file)` — compatible with external logrotate
     b. Set formatter to `IntegrityChainFormatter(hmac_key)`
     c. Add `RedactingFilter` to the file handler
     d. Add handler to root logger
   - If no `audit_log_file`: stderr-only mode (backward compat)
   - Use `IntegrityChainFormatter` for stderr handler too (adds retention_class + integrity)

**Verification:**
- Audit log file created when AUDIT_LOG_FILE is set
- Each line is valid JSON with retention_class and integrity_hmac fields
- HMAC chain is verifiable: recomputing from first to last produces matching HMACs
- Without AUDIT_LOG_FILE, only stderr output (backward compat)

### T2: Session Summary & Lifespan Integration
**Wave:** 1 (parallel with T1 — T2 only touches server.py)
**Files:** `src/mcp_defectdojo/server.py`
**Features:** FR-030

**Changes to `server.py`:**

1. Import `_session_counter` from audit_logging
2. In `lifespan()` finally block, before closing client:
   - Call `_session_counter.summary()` to get session stats
   - Emit: `logger.info("Session shutdown", extra={"event_type": "lifecycle", "session_summary": summary})`
   - This includes: total_requests, requests_by_tool, error_count, uptime_seconds

**Verification:**
- On server shutdown, a session summary log entry is emitted
- Summary includes tool-level breakdown and error count

### T3: Audit Log Test Suite
**Wave:** 2 (after T1 and T2)
**Files:** `tests/test_log_integrity.py` (new)
**Features:** FR-032

**Test cases:**

1. **Log export:**
   - `test_audit_log_file_created` — AUDIT_LOG_FILE set, file created with JSON lines
   - `test_audit_log_no_file_by_default` — no env var, stderr only
   - `test_audit_log_lines_are_valid_json` — each line parseable

2. **Integrity chain:**
   - `test_integrity_hmac_present` — every log line has integrity_hmac field
   - `test_integrity_chain_verifiable` — recompute chain from scratch, all HMACs match
   - `test_integrity_chain_detects_tamper` — modify a line, chain breaks

3. **Retention metadata:**
   - `test_retention_class_security_audit` — audit events have "security_audit"
   - `test_retention_class_operational` — lifecycle events have "operational"
   - `test_retention_class_debug` — other events have "debug"

4. **Session summary:**
   - `test_session_counter_tracks_calls` — counter increments per tool call
   - `test_session_counter_tracks_errors` — error count increments on failure
   - `test_session_summary_format` — summary dict has expected keys

**Verification:**
- All new tests pass
- All existing 164 tests still pass

## Acceptance Criteria

| AC ID | Criterion | Task |
|-------|-----------|------|
| AC-6.1 | Given AUDIT_LOG_FILE env var, When the server runs and tools are called, Then a dedicated file contains JSON-lines audit entries | T1 |
| AC-6.2 | Given any log entry, When inspected, Then it contains an `integrity_hmac` field that is a valid HMAC-SHA256 hex string | T1 |
| AC-6.3 | Given a sequence of log entries, When the HMAC chain is recomputed from first to last, Then all HMACs match (tamper-evident) | T1 |
| AC-6.4 | Given a tampered log entry, When the chain is verified, Then the tamper is detected (HMAC mismatch) | T1 |
| AC-6.5 | Given any log entry, When inspected, Then it contains a `retention_class` field with value "security_audit", "operational", or "debug" | T1 |
| AC-6.6 | Given server shutdown, When the lifespan teardown runs, Then a summary log entry is emitted with total_requests, requests_by_tool, error_count, uptime_seconds | T2 |
| AC-6.7 | Given no AUDIT_LOG_FILE env var, When the server runs, Then only stderr output is produced (backward compat) | T1 |
| AC-6.8 | All features have test coverage verifying both positive and negative cases | T3 |

## Wave Schedule

| Wave | Tasks | Parallel? | Rationale |
|------|-------|-----------|-----------|
| 1 | T1, T2 | Yes | T1 modifies audit_logging.py; T2 modifies server.py lifespan only. No overlap. |
| 2 | T3 | No | Tests depend on T1 and T2 |

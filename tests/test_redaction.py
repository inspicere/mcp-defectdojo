"""Phase 9 / T4 — F-005 / F-016 read-side redaction regression suite.

Tests for `redact_response_text` (audit_logging.py) and its integration into
the `_format_response` pipeline (server.py). The redactor handles legacy data
that predates the write-side `validate_no_secrets` guard.

Interaction with T2's `_apply_untrusted_wrapping`: redaction runs FIRST, so
the `[REDACTED:<class>]` marker ends up inside the `"value"` slot of the
envelope, not adjacent to the `"_warning"` key.

All test fixtures use synthetic / clearly-marked-fake strings — never real
credentials.
"""
import json

import pytest
from unittest.mock import AsyncMock

import mcp_defectdojo.server as server_module
from mcp_defectdojo.audit_logging import redact_response_text
from mcp_defectdojo.server import get_finding, list_finding_notes


# ---------------------------------------------------------------------------
# Unit-level: redact_response_text
# ---------------------------------------------------------------------------


def test_redact_returns_none_for_none():
    assert redact_response_text(None, "title") is None


def test_redact_preserves_clean_text():
    """Strings with no secret patterns are returned unchanged."""
    txt = "SQL injection in /api/v1/login allows authentication bypass."
    assert redact_response_text(txt, "description") == txt


def test_redact_aws_access_key_emits_class_marker():
    result = redact_response_text("creds AKIAIOSFODNN7EXAMPLE here", "description")
    assert "[REDACTED:aws_access_key]" in result
    assert "AKIAIOSFODNN7EXAMPLE" not in result


def test_redact_github_pat_emits_class_marker():
    fake = "ghp_FAKETESTTOKENFORREGEXMATCH0123456789xx"
    result = redact_response_text(f"see also: {fake}", "description")
    assert "[REDACTED:github_pat]" in result
    assert fake not in result


def test_redact_password_assignment_emits_class_marker():
    result = redact_response_text("config: password=hunter2-fake", "description")
    assert "[REDACTED:password_assignment]" in result
    assert "hunter2-fake" not in result


def test_redact_handles_list_elementwise():
    """Tags are list-valued and must be redacted per element."""
    fake = "ghp_FAKETESTTOKENFORREGEXMATCH0123456789xx"
    result = redact_response_text(["benign", f"leak:{fake}"], "tags")
    assert isinstance(result, list)
    assert result[0] == "benign"
    assert "[REDACTED:github_pat]" in result[1]


def test_redact_non_string_passes_through():
    """Non-str / non-list / non-None values pass through unchanged."""
    assert redact_response_text(42, "title") == 42
    assert redact_response_text({"x": 1}, "title") == {"x": 1}


def test_redact_empty_string_returns_empty():
    assert redact_response_text("", "title") == ""


# ---------------------------------------------------------------------------
# Integration: _format_response pipeline
# ---------------------------------------------------------------------------
#
# These tests use real server tool handlers with a patched client, mirroring
# the pattern from test_prompt_injection.py. They confirm that:
#   1. The redactor runs in the response pipeline (pre-existing secrets get
#      `[REDACTED:*]` markers).
#   2. The redaction marker ends up inside the T2 envelope's "value" slot
#      (not at the same level as "_warning") — i.e. order is redact → wrap.


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    try:
        yield mock
    finally:
        server_module.client = None


@pytest.fixture
def sample_finding_with_legacy_secret():
    """A finding shaped like one created BEFORE Phase 9 hardening — the
    description carries a synthetic AWS-key-shaped string that the write-side
    validator now blocks. On read, the redactor must strip it."""
    return {
        "id": 1, "test": 4, "title": "Old issue",
        "severity": "High",
        "description": "Reproduction creds: AKIAIOSFODNN7EXAMPLE were stored.",
        "active": True, "verified": False,
        "mitigated": None, "is_mitigated": False, "out_of_scope": False,
        "false_p": False, "duplicate": False,
        "tags": ["web", "stored"],
    }


async def test_redact_aws_access_key_in_existing_data(
    patched_client, sample_finding_with_legacy_secret, monkeypatch
):
    """A pre-existing AKIA* in description must be replaced with the marker
    on the read path."""
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    patched_client.get_finding.return_value = sample_finding_with_legacy_secret
    result = await get_finding(finding_id=1)
    data = json.loads(result)
    # Wrapping is on by default, so description is `{"value": ..., "_warning": ...}`.
    assert "[REDACTED:aws_access_key]" in data["description"]["value"]
    assert "AKIAIOSFODNN7EXAMPLE" not in data["description"]["value"]


async def test_redact_github_pat_in_description(patched_client, monkeypatch):
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    fake = "ghp_FAKETESTTOKENFORREGEXMATCH0123456789xx"
    finding = {
        "id": 2, "test": 4, "title": "Legacy",
        "severity": "Low",
        "description": f"Found token: {fake}",
        "active": True, "verified": False,
        "mitigated": None, "is_mitigated": False, "out_of_scope": False,
        "false_p": False, "duplicate": False,
    }
    patched_client.get_finding.return_value = finding
    result = await get_finding(finding_id=2)
    data = json.loads(result)
    assert "[REDACTED:github_pat]" in data["description"]["value"]
    assert fake not in data["description"]["value"]


async def test_redact_password_in_title(patched_client, monkeypatch):
    """The title field also gets scrubbed — legacy ingestion sometimes
    stuffed assignments there."""
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    finding = {
        "id": 3, "test": 4,
        "title": "Bug: password=hunter2-fake leaked",
        "severity": "Critical",
        "description": "details",
        "active": True, "verified": False,
        "mitigated": None, "is_mitigated": False, "out_of_scope": False,
        "false_p": False, "duplicate": False,
    }
    patched_client.get_finding.return_value = finding
    result = await get_finding(finding_id=3)
    data = json.loads(result)
    assert "[REDACTED:password_assignment]" in data["title"]["value"]
    assert "hunter2-fake" not in data["title"]["value"]


async def test_redact_does_not_alter_clean_text(
    patched_client, sample_finding_with_legacy_secret, monkeypatch
):
    """A finding with no embedded secrets must come back byte-identical
    (modulo the T2 envelope)."""
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    clean = dict(sample_finding_with_legacy_secret)
    clean["description"] = "SQL injection in /api/v1/login"
    clean["title"] = "Auth bypass"
    patched_client.get_finding.return_value = clean
    result = await get_finding(finding_id=1)
    data = json.loads(result)
    assert data["title"]["value"] == "Auth bypass"
    assert data["description"]["value"] == "SQL injection in /api/v1/login"
    assert "[REDACTED" not in data["title"]["value"]
    assert "[REDACTED" not in data["description"]["value"]


async def test_redact_preserves_envelope_wrapping(
    patched_client, sample_finding_with_legacy_secret, monkeypatch
):
    """Order check: redact runs BEFORE wrap, so the marker is inside `value`
    and the `_warning` key is at the same depth as `value`."""
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    patched_client.get_finding.return_value = sample_finding_with_legacy_secret
    result = await get_finding(finding_id=1)
    data = json.loads(result)
    desc = data["description"]
    assert isinstance(desc, dict)
    assert set(desc.keys()) == {"value", "_warning"}
    assert "[REDACTED:aws_access_key]" in desc["value"]
    assert desc["_warning"].startswith("untrusted-content")


async def test_redact_runs_even_when_wrapping_disabled(
    patched_client, sample_finding_with_legacy_secret, monkeypatch
):
    """Operators may disable the T2 envelope (UNTRUSTED_CONTENT_WRAPPING=off)
    for backward compat — but redaction must still fire so legacy secrets
    never exit the server."""
    monkeypatch.setenv("UNTRUSTED_CONTENT_WRAPPING", "off")
    patched_client.get_finding.return_value = sample_finding_with_legacy_secret
    result = await get_finding(finding_id=1)
    data = json.loads(result)
    # Description is now a bare string (envelope off) — marker still present.
    assert isinstance(data["description"], str)
    assert "[REDACTED:aws_access_key]" in data["description"]
    assert "AKIAIOSFODNN7EXAMPLE" not in data["description"]


async def test_redact_note_entry_in_list_finding_notes(patched_client, monkeypatch):
    """`list_finding_notes` redacts via `_format_response`'s shared
    `_apply_response_redaction` pass (Phase 12 / API-01 envelope unification).
    Verify the marker shows up inside the envelope's `items[*].entry`."""
    monkeypatch.delenv("UNTRUSTED_CONTENT_WRAPPING", raising=False)
    fake = "ghp_FAKETESTTOKENFORREGEXMATCH0123456789xx"
    patched_client.get_finding_notes.return_value = [
        {"id": 1, "entry": f"Old triage note carrying {fake}", "private": False},
    ]
    result = await list_finding_notes(finding_id=1)
    data = json.loads(result)
    entry = data["items"][0]["entry"]
    # Wrapping on by default — entry is the envelope dict.
    assert isinstance(entry, dict)
    assert "[REDACTED:github_pat]" in entry["value"]
    assert fake not in entry["value"]


# ---------------------------------------------------------------------------
# RedactingFilter — _SECRET_PATTERNS catalog pass (AC-10.4 / AC-10.5)
# ---------------------------------------------------------------------------
#
# These tests verify that RedactingFilter._redact_str now applies the third
# pass (over security._SECRET_PATTERNS) to every log record, bringing the
# log path to parity with the read path's redact_response_text(). They also
# act as regression guards for the existing env-var and legacy-token passes.

import io
import logging as _logging

from mcp_defectdojo.audit_logging import RedactingFilter, StructuredJsonFormatter


def _capture_log_output(msg: str, *args, extra=None, level=_logging.INFO) -> str:
    """Emit one log record through a RedactingFilter and return the formatted string.

    Uses StructuredJsonFormatter so extra fields appear in the captured JSON,
    which allows assertions on specific field values.
    """
    buf = io.StringIO()
    handler = _logging.StreamHandler(buf)
    handler.setFormatter(StructuredJsonFormatter())
    filt = RedactingFilter()
    handler.addFilter(filt)

    log = _logging.getLogger(f"_test_capture_{id(buf)}")
    log.propagate = False
    log.setLevel(_logging.DEBUG)
    log.addHandler(handler)
    try:
        log.log(level, msg, *args, extra=extra or {})
    finally:
        log.removeHandler(handler)
        handler.close()

    return buf.getvalue()


def test_redacting_filter_redacts_pem_block():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQI...\n-----END PRIVATE KEY-----"
    out = _capture_log_output("%s", pem)
    assert "[REDACTED:pem_private_key]" in out
    assert "BEGIN PRIVATE KEY" not in out


def test_redacting_filter_redacts_github_pat():
    token = "ghp_" + "a" * 36
    out = _capture_log_output(f"found token {token}")
    assert "[REDACTED:" in out
    assert token not in out


def test_redacting_filter_redacts_bearer_token():
    out = _capture_log_output("auth: Bearer xyz123abc456")
    assert "[REDACTED:bearer_token]" in out


def test_redacting_filter_redacts_extra_dict_values():
    out = _capture_log_output(
        "audit record",
        extra={"event_type": "audit", "tool_name": "x", "stash": "AKIAIOSFODNN7EXAMPLE"},
    )
    assert "[REDACTED:aws_access_key]" in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_redacting_filter_env_var_redaction_still_works(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "supersecret123")
    buf = io.StringIO()
    handler = _logging.StreamHandler(buf)
    handler.setFormatter(StructuredJsonFormatter())
    filt = RedactingFilter()
    filt.refresh_secrets()
    handler.addFilter(filt)

    log = _logging.getLogger("_test_env_var_redaction")
    log.propagate = False
    log.setLevel(_logging.DEBUG)
    log.addHandler(handler)
    try:
        log.info("key=%s", "supersecret123")
    finally:
        log.removeHandler(handler)
        handler.close()

    out = buf.getvalue()
    assert "***REDACTED***" in out
    assert "supersecret123" not in out


# ---------------------------------------------------------------------------
# SEC-02 + SEC-03 — New pattern classes flow through RedactingFilter (Phase 11 / T2)
# ---------------------------------------------------------------------------


def test_redacting_filter_redacts_github_pat_finegrained():
    token = "github_pat_" + "x" * 92
    out = _capture_log_output(f"leak: {token}")
    assert "[REDACTED:github_pat_finegrained]" in out
    assert token not in out


def test_redacting_filter_redacts_vault_token():
    token = "hvs.AAAA" + "B" * 30
    out = _capture_log_output(token)
    assert "[REDACTED:vault_token]" in out
    assert token not in out


def test_redacting_filter_redacts_anthropic_api_key():
    token = "sk-ant-api03-" + "Z" * 60
    out = _capture_log_output(token)
    assert "[REDACTED:anthropic_api_key]" in out
    assert token not in out


def test_redacting_filter_redacts_stripe_live_key():
    token = "sk_live_" + "A" * 30
    out = _capture_log_output(token)
    assert "[REDACTED:stripe_live_key]" in out
    assert token not in out


def test_redacting_filter_does_not_redact_placeholder_password():
    """SB-001 / DEC-026 — placeholder values must pass through unredacted."""
    text = "docs: password=<value>"
    out = _capture_log_output(text)
    assert "[REDACTED:password_assignment]" not in out
    text2 = "config: password=YOUR_PASSWORD_HERE"
    out2 = _capture_log_output(text2)
    assert "[REDACTED:password_assignment]" not in out2


def test_redacting_filter_redacts_real_long_password():
    """SB-001 / DEC-026 — real long-form secrets still redact."""
    text = "config has password=Tr0ub4dor&3xampleLongPwd plaintext"
    out = _capture_log_output(text)
    assert "[REDACTED:password_assignment]" in out
    assert "Tr0ub4dor&3xampleLongPwd" not in out

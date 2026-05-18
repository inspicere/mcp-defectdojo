"""Tests for finding lifecycle tools — close, notes, tags."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

import mcp_defectdojo.server as server_module
from mcp_defectdojo.server import (
    add_finding_note,
    add_finding_tags,
    close_finding,
    list_finding_notes,
    remove_finding_tags,
    reopen_finding,
    update_finding,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_client():
    mock = AsyncMock()
    server_module.client = mock
    yield mock
    server_module.client = None


@pytest.fixture
def closed_finding(sample_finding):
    """A finding dict that looks like it was closed."""
    f = dict(sample_finding)
    f["active"] = False
    f["is_mitigated"] = True
    return f


# ---------------------------------------------------------------------------
# close_finding tests
# ---------------------------------------------------------------------------


async def test_close_finding_mitigated(patched_client, sample_finding, closed_finding):
    patched_client.close_finding.return_value = closed_finding
    result = await close_finding(finding_id=1, reason="mitigated")
    data = json.loads(result)
    assert data["active"] is False
    assert data["is_mitigated"] is True
    patched_client.close_finding.assert_called_once_with(
        1,
        is_mitigated=True,
        false_p=False,
        out_of_scope=False,
        duplicate=False,
    )


async def test_close_finding_false_positive(patched_client, closed_finding):
    closed_finding["false_p"] = True
    closed_finding["is_mitigated"] = False
    patched_client.close_finding.return_value = closed_finding
    result = await close_finding(finding_id=1, reason="false_positive")
    data = json.loads(result)
    assert data["active"] is False
    assert data["false_p"] is True
    patched_client.close_finding.assert_called_once_with(
        1,
        is_mitigated=False,
        false_p=True,
        out_of_scope=False,
        duplicate=False,
    )


async def test_close_finding_out_of_scope(patched_client, closed_finding):
    closed_finding["out_of_scope"] = True
    closed_finding["is_mitigated"] = False
    patched_client.close_finding.return_value = closed_finding
    result = await close_finding(finding_id=1, reason="out_of_scope")
    data = json.loads(result)
    assert data["active"] is False
    assert data["out_of_scope"] is True
    patched_client.close_finding.assert_called_once_with(
        1,
        is_mitigated=False,
        false_p=False,
        out_of_scope=True,
        duplicate=False,
    )


async def test_close_finding_duplicate(patched_client, closed_finding):
    closed_finding["duplicate"] = True
    closed_finding["is_mitigated"] = False
    patched_client.close_finding.return_value = closed_finding
    result = await close_finding(finding_id=1, reason="duplicate")
    data = json.loads(result)
    assert data["active"] is False
    assert data["duplicate"] is True
    patched_client.close_finding.assert_called_once_with(
        1,
        is_mitigated=False,
        false_p=False,
        out_of_scope=False,
        duplicate=True,
    )


async def test_close_finding_with_note(patched_client, closed_finding):
    patched_client.close_finding.return_value = closed_finding
    patched_client.add_finding_note.return_value = {"id": 10, "entry": "Mitigated in v2.1"}
    result = await close_finding(finding_id=1, reason="mitigated", note="Mitigated in v2.1")
    data = json.loads(result)
    assert data["active"] is False
    patched_client.close_finding.assert_called_once()
    patched_client.add_finding_note.assert_called_once_with(1, "Mitigated in v2.1")


async def test_close_finding_invalid_reason(patched_client):
    with pytest.raises(ToolError, match="reason must be one of"):
        await close_finding(finding_id=1, reason="invalid_reason")


async def test_close_finding_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await close_finding(finding_id=0, reason="mitigated")


async def test_close_finding_negative_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await close_finding(finding_id=-1, reason="mitigated")


# ---------------------------------------------------------------------------
# add_finding_note tests
# ---------------------------------------------------------------------------


async def test_add_finding_note(patched_client):
    note_response = {"id": 5, "entry": "Test note", "private": False}
    patched_client.add_finding_note.return_value = note_response
    result = await add_finding_note(finding_id=1, entry="Test note")
    data = json.loads(result)
    # F-002: note `entry` is wrapped in the untrusted-content envelope (T2/Phase 12).
    assert data["entry"]["value"] == "Test note"
    assert data["private"] is False
    patched_client.add_finding_note.assert_called_once_with(1, "Test note", private=False)


async def test_add_finding_note_private(patched_client):
    note_response = {"id": 6, "entry": "Private note", "private": True}
    patched_client.add_finding_note.return_value = note_response
    result = await add_finding_note(finding_id=1, entry="Private note", private=True)
    data = json.loads(result)
    assert data["private"] is True
    patched_client.add_finding_note.assert_called_once_with(1, "Private note", private=True)


async def test_add_finding_note_too_long(patched_client):
    long_entry = "x" * 10001
    with pytest.raises(ToolError, match="entry exceeds maximum length"):
        await add_finding_note(finding_id=1, entry=long_entry)


async def test_add_finding_note_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await add_finding_note(finding_id=0, entry="note")


# ---------------------------------------------------------------------------
# list_finding_notes tests
# ---------------------------------------------------------------------------


async def test_list_finding_notes(patched_client):
    notes = [
        {"id": 1, "entry": "First note", "private": False},
        {"id": 2, "entry": "Second note", "private": True},
    ]
    patched_client.get_finding_notes.return_value = notes
    result = await list_finding_notes(finding_id=1)
    data = json.loads(result)
    # API-01: list_finding_notes returns the universal envelope.
    assert isinstance(data["items"], list) and len(data["items"]) == 2
    assert data["pagination"]["count"] == 2
    # F-002: note `entry` is wrapped in the untrusted-content envelope.
    assert data["items"][0]["entry"]["value"] == "First note"
    assert data["items"][1]["entry"]["value"] == "Second note"


async def test_list_finding_notes_envelope_shape(patched_client):
    # API-01: explicit assertion of envelope contract keys.
    notes = [{"id": 1, "entry": "envelope check", "private": False}]
    patched_client.get_finding_notes.return_value = notes
    result = await list_finding_notes(finding_id=1)
    data = json.loads(result)
    assert "items" in data
    assert "pagination" in data
    pagination = data["pagination"]
    assert "count" in pagination
    assert "offset" in pagination
    assert "limit" in pagination
    assert "has_next" in pagination
    assert pagination["count"] == 1
    assert pagination["offset"] == 0
    assert pagination["has_next"] is False


async def test_list_finding_notes_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await list_finding_notes(finding_id=0)


# ---------------------------------------------------------------------------
# add_finding_tags tests
# ---------------------------------------------------------------------------


async def test_add_finding_tags(patched_client):
    tag_response = {"tags": ["critical", "web"]}
    patched_client.add_finding_tags.return_value = tag_response
    result = await add_finding_tags(finding_id=1, tags=["critical", "web"])
    data = json.loads(result)
    # F-002: tags returned on the read path are wrapped in the envelope.
    assert data["tags"]["value"] == ["critical", "web"]
    patched_client.add_finding_tags.assert_called_once_with(1, ["critical", "web"])


async def test_add_finding_tags_empty(patched_client):
    with pytest.raises(ToolError, match="tags must be a non-empty list"):
        await add_finding_tags(finding_id=1, tags=[])


async def test_add_finding_tags_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await add_finding_tags(finding_id=0, tags=["tag1"])


async def test_add_finding_tags_tag_too_long(patched_client):
    long_tag = "x" * 201
    with pytest.raises(ToolError, match="tag exceeds maximum length"):
        await add_finding_tags(finding_id=1, tags=[long_tag])


# ---------------------------------------------------------------------------
# remove_finding_tags tests
# ---------------------------------------------------------------------------


async def test_remove_finding_tags(patched_client):
    tag_response = {"tags": ["remaining-tag"]}
    patched_client.remove_finding_tags.return_value = tag_response
    result = await remove_finding_tags(finding_id=1, tags=["old-tag"])
    data = json.loads(result)
    # F-002: tags returned on the read path are wrapped in the envelope.
    assert data["tags"]["value"] == ["remaining-tag"]
    patched_client.remove_finding_tags.assert_called_once_with(1, ["old-tag"])


async def test_remove_finding_tags_empty(patched_client):
    with pytest.raises(ToolError, match="tags must be a non-empty list"):
        await remove_finding_tags(finding_id=1, tags=[])


async def test_remove_finding_tags_invalid_id(patched_client):
    with pytest.raises(ToolError, match="finding_id must be > 0"):
        await remove_finding_tags(finding_id=0, tags=["tag1"])


# ---------------------------------------------------------------------------
# Rate limiter integration test
# ---------------------------------------------------------------------------


async def test_close_finding_rate_limited(patched_client, closed_finding):
    """Verify close_finding routes through the rate limiter (open-access tier under test)."""
    patched_client.close_finding.return_value = closed_finding
    with patch.object(server_module._open_access_limiter, "check", new_callable=AsyncMock) as mock_check:
        await close_finding(finding_id=1, reason="mitigated")
        mock_check.assert_called_once()


async def test_add_finding_note_rate_limited(patched_client):
    """Verify add_finding_note routes through the rate limiter (open-access tier under test)."""
    patched_client.add_finding_note.return_value = {"id": 1, "entry": "note"}
    with patch.object(server_module._open_access_limiter, "check", new_callable=AsyncMock) as mock_check:
        await add_finding_note(finding_id=1, entry="note")
        mock_check.assert_called_once()


async def test_add_finding_tags_rate_limited(patched_client):
    """Verify add_finding_tags routes through the rate limiter (open-access tier under test)."""
    patched_client.add_finding_tags.return_value = {"tags": ["tag1"]}
    with patch.object(server_module._open_access_limiter, "check", new_callable=AsyncMock) as mock_check:
        await add_finding_tags(finding_id=1, tags=["tag1"])
        mock_check.assert_called_once()


async def test_remove_finding_tags_rate_limited(patched_client):
    """Verify remove_finding_tags routes through the rate limiter (open-access tier under test)."""
    patched_client.remove_finding_tags.return_value = {"tags": []}
    with patch.object(server_module._open_access_limiter, "check", new_callable=AsyncMock) as mock_check:
        await remove_finding_tags(finding_id=1, tags=["tag1"])
        mock_check.assert_called_once()


# ---------------------------------------------------------------------------
# RuntimeError propagation tests
# ---------------------------------------------------------------------------


async def test_close_finding_api_error(patched_client):
    patched_client.close_finding.side_effect = RuntimeError("DefectDojo API Error 404: not found")
    with pytest.raises(ToolError, match="404"):
        await close_finding(finding_id=1, reason="mitigated")


async def test_add_finding_note_api_error(patched_client):
    patched_client.add_finding_note.side_effect = RuntimeError("DefectDojo API Error 500: server error")
    with pytest.raises(ToolError, match="500"):
        await add_finding_note(finding_id=1, entry="note")


async def test_list_finding_notes_api_error(patched_client):
    patched_client.get_finding_notes.side_effect = RuntimeError("DefectDojo API Error 404: not found")
    with pytest.raises(ToolError, match="404"):
        await list_finding_notes(finding_id=1)


async def test_add_finding_tags_api_error(patched_client):
    patched_client.add_finding_tags.side_effect = RuntimeError("DefectDojo API Error 400: bad request")
    with pytest.raises(ToolError, match="400"):
        await add_finding_tags(finding_id=1, tags=["tag1"])


async def test_remove_finding_tags_api_error(patched_client):
    patched_client.remove_finding_tags.side_effect = RuntimeError("DefectDojo API Error 400: bad request")
    with pytest.raises(ToolError, match="400"):
        await remove_finding_tags(finding_id=1, tags=["tag1"])


# ---------------------------------------------------------------------------
# Null guard tests — client is None
# ---------------------------------------------------------------------------


async def test_close_finding_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await close_finding(finding_id=1, reason="mitigated")


async def test_add_finding_note_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await add_finding_note(finding_id=1, entry="note")


async def test_list_finding_notes_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await list_finding_notes(finding_id=1)


async def test_add_finding_tags_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await add_finding_tags(finding_id=1, tags=["tag"])


async def test_remove_finding_tags_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await remove_finding_tags(finding_id=1, tags=["tag"])


# ---------------------------------------------------------------------------
# State transition gates — F-008 (reopen authority) and F-015 (consistent state)
# ---------------------------------------------------------------------------


async def test_update_finding_rejects_clearing_is_mitigated(patched_client, closed_finding):
    """F-008: update_finding must not let a finding_mgmt caller un-mitigate via is_mitigated=false.

    The new state-transition gate fetches the current finding via get_finding
    to determine whether is_mitigated → false would be a real state change, so
    the test must seed `get_finding` with a mitigated record.
    """
    patched_client.get_finding.return_value = closed_finding
    with pytest.raises(ToolError, match="reopen_finding"):
        await update_finding(finding_id=1, is_mitigated=False)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_rejects_active_and_mitigated(patched_client):
    """F-015: update_finding must reject active=true with is_mitigated=true in the same request."""
    with pytest.raises(ToolError, match="active=true and is_mitigated=true"):
        await update_finding(finding_id=1, active=True, is_mitigated=True)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_rejects_verified_on_inactive(patched_client):
    """F-008 secondary: update_finding must reject verified=true when active=false."""
    with pytest.raises(ToolError, match="verified=true on an inactive"):
        await update_finding(finding_id=1, verified=True, active=False)
    patched_client.update_finding.assert_not_called()


async def test_update_finding_allows_setting_is_mitigated_true(patched_client, sample_finding):
    """update_finding may still set is_mitigated=true (closing-equivalent path).

    Finding is not currently mitigated (sample_finding has is_mitigated=False),
    so the cascade gate is a no-op.
    """
    patched_client.get_finding.return_value = sample_finding
    patched_client.update_finding.return_value = sample_finding
    await update_finding(finding_id=1, is_mitigated=True, active=False)
    patched_client.update_finding.assert_called_once_with(1, is_mitigated=True, active=False)


async def test_reopen_finding_calls_client_with_reset_state(patched_client, sample_finding):
    """reopen_finding clears mitigation and reactivates."""
    patched_client.update_finding.return_value = sample_finding
    result = await reopen_finding(finding_id=1)
    data = json.loads(result)
    assert data["id"] == sample_finding["id"]
    patched_client.update_finding.assert_called_once_with(
        1, is_mitigated=False, active=True, false_p=False, out_of_scope=False, duplicate=False,
    )


async def test_reopen_finding_attaches_note(patched_client, sample_finding):
    patched_client.update_finding.return_value = sample_finding
    patched_client.add_finding_note.return_value = {"id": 1, "entry": "regressed in prod"}
    await reopen_finding(finding_id=1, note="regressed in prod")
    patched_client.add_finding_note.assert_called_once_with(1, "regressed in prod")


async def test_reopen_finding_zero_id(patched_client):
    with pytest.raises(ToolError, match="finding_id"):
        await reopen_finding(finding_id=0)


async def test_reopen_finding_null_guard():
    server_module.client = None
    with pytest.raises(ToolError, match="not initialized"):
        await reopen_finding(finding_id=1)


async def test_reopen_finding_note_attach_failure_returns_warning(patched_client, sample_finding):
    patched_client.update_finding.return_value = sample_finding
    patched_client.add_finding_note.side_effect = RuntimeError("note service down")
    result = await reopen_finding(finding_id=1, note="reopen note")
    data = json.loads(result)
    assert "_warning" in data
    assert "note failed" in data["_warning"]


# ---------------------------------------------------------------------------
# Tag sanitization — F-006 (newlines), F-009 (commas), F-010 (ANSI escapes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_tag,reason", [
    ("tag-with-newline\ninjected", "newline"),
    ("tag\ttab", "tab"),
    ("ansi-\x1b[31mred", "ANSI escape"),
    ("null\x00byte", "null"),
])
async def test_add_finding_tags_rejects_control_chars(patched_client, bad_tag, reason):
    """F-006/F-010: tags containing any control character must be rejected on write."""
    with pytest.raises(ToolError, match="control characters"):
        await add_finding_tags(finding_id=1, tags=[bad_tag])
    patched_client.add_finding_tags.assert_not_called()


async def test_add_finding_tags_rejects_comma(patched_client):
    """F-009: comma in a tag string is silently split server-side into multiple tags."""
    with pytest.raises(ToolError, match="comma"):
        await add_finding_tags(finding_id=1, tags=["legitimate,injected"])
    patched_client.add_finding_tags.assert_not_called()


async def test_add_finding_tags_rejects_empty_tag(patched_client):
    with pytest.raises(ToolError, match="empty"):
        await add_finding_tags(finding_id=1, tags=[""])
    patched_client.add_finding_tags.assert_not_called()


async def test_add_finding_tags_accepts_clean_tag(patched_client):
    patched_client.add_finding_tags.return_value = {"tags": ["clean-tag"]}
    result = await add_finding_tags(finding_id=1, tags=["clean-tag"])
    data = json.loads(result)
    # F-002: tags returned on the read path are wrapped in the envelope.
    assert data["tags"]["value"] == ["clean-tag"]


# ---------------------------------------------------------------------------
# Secret redaction on write paths — F-005
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("secret_payload", [
    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG",
    "AKIAIOSFODNN7EXAMPLE",
    "DEFECTDOJO_API_KEY=abcdef123456",
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9zzzzzzzzzzzzzzz",
    "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
])
async def test_add_finding_tags_rejects_embedded_secrets(patched_client, secret_payload):
    """F-005: tags containing recognizable secret patterns must be rejected."""
    with pytest.raises(ToolError, match="embedded secret"):
        await add_finding_tags(finding_id=1, tags=[secret_payload])
    patched_client.add_finding_tags.assert_not_called()


async def test_add_finding_note_rejects_embedded_secret(patched_client):
    """F-005: notes with embedded secrets must be rejected at the boundary."""
    with pytest.raises(ToolError, match="embedded secret"):
        await add_finding_note(finding_id=1, entry="please rotate AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI")
    patched_client.add_finding_note.assert_not_called()

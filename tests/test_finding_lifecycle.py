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
    assert data["entry"] == "Test note"
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
    assert len(data) == 2
    assert data[0]["entry"] == "First note"
    assert data[1]["entry"] == "Second note"


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
    assert data["tags"] == ["critical", "web"]
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
    assert data["tags"] == ["remaining-tag"]
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
    """Verify close_finding calls the mutation rate limiter."""
    patched_client.close_finding.return_value = closed_finding
    with patch.object(server_module._mutation_limiter, "check", new_callable=AsyncMock) as mock_check:
        await close_finding(finding_id=1, reason="mitigated")
        mock_check.assert_called_once()


async def test_add_finding_note_rate_limited(patched_client):
    """Verify add_finding_note calls the mutation rate limiter."""
    patched_client.add_finding_note.return_value = {"id": 1, "entry": "note"}
    with patch.object(server_module._mutation_limiter, "check", new_callable=AsyncMock) as mock_check:
        await add_finding_note(finding_id=1, entry="note")
        mock_check.assert_called_once()


async def test_add_finding_tags_rate_limited(patched_client):
    """Verify add_finding_tags calls the mutation rate limiter."""
    patched_client.add_finding_tags.return_value = {"tags": ["tag1"]}
    with patch.object(server_module._mutation_limiter, "check", new_callable=AsyncMock) as mock_check:
        await add_finding_tags(finding_id=1, tags=["tag1"])
        mock_check.assert_called_once()


async def test_remove_finding_tags_rate_limited(patched_client):
    """Verify remove_finding_tags calls the mutation rate limiter."""
    patched_client.remove_finding_tags.return_value = {"tags": []}
    with patch.object(server_module._mutation_limiter, "check", new_callable=AsyncMock) as mock_check:
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

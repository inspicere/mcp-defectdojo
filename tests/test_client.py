"""Tests for DefectDojoClient — HTTP mocking via respx."""
import json
import logging

import httpx
import pytest
import respx

from mcp_defectdojo.client import DefectDojoClient

BASE = "http://test.defectdojo.local/api/v2"


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


def test_client_init_success(mock_env):
    client = DefectDojoClient()
    assert client.base_url == "http://test.defectdojo.local"
    assert client.api_key == "test-api-key-12345"
    assert isinstance(client._client, httpx.AsyncClient)
    assert str(client._client.base_url).rstrip("/").endswith("/api/v2")


def test_client_init_missing_url(monkeypatch):
    monkeypatch.delenv("DEFECTDOJO_URL", raising=False)
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="DEFECTDOJO_URL"):
        DefectDojoClient()


def test_client_init_missing_key(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://test.defectdojo.local")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    with pytest.raises(ValueError):
        DefectDojoClient()


def test_client_init_both_missing(monkeypatch):
    monkeypatch.delenv("DEFECTDOJO_URL", raising=False)
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    with pytest.raises(ValueError):
        DefectDojoClient()


def test_client_init_invalid_scheme(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "ftp://defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="http or https"):
        DefectDojoClient()


def test_client_init_embedded_credentials(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://admin:password@defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="embedded credentials"):
        DefectDojoClient()


def test_client_init_no_hostname(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="hostname"):
        DefectDojoClient()


def test_client_init_http_rejected_by_default(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    monkeypatch.delenv("ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(ValueError, match="TLS is required"):
        DefectDojoClient()


def test_client_init_http_allowed_with_override(monkeypatch, caplog):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    with caplog.at_level(logging.CRITICAL, logger="mcp_defectdojo.client"):
        DefectDojoClient()
    assert "cleartext" in caplog.text


@pytest.mark.asyncio
async def test_client_aclose(mock_client):
    await mock_client.aclose()


def test_make_client_sets_concurrency_limits_single_key(mock_env, monkeypatch):
    """OP-01: outbound httpx concurrency cap is passed to the AsyncClient
    constructor in single-key mode. Version-stable: asserts on the `limits=`
    kwarg captured at construction time, not on httpx's private internals
    (which moved between minor versions historically — SB-1 finding).
    """
    captured_limits = []
    original_init = httpx.AsyncClient.__init__

    def capturing_init(self, *args, **kwargs):
        captured_limits.append(kwargs.get("limits"))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", capturing_init)
    DefectDojoClient()  # single-key mode (mock_env sets DEFECTDOJO_API_KEY only)
    assert len(captured_limits) == 1, "single-key mode constructs exactly one AsyncClient"
    limits = captured_limits[0]
    assert isinstance(limits, httpx.Limits)
    assert limits.max_connections == 20
    assert limits.max_keepalive_connections == 10


def test_make_client_sets_concurrency_limits_dual_key(monkeypatch):
    """OP-01 / SA-2: dual-key mode constructs TWO AsyncClients (read + write).
    Both must receive the same concurrency cap. Regression guard for any
    future refactor that special-cases dual-key construction outside
    `_make_client`.
    """
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key-123")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key-456")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)

    captured_limits = []
    original_init = httpx.AsyncClient.__init__

    def capturing_init(self, *args, **kwargs):
        captured_limits.append(kwargs.get("limits"))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", capturing_init)
    client = DefectDojoClient()
    assert client._dual_key_mode is True
    assert len(captured_limits) == 2, "dual-key mode constructs read + write clients"
    for limits in captured_limits:
        assert isinstance(limits, httpx.Limits)
        assert limits.max_connections == 20
        assert limits.max_keepalive_connections == 10


# ---------------------------------------------------------------------------
# _request method tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_request_get_success(mock_client):
    expected = {"count": 1, "results": [{"id": 1}]}
    respx.get(f"{BASE}/products/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_products()
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_request_post_success(mock_client):
    product = {"id": 2, "name": "New Product", "description": "desc", "prod_type": 1}
    respx.post(f"{BASE}/products/").mock(return_value=httpx.Response(201, json=product))
    result = await mock_client.create_product("New Product", "desc", 1)
    assert result == product


@pytest.mark.asyncio
@respx.mock
async def test_request_204_no_content(mock_client):
    respx.patch(f"{BASE}/findings/9/").mock(return_value=httpx.Response(204))
    result = await mock_client.update_finding(9, active=False)
    assert result == {}


@pytest.mark.asyncio
@respx.mock
async def test_request_http_error_json(mock_client):
    respx.get(f"{BASE}/products/5/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found"})
    )
    with pytest.raises(RuntimeError) as exc_info:
        await mock_client.get_product(5)
    assert "404" in str(exc_info.value)
    assert "Resource not found" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_request_http_error_non_json(mock_client):
    respx.get(f"{BASE}/products/5/").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    with pytest.raises(RuntimeError) as exc_info:
        await mock_client.get_product(5)
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_request_connect_error(mock_client):
    respx.get(f"{BASE}/products/5/").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(RuntimeError) as exc_info:
        await mock_client.get_product(5)
    assert "request failed" in str(exc_info.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_request_connect_error_no_url_leak(mock_client):
    """Connection errors should not leak the internal base URL."""
    respx.get(f"{BASE}/products/5/").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(RuntimeError) as exc_info:
        await mock_client.get_product(5)
    assert "test.defectdojo.local" not in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_request_timeout(mock_client):
    respx.get(f"{BASE}/products/5/").mock(
        side_effect=httpx.ReadTimeout("Timed out")
    )
    with pytest.raises(RuntimeError) as exc_info:
        await mock_client.get_product(5)
    assert "request failed" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# API method tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_products(mock_client):
    expected = {"count": 0, "results": []}
    route = respx.get(f"{BASE}/products/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_products()
    assert route.called
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_get_product(mock_client):
    product = {"id": 5, "name": "Prod", "description": "d", "prod_type": 1}
    route = respx.get(f"{BASE}/products/5/").mock(return_value=httpx.Response(200, json=product))
    result = await mock_client.get_product(5)
    assert route.called
    assert result["id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_create_product(mock_client):
    product = {"id": 3, "name": "Created", "description": "desc", "prod_type": 2}
    route = respx.post(f"{BASE}/products/").mock(return_value=httpx.Response(201, json=product))
    result = await mock_client.create_product("Created", "desc", 2)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "Created"
    assert body["description"] == "desc"
    assert body["prod_type"] == 2
    assert result["id"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_get_engagements(mock_client):
    expected = {"count": 0, "results": []}
    route = respx.get(f"{BASE}/engagements/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_engagements(product_id=1)
    assert route.called
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_get_engagement(mock_client):
    eng = {"id": 3, "product": 1, "name": "Eng", "target_start": "2026-01-01", "target_end": "2026-12-31"}
    route = respx.get(f"{BASE}/engagements/3/").mock(return_value=httpx.Response(200, json=eng))
    result = await mock_client.get_engagement(3)
    assert route.called
    assert result["id"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_create_engagement(mock_client):
    eng = {"id": 4, "product": 1, "name": "New Eng", "target_start": "2026-01-01", "target_end": "2026-06-30"}
    route = respx.post(f"{BASE}/engagements/").mock(return_value=httpx.Response(201, json=eng))
    result = await mock_client.create_engagement(1, "New Eng", "2026-01-01", "2026-06-30")
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["product"] == 1
    assert body["name"] == "New Eng"
    assert body["target_start"] == "2026-01-01"
    assert body["target_end"] == "2026-06-30"
    assert result["id"] == 4


@pytest.mark.asyncio
@respx.mock
async def test_get_tests(mock_client):
    expected = {"count": 0, "results": []}
    route = respx.get(f"{BASE}/tests/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_tests(engagement_id=2)
    assert route.called
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_get_test(mock_client):
    test_obj = {"id": 7, "engagement": 2, "test_type": 1, "title": "SAST"}
    route = respx.get(f"{BASE}/tests/7/").mock(return_value=httpx.Response(200, json=test_obj))
    result = await mock_client.get_test(7)
    assert route.called
    assert result["id"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_create_test(mock_client):
    test_obj = {"id": 8, "engagement": 2, "test_type": 3, "target_start": "2026-01-01", "target_end": "2026-12-31"}
    route = respx.post(f"{BASE}/tests/").mock(return_value=httpx.Response(201, json=test_obj))
    result = await mock_client.create_test(2, 3, "2026-01-01", "2026-12-31")
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["engagement"] == 2
    assert body["test_type"] == 3
    assert body["target_start"] == "2026-01-01"
    assert body["target_end"] == "2026-12-31"
    assert result["id"] == 8


@pytest.mark.asyncio
@respx.mock
async def test_get_findings(mock_client):
    expected = {"count": 0, "results": []}
    route = respx.get(f"{BASE}/findings/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_findings()
    assert route.called
    request = route.calls.last.request
    assert "test=" not in str(request.url)
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_get_findings_with_test_id(mock_client):
    expected = {"count": 1, "results": [{"id": 10}]}
    route = respx.get(f"{BASE}/findings/").mock(return_value=httpx.Response(200, json=expected))
    result = await mock_client.get_findings(test_id=4)
    assert route.called
    request = route.calls.last.request
    assert "test=4" in str(request.url)
    assert result == expected


@pytest.mark.asyncio
@respx.mock
async def test_get_finding(mock_client):
    finding = {"id": 9, "test": 4, "title": "SQLi", "severity": "Critical"}
    route = respx.get(f"{BASE}/findings/9/").mock(return_value=httpx.Response(200, json=finding))
    result = await mock_client.get_finding(9)
    assert route.called
    assert result["id"] == 9


@pytest.mark.asyncio
@respx.mock
async def test_create_finding(mock_client):
    finding = {"id": 11, "test": 4, "title": "XSS", "severity": "High", "description": "Found XSS", "active": True, "verified": False}
    route = respx.post(f"{BASE}/findings/").mock(return_value=httpx.Response(201, json=finding))
    result = await mock_client.create_finding(4, "XSS", "High", "Found XSS", active=True, verified=False)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["test"] == 4
    assert body["title"] == "XSS"
    assert body["severity"] == "High"
    assert body["description"] == "Found XSS"
    assert body["active"] is True
    assert body["verified"] is False
    assert body["found_by"] == [1]
    assert result["id"] == 11


@pytest.mark.asyncio
@respx.mock
async def test_create_finding_custom_found_by(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("DEFECTDOJO_DEFAULT_FOUND_BY_ID", "7")
    client = DefectDojoClient()
    finding = {"id": 12, "test": 4, "title": "SQLi", "severity": "Critical"}
    route = respx.post(f"{BASE}/findings/").mock(return_value=httpx.Response(201, json=finding))
    await client.create_finding(4, "SQLi", "Critical", "Found SQLi")
    body = json.loads(route.calls.last.request.content)
    assert body["found_by"] == [7]


def test_default_found_by_id_invalid_value(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("DEFECTDOJO_DEFAULT_FOUND_BY_ID", "not-a-number")
    with pytest.raises(ValueError, match="DEFECTDOJO_DEFAULT_FOUND_BY_ID"):
        DefectDojoClient()


def test_default_found_by_id_non_positive(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("DEFECTDOJO_DEFAULT_FOUND_BY_ID", "0")
    with pytest.raises(ValueError, match="DEFECTDOJO_DEFAULT_FOUND_BY_ID"):
        DefectDojoClient()


@pytest.mark.asyncio
@respx.mock
async def test_update_finding(mock_client):
    updated = {"id": 9, "active": False, "verified": True}
    route = respx.patch(f"{BASE}/findings/9/").mock(return_value=httpx.Response(200, json=updated))
    result = await mock_client.update_finding(9, active=False, verified=True)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"active": False, "verified": True}
    assert result["id"] == 9


# ---------------------------------------------------------------------------
# get_findings filter parameter coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_findings_all_filters(mock_client):
    expected = {"count": 0, "results": []}
    route = respx.get(f"{BASE}/findings/").mock(return_value=httpx.Response(200, json=expected))
    await mock_client.get_findings(
        product_id=1, engagement_id=2, severity="High",
        active=True, verified=False, duplicate=False,
        false_p=False, out_of_scope=False, is_mitigated=False,
        risk_accepted=False, has_jira=True, tags=["web", "api"],
        outside_of_sla=True, component_name="libfoo", title="XSS",
    )
    assert route.called
    url = str(route.calls.last.request.url)
    assert "test__engagement__product=1" in url
    assert "test__engagement=2" in url
    assert "severity=High" in url
    assert "active=true" in url
    assert "verified=false" in url
    assert "duplicate=false" in url
    assert "false_p=false" in url
    assert "out_of_scope=false" in url
    assert "is_mitigated=false" in url
    assert "risk_accepted=false" in url
    assert "has_jira_issue=true" in url
    assert "tags=web" in url
    assert "outside_of_sla=true" in url
    assert "component_name=libfoo" in url
    assert "title=XSS" in url


# ---------------------------------------------------------------------------
# close_finding — reason variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_close_finding_mitigated(mock_client):
    route = respx.patch(f"{BASE}/findings/5/").mock(return_value=httpx.Response(200, json={"id": 5}))
    result = await mock_client.close_finding(5, is_mitigated=True)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["active"] is False
    assert body["is_mitigated"] is True
    assert "false_p" not in body


@pytest.mark.asyncio
@respx.mock
async def test_close_finding_false_positive(mock_client):
    route = respx.patch(f"{BASE}/findings/6/").mock(return_value=httpx.Response(200, json={"id": 6}))
    result = await mock_client.close_finding(6, is_mitigated=False, false_p=True)
    body = json.loads(route.calls.last.request.content)
    assert body["false_p"] is True
    assert body["is_mitigated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_close_finding_out_of_scope(mock_client):
    route = respx.patch(f"{BASE}/findings/7/").mock(return_value=httpx.Response(200, json={"id": 7}))
    await mock_client.close_finding(7, is_mitigated=False, out_of_scope=True)
    body = json.loads(route.calls.last.request.content)
    assert body["out_of_scope"] is True
    assert body["is_mitigated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_close_finding_duplicate(mock_client):
    route = respx.patch(f"{BASE}/findings/8/").mock(return_value=httpx.Response(200, json={"id": 8}))
    await mock_client.close_finding(8, is_mitigated=False, duplicate=True)
    body = json.loads(route.calls.last.request.content)
    assert body["duplicate"] is True
    assert body["is_mitigated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_close_finding_multiple_flags_clear_is_mitigated(mock_client):
    """SB-7: with multiple truthy flags, ALL flag fields are set AND
    is_mitigated is forced to False. This pins the state-map loop's
    semantics — a future refactor to elif would silently drop flags."""
    route = respx.patch(f"{BASE}/findings/9/").mock(return_value=httpx.Response(200, json={"id": 9}))
    await mock_client.close_finding(9, false_p=True, out_of_scope=True, duplicate=True)
    body = json.loads(route.calls.last.request.content)
    assert body["false_p"] is True
    assert body["out_of_scope"] is True
    assert body["duplicate"] is True
    assert body["is_mitigated"] is False
    assert body["active"] is False


# ---------------------------------------------------------------------------
# Finding notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_finding_note(mock_client):
    note = {"id": 1, "entry": "test note", "private": False}
    route = respx.post(f"{BASE}/findings/3/notes/").mock(return_value=httpx.Response(201, json=note))
    result = await mock_client.add_finding_note(3, "test note")
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["entry"] == "test note"
    assert body["private"] is False
    assert "note_type" not in body


@pytest.mark.asyncio
@respx.mock
async def test_add_finding_note_with_type(mock_client):
    note = {"id": 2, "entry": "typed", "private": True}
    route = respx.post(f"{BASE}/findings/3/notes/").mock(return_value=httpx.Response(201, json=note))
    result = await mock_client.add_finding_note(3, "typed", note_type=5, private=True)
    body = json.loads(route.calls.last.request.content)
    assert body["note_type"] == 5
    assert body["private"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_finding_notes_list_response(mock_client):
    notes = [{"id": 1, "entry": "note1"}, {"id": 2, "entry": "note2"}]
    respx.get(f"{BASE}/findings/3/notes/").mock(return_value=httpx.Response(200, json=notes))
    result = await mock_client.get_finding_notes(3)
    assert len(result) == 2
    assert result[0]["entry"] == "note1"


@pytest.mark.asyncio
@respx.mock
async def test_get_finding_notes_paginated_response(mock_client):
    paginated = {"count": 1, "results": [{"id": 1, "entry": "note1"}]}
    respx.get(f"{BASE}/findings/3/notes/").mock(return_value=httpx.Response(200, json=paginated))
    result = await mock_client.get_finding_notes(3)
    assert len(result) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_finding_notes_wrapper_response(mock_client):
    """F-012: DefectDojo wraps notes as {finding_id, notes:[...]}; the wrapper key
    is not "results" so the previous fallback wrapped it into [wrapper] and broke
    downstream Pydantic validation."""
    wrapper = {"finding_id": 3, "notes": [{"id": 1, "entry": "wrapped"}, {"id": 2, "entry": "second"}]}
    respx.get(f"{BASE}/findings/3/notes/").mock(return_value=httpx.Response(200, json=wrapper))
    result = await mock_client.get_finding_notes(3)
    assert len(result) == 2
    assert result[0]["entry"] == "wrapped"


@pytest.mark.asyncio
@respx.mock
async def test_get_finding_notes_empty_wrapper(mock_client):
    """F-012: empty notes inside the wrapper still produces an empty list."""
    wrapper = {"finding_id": 5, "notes": []}
    respx.get(f"{BASE}/findings/5/notes/").mock(return_value=httpx.Response(200, json=wrapper))
    result = await mock_client.get_finding_notes(5)
    assert result == []


# ---------------------------------------------------------------------------
# Finding tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_add_finding_tags(mock_client):
    route = respx.post(f"{BASE}/findings/4/tags/").mock(return_value=httpx.Response(200, json={"tags": ["web", "api"]}))
    result = await mock_client.add_finding_tags(4, ["web", "api"])
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["tags"] == ["web", "api"]


@pytest.mark.asyncio
@respx.mock
async def test_remove_finding_tags(mock_client):
    route = respx.put(f"{BASE}/findings/4/remove_tags/").mock(return_value=httpx.Response(200, json={"tags": []}))
    result = await mock_client.remove_finding_tags(4, ["web"])
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["tags"] == ["web"]


@pytest.mark.asyncio
@respx.mock
async def test_remove_finding_tags_empty_body_response(mock_client):
    """F-011: DefectDojo returns {} on successful tag removal; client must normalize
    to a tags-bearing dict so TagList validation does not fail on a successful call."""
    respx.put(f"{BASE}/findings/4/remove_tags/").mock(return_value=httpx.Response(200, json={}))
    result = await mock_client.remove_finding_tags(4, ["web"])
    assert result == {"tags": []}


@pytest.mark.asyncio
@respx.mock
async def test_get_finding_tags(mock_client):
    respx.get(f"{BASE}/findings/4/tags/").mock(return_value=httpx.Response(200, json={"tags": ["web"]}))
    result = await mock_client.get_finding_tags(4)
    assert result["tags"] == ["web"]


# ---------------------------------------------------------------------------
# Multipart upload — import_scan / reimport_scan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_import_scan_basic(mock_client):
    scan_result = {"test": 10, "test_id": 10, "findings_affected": 5}
    route = respx.post(url__regex=r".*/import-scan/").mock(return_value=httpx.Response(201, json=scan_result))
    result = await mock_client.import_scan(
        scan_type="Semgrep JSON Report",
        file=b"scan content",
        file_name="semgrep.json",
    )
    assert route.called
    assert result["test"] == 10
    assert result["findings_affected"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_import_scan_all_optional_params(mock_client):
    scan_result = {"test": 11, "test_id": 11, "findings_affected": 2}
    route = respx.post(url__regex=r".*/import-scan/").mock(return_value=httpx.Response(201, json=scan_result))
    result = await mock_client.import_scan(
        scan_type="Trivy Scan",
        file=b"trivy output",
        file_name="trivy.json",
        product_name="MyApp",
        engagement_name="CI Scan",
        product_type_name="Web Apps",
        minimum_severity="Medium",
        version="1.2.3",
        branch_tag="main",
        commit_hash="abc123",
        build_id="build-99",
        tags=["ci", "trivy"],
        group_by="component_name",
    )
    assert route.called
    req = route.calls.last.request
    # Multipart form data — check the request was sent
    assert result["test"] == 11


@pytest.mark.asyncio
@respx.mock
async def test_import_scan_sends_multipart_content_type(mock_client):
    """Regression for F-013: shared client carries Content-Type: application/json,
    which previously leaked into multipart POSTs and caused HTTP 415 from DefectDojo."""
    scan_result = {"test": 99, "test_id": 99, "findings_affected": 0}
    route = respx.post(url__regex=r".*/import-scan/").mock(return_value=httpx.Response(201, json=scan_result))
    await mock_client.import_scan(
        scan_type="Semgrep JSON Report",
        file=b"scan content",
        file_name="semgrep.json",
    )
    assert route.called
    sent_content_type = route.calls.last.request.headers.get("content-type", "")
    assert sent_content_type.startswith("multipart/form-data"), (
        f"expected multipart/form-data, got {sent_content_type!r}"
    )


@pytest.mark.asyncio
@respx.mock
async def test_import_scan_http_error(mock_client):
    respx.post(url__regex=r".*/import-scan/").mock(return_value=httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(RuntimeError, match="400"):
        await mock_client.import_scan(
            scan_type="ZAP Scan", file=b"data", file_name="zap.json",
        )


@pytest.mark.asyncio
@respx.mock
async def test_import_scan_connection_error(mock_client):
    respx.post(url__regex=r".*/import-scan/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="request failed"):
        await mock_client.import_scan(
            scan_type="ZAP Scan", file=b"data", file_name="zap.json",
        )


@pytest.mark.asyncio
@respx.mock
async def test_reimport_scan_basic(mock_client):
    scan_result = {"test": 12, "test_id": 12, "findings_affected": 3}
    route = respx.post(url__regex=r".*/reimport-scan/").mock(return_value=httpx.Response(201, json=scan_result))
    result = await mock_client.reimport_scan(
        scan_type="Semgrep JSON Report",
        file=b"scan content v2",
        file_name="semgrep.json",
    )
    assert route.called
    assert result["test"] == 12


@pytest.mark.asyncio
@respx.mock
async def test_reimport_scan_with_test_id(mock_client):
    scan_result = {"test": 12, "test_id": 12, "findings_affected": 1}
    route = respx.post(url__regex=r".*/reimport-scan/").mock(return_value=httpx.Response(201, json=scan_result))
    result = await mock_client.reimport_scan(
        scan_type="Trivy Scan",
        file=b"trivy v2",
        file_name="trivy.json",
        test_id=12,
        do_not_reactivate=True,
        product_name="MyApp",
        engagement_name="CI Scan",
        product_type_name="Web Apps",
        minimum_severity="High",
        version="2.0.0",
        branch_tag="release",
        commit_hash="def456",
        build_id="build-100",
        tags=["release"],
        group_by="component_name+component_version",
    )
    assert route.called
    assert result["findings_affected"] == 1


# ---------------------------------------------------------------------------
# Dual API key mode
# ---------------------------------------------------------------------------


def test_client_dual_key_init(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "https://dojo.local")
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key-123")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key-456")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    client = DefectDojoClient()
    assert client._dual_key_mode is True
    assert client._read_client is not client._write_client
    assert client._select_client("GET") is client._read_client
    assert client._select_client("POST") is client._write_client


def test_client_dual_key_missing_url(monkeypatch):
    monkeypatch.delenv("DEFECTDOJO_URL", raising=False)
    monkeypatch.setenv("DEFECTDOJO_READ_API_KEY", "read-key")
    monkeypatch.setenv("DEFECTDOJO_WRITE_API_KEY", "write-key")
    monkeypatch.delenv("DEFECTDOJO_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEFECTDOJO_URL"):
        DefectDojoClient()

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
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
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
    monkeypatch.setenv("DEFECTDOJO_URL", "http://admin:password@defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="embedded credentials"):
        DefectDojoClient()


def test_client_init_no_hostname(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with pytest.raises(ValueError, match="hostname"):
        DefectDojoClient()


def test_client_init_http_warns(monkeypatch, caplog):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "some-key")
    with caplog.at_level(logging.WARNING, logger="mcp_defectdojo.client"):
        DefectDojoClient()
    assert "cleartext" in caplog.text


@pytest.mark.asyncio
async def test_client_aclose(mock_client):
    await mock_client.aclose()


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
    assert "Not found" in str(exc_info.value)


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
    assert "Failed to connect" in str(exc_info.value)


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
    assert "Failed to connect" in str(exc_info.value)


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
    assert result["id"] == 11


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

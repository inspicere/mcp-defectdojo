import pytest
from unittest.mock import MagicMock
from mcp_defectdojo.client import DefectDojoClient


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "test-api-key-12345")


@pytest.fixture
def mock_client(mock_env):
    return DefectDojoClient()


@pytest.fixture
def sample_product():
    return {"id": 1, "name": "Test Product", "description": "A test product", "prod_type": 1}


@pytest.fixture
def sample_engagement():
    return {
        "id": 1,
        "product": 2,
        "name": "Test Engagement",
        "target_start": "2026-01-01",
        "target_end": "2026-12-31",
    }


@pytest.fixture
def sample_test_obj():
    return {"id": 1, "engagement": 3, "test_type": 1, "title": "Unit Test"}


@pytest.fixture
def sample_finding():
    return {
        "id": 1,
        "test": 4,
        "title": "XSS Vuln",
        "severity": "High",
        "description": "Found XSS",
        "active": True,
        "verified": False,
        "mitigated": None,
        "is_mitigated": False,
        "out_of_scope": False,
        "false_p": False,
        "duplicate": False,
    }


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.request_id = "test-request-id-1234"
    ctx.client_id = "test-client"
    ctx.request_context = MagicMock()
    return ctx


@pytest.fixture
def anonymous_ctx():
    ctx = MagicMock()
    ctx.request_id = "test-request-id-anon"
    ctx.client_id = None
    ctx.request_context = MagicMock()
    return ctx


def paginated_response(items, count=None):
    return {"count": count if count is not None else len(items), "results": items}

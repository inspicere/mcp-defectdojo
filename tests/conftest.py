import pytest
from unittest.mock import MagicMock
from mcp_defectdojo.client import DefectDojoClient
from mcp_defectdojo.security import MutationRateLimiter


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Replace both rate limiters with fresh, generously-sized instances per test.

    The default open-access limiter is 10 mutations / 60s — small enough that
    cross-test contamination quickly exhausts it. Each test gets a fresh state
    with limits high enough that no test inadvertently triggers a 429 unless
    it's specifically testing the limiter (those tests still patch directly).

    Tests that need a tighter limit must patch the limiter explicitly.
    """
    from mcp_defectdojo import server as server_module
    original_auth = server_module._mutation_limiter
    original_open = server_module._open_access_limiter
    server_module._mutation_limiter = MutationRateLimiter(max_mutations=10_000, window_seconds=60)
    server_module._open_access_limiter = MutationRateLimiter(max_mutations=10_000, window_seconds=60)
    try:
        yield
    finally:
        server_module._mutation_limiter = original_auth
        server_module._open_access_limiter = original_open


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("DEFECTDOJO_URL", "http://test.defectdojo.local")
    monkeypatch.setenv("DEFECTDOJO_API_KEY", "test-api-key-12345")
    monkeypatch.setenv("ALLOW_INSECURE_HTTP", "true")


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

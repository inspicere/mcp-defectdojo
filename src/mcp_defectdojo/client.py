import json
import logging
import os
from urllib.parse import urlparse
import httpx
from typing import Any, Optional

logger = logging.getLogger(__name__)

class DefectDojoClient:
    def __init__(self):
        self.base_url = os.environ.get("DEFECTDOJO_URL", "").rstrip("/")
        self.api_key = os.environ.get("DEFECTDOJO_API_KEY", "")

        if not self.base_url or not self.api_key:
            raise ValueError("DEFECTDOJO_URL and DEFECTDOJO_API_KEY must be set. Ensure load_dotenv() is called before creating the client.")

        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"DEFECTDOJO_URL must use http or https scheme, got '{parsed.scheme}'")
        if parsed.username or parsed.password:
            raise ValueError("DEFECTDOJO_URL must not contain embedded credentials")
        if not parsed.hostname:
            raise ValueError("DEFECTDOJO_URL must contain a valid hostname")
        if parsed.scheme == "http":
            logger.warning("DEFECTDOJO_URL uses HTTP — API key will be transmitted in cleartext", extra={"event_type": "security_warning"})

        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v2",
            headers=self.headers,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            logger.debug("API request", extra={"event_type": "api_request", "method": method, "path": path})
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            logger.debug("API response", extra={"event_type": "api_response", "method": method, "path": path, "status_code": response.status_code})
            if response.status_code != 204:
                return response.json()
            return {}
        except httpx.HTTPStatusError as e:
            logger.warning("API error", extra={"event_type": "api_error", "method": method, "path": path, "status_code": e.response.status_code})
            try:
                error_data = e.response.json()
                error_detail = error_data.get("detail", error_data)
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {json.dumps(error_detail)}")
            except (json.JSONDecodeError, ValueError):
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {e.response.text[:500]}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("Connection failed", extra={"event_type": "connection_error", "method": method, "path": path, "error": str(e)})
            raise RuntimeError(f"Failed to connect to DefectDojo: {e}")

    # Product Methods
    async def get_products(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/products/", params={"limit": limit, "offset": offset})

    async def get_product(self, product_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/products/{product_id}/")

    async def create_product(self, name: str, description: str, prod_type_id: int) -> dict[str, Any]:
        data = {
            "name": name,
            "description": description,
            "prod_type": prod_type_id
        }
        return await self._request("POST", "/products/", json=data)

    # Engagement Methods
    async def get_engagements(self, product_id: int, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/engagements/", params={"product": product_id, "limit": limit, "offset": offset})

    async def get_engagement(self, engagement_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/engagements/{engagement_id}/")

    async def create_engagement(self, product_id: int, name: str, target_start: str, target_end: str) -> dict[str, Any]:
        data = {
            "product": product_id,
            "name": name,
            "target_start": target_start,
            "target_end": target_end
        }
        return await self._request("POST", "/engagements/", json=data)

    # Test Methods
    async def get_tests(self, engagement_id: int, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/tests/", params={"engagement": engagement_id, "limit": limit, "offset": offset})

    async def get_test(self, test_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/tests/{test_id}/")

    async def create_test(self, engagement_id: int, test_type_id: int, target_start: str, target_end: str) -> dict[str, Any]:
        data = {
            "engagement": engagement_id,
            "test_type": test_type_id,
            "target_start": target_start,
            "target_end": target_end
        }
        return await self._request("POST", "/tests/", json=data)

    # Finding Methods
    async def get_findings(self, test_id: Optional[int] = None, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if test_id is not None:
            params["test"] = test_id
        return await self._request("GET", "/findings/", params=params)

    async def get_finding(self, finding_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/findings/{finding_id}/")

    _SEVERITY_TO_NUMERICAL = {
        "Critical": "S0", "High": "S1", "Medium": "S2", "Low": "S3", "Info": "S4",
    }

    async def create_finding(self, test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False) -> dict[str, Any]:
        data = {
            "test": test_id,
            "title": title,
            "severity": severity,
            "numerical_severity": self._SEVERITY_TO_NUMERICAL.get(severity, "S2"),
            "description": description,
            "active": active,
            "verified": verified,
            "found_by": [1],
        }
        return await self._request("POST", "/findings/", json=data)

    async def update_finding(self, finding_id: int, **kwargs: Any) -> dict[str, Any]:
        return await self._request("PATCH", f"/findings/{finding_id}/", json=kwargs)

import json
import logging
import os
import httpx
from typing import Any, Optional

logger = logging.getLogger(__name__)

class DefectDojoClient:
    def __init__(self):
        self.base_url = os.environ.get("DEFECTDOJO_URL", "").rstrip("/")
        self.api_key = os.environ.get("DEFECTDOJO_API_KEY", "")

        if not self.base_url or not self.api_key:
            raise ValueError("DEFECTDOJO_URL and DEFECTDOJO_API_KEY must be set. Ensure load_dotenv() is called before creating the client.")

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

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            if response.status_code != 204:
                return response.json()
            return {}
        except httpx.HTTPStatusError as e:
            try:
                error_data = json.loads(e.response.text)
                error_detail = error_data.get("detail", error_data)
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {json.dumps(error_detail)}")
            except json.JSONDecodeError:
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {e.response.text[:500]}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"Failed to connect to DefectDojo at {self.base_url}: {e}")

    # Product Methods
    async def get_products(self, limit: int = 20, offset: int = 0) -> Any:
        return await self._request("GET", "/products/", params={"limit": limit, "offset": offset})

    async def get_product(self, id: int) -> Any:
        return await self._request("GET", f"/products/{id}/")

    async def create_product(self, name: str, description: str, prod_type_id: int) -> Any:
        data = {
            "name": name,
            "description": description,
            "prod_type": prod_type_id
        }
        return await self._request("POST", "/products/", json=data)

    # Engagement Methods
    async def get_engagements(self, product_id: int, limit: int = 20, offset: int = 0) -> Any:
        return await self._request("GET", "/engagements/", params={"product": product_id, "limit": limit, "offset": offset})

    async def get_engagement(self, id: int) -> Any:
        return await self._request("GET", f"/engagements/{id}/")

    async def create_engagement(self, product_id: int, name: str, target_start: str, target_end: str) -> Any:
        data = {
            "product": product_id,
            "name": name,
            "target_start": target_start,
            "target_end": target_end
        }
        return await self._request("POST", "/engagements/", json=data)

    # Test Methods
    async def get_tests(self, engagement_id: int, limit: int = 20, offset: int = 0) -> Any:
        return await self._request("GET", "/tests/", params={"engagement": engagement_id, "limit": limit, "offset": offset})

    async def get_test(self, id: int) -> Any:
        return await self._request("GET", f"/tests/{id}/")

    async def create_test(self, engagement_id: int, test_type_id: int, target_start: str, target_end: str) -> Any:
        data = {
            "engagement": engagement_id,
            "test_type": test_type_id,
            "target_start": target_start,
            "target_end": target_end
        }
        return await self._request("POST", "/tests/", json=data)

    # Finding Methods
    async def get_findings(self, test_id: Optional[int] = None, limit: int = 20, offset: int = 0) -> Any:
        params = {"limit": limit, "offset": offset}
        if test_id is not None:
            params["test"] = test_id
        return await self._request("GET", "/findings/", params=params)

    async def get_finding(self, id: int) -> Any:
        return await self._request("GET", f"/findings/{id}/")

    async def create_finding(self, test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False) -> Any:
        data = {
            "test": test_id,
            "title": title,
            "severity": severity,
            "description": description,
            "active": active,
            "verified": verified
        }
        return await self._request("POST", "/findings/", json=data)

    async def update_finding(self, id: int, **kwargs) -> Any:
        return await self._request("PATCH", f"/findings/{id}/", json=kwargs)

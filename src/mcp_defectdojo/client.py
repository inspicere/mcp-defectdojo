import os
import httpx
from typing import Any, Dict, List
from dotenv import load_dotenv

load_dotenv()

class DefectDojoClient:
    def __init__(self):
        self.base_url = os.environ.get("DEFECTDOJO_URL", "").rstrip("/")
        self.api_key = os.environ.get("DEFECTDOJO_API_KEY", "")
        
        if not self.base_url or not self.api_key:
            # We'll let it pass here and fail on request if they aren't set, 
            # or maybe raise? The plan says "load from os.environ".
            pass

        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}/api/v2{path}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=self.headers, **kwargs)
                response.raise_for_status()
                if response.status_code != 204:
                    return response.json()
                return {}
        except httpx.HTTPStatusError as e:
            return f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
        except Exception as e:
            return f"An error occurred: {str(e)}"

    # Product Methods
    async def get_products(self) -> Any:
        return await self._request("GET", "/products/")

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
    async def get_engagements(self, product_id: int) -> Any:
        return await self._request("GET", "/engagements/", params={"product": product_id})

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
    async def get_tests(self, engagement_id: int) -> Any:
        return await self._request("GET", "/tests/", params={"engagement": engagement_id})

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

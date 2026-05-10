import json
import logging
import os
import time
from urllib.parse import urlparse
import httpx
from typing import Any, Optional
from .audit_logging import current_request_id

logger = logging.getLogger(__name__)


def _make_client(base_url: str, api_key: str) -> httpx.AsyncClient:
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return httpx.AsyncClient(
        base_url=f"{base_url}/api/v2",
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=5.0),
    )


class DefectDojoClient:
    def __init__(self):
        self.base_url = os.environ.get("DEFECTDOJO_URL", "").rstrip("/")

        read_key = os.environ.get("DEFECTDOJO_READ_API_KEY", "")
        write_key = os.environ.get("DEFECTDOJO_WRITE_API_KEY", "")
        single_key = os.environ.get("DEFECTDOJO_API_KEY", "")

        self._dual_key_mode = bool(read_key and write_key)

        if self._dual_key_mode:
            self.api_key = write_key
            if not self.base_url:
                raise ValueError("DEFECTDOJO_URL must be set. Ensure load_dotenv() is called before creating the client.")
        else:
            self.api_key = single_key
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
            allow_insecure = os.environ.get("ALLOW_INSECURE_HTTP", "").lower() == "true"
            if not allow_insecure:
                raise ValueError(
                    "DEFECTDOJO_URL uses http:// — TLS is required by default. "
                    "Set ALLOW_INSECURE_HTTP=true to allow insecure connections."
                )
            logger.critical("DEFECTDOJO_URL uses HTTP — API key will be transmitted in cleartext", extra={"event_type": "security_warning"})

        if self._dual_key_mode:
            self._read_client = _make_client(self.base_url, read_key)
            self._write_client = _make_client(self.base_url, write_key)
            self._client = self._write_client
            logger.info("Dual API key mode: separate read/write keys", extra={"event_type": "lifecycle"})
        else:
            self._client = _make_client(self.base_url, self.api_key)
            self._read_client = self._client
            self._write_client = self._client
            logger.info("Single API key mode", extra={"event_type": "lifecycle"})

    async def aclose(self) -> None:
        if self._dual_key_mode:
            await self._read_client.aclose()
            await self._write_client.aclose()
        else:
            await self._client.aclose()

    def _select_client(self, method: str) -> httpx.AsyncClient:
        if method in ("GET", "HEAD", "OPTIONS"):
            return self._read_client
        return self._write_client

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        request_id = current_request_id.get("")
        http_client = self._select_client(method)
        t0 = time.perf_counter()
        try:
            logger.debug("API request", extra={"event_type": "api_request", "method": method, "path": path, "request_id": request_id})
            response = await http_client.request(method, path, **kwargs)
            response.raise_for_status()
            api_duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.debug("API response", extra={"event_type": "api_response", "method": method, "path": path, "status_code": response.status_code, "request_id": request_id, "api_duration_ms": api_duration_ms})
            if response.status_code != 204:
                return response.json()
            return {}
        except httpx.HTTPStatusError as e:
            logger.warning("API error", extra={"event_type": "api_error", "method": method, "path": path, "status_code": e.response.status_code, "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            try:
                error_data = e.response.json()
                error_detail = error_data.get("detail", error_data)
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {json.dumps(error_detail)}")
            except (json.JSONDecodeError, ValueError):
                raise RuntimeError(f"DefectDojo API Error {e.response.status_code}: {e.response.text[:500]}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("Connection failed", extra={"event_type": "connection_error", "method": method, "path": path, "error": str(e), "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
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
    async def get_findings(
        self,
        test_id: Optional[int] = None,
        product_id: Optional[int] = None,
        engagement_id: Optional[int] = None,
        severity: Optional[str] = None,
        active: Optional[bool] = None,
        verified: Optional[bool] = None,
        duplicate: Optional[bool] = None,
        false_p: Optional[bool] = None,
        out_of_scope: Optional[bool] = None,
        is_mitigated: Optional[bool] = None,
        risk_accepted: Optional[bool] = None,
        has_jira: Optional[bool] = None,
        tags: Optional[list[str]] = None,
        outside_of_sla: Optional[bool] = None,
        component_name: Optional[str] = None,
        title: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if test_id is not None:
            params["test"] = test_id
        if product_id is not None:
            params["test__engagement__product"] = product_id
        if engagement_id is not None:
            params["test__engagement"] = engagement_id
        if severity is not None:
            params["severity"] = severity
        if active is not None:
            params["active"] = str(active).lower()
        if verified is not None:
            params["verified"] = str(verified).lower()
        if duplicate is not None:
            params["duplicate"] = str(duplicate).lower()
        if false_p is not None:
            params["false_p"] = str(false_p).lower()
        if out_of_scope is not None:
            params["out_of_scope"] = str(out_of_scope).lower()
        if is_mitigated is not None:
            params["is_mitigated"] = str(is_mitigated).lower()
        if risk_accepted is not None:
            params["risk_accepted"] = str(risk_accepted).lower()
        if has_jira is not None:
            params["has_jira_issue"] = str(has_jira).lower()
        if tags is not None:
            params["tags"] = ",".join(tags)
        if outside_of_sla is not None:
            params["outside_of_sla"] = str(outside_of_sla).lower()
        if component_name is not None:
            params["component_name"] = component_name
        if title is not None:
            params["title"] = title
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

    # Metadata Methods
    async def get_product_types(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/product_types/", params={"limit": limit, "offset": offset})

    async def get_test_types(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/test_types/", params={"limit": limit, "offset": offset})

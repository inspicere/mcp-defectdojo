import json
import logging
import os
import time
from urllib.parse import urlparse
import httpx
from typing import Any
from .audit_logging import current_request_id

logger = logging.getLogger(__name__)

_STATUS_MESSAGES = {
    400: "Invalid request parameters",
    401: "Authentication failed",
    403: "Insufficient permissions",
    404: "Resource not found",
    405: "Method not allowed",
    409: "Conflict with current state",
    429: "Rate limit exceeded",
}


def _sanitize_api_error(exc: "httpx.HTTPStatusError", request_id: str) -> str:
    status = exc.response.status_code
    try:
        detail = exc.response.json()
    except Exception:
        detail = exc.response.text[:500]
    logger.debug("API error detail", extra={
        "event_type": "api_error_detail",
        "status_code": status,
        "detail": detail,
        "request_id": request_id,
    })
    label = _STATUS_MESSAGES.get(status, "Request failed")
    if status >= 500:
        label = "DefectDojo server error"
    return f"{label} (HTTP {status}, request_id={request_id})"


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
            raise RuntimeError(_sanitize_api_error(e, request_id))
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("Connection failed", extra={"event_type": "connection_error", "method": method, "path": path, "error": str(e), "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            raise RuntimeError(f"DefectDojo request failed (request_id={request_id})")
        except httpx.HTTPError as e:
            logger.error("HTTP error", extra={"event_type": "connection_error", "method": method, "path": path, "error": type(e).__name__, "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            raise RuntimeError(f"DefectDojo request failed (request_id={request_id})")

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
        test_id: int | None = None,
        product_id: int | None = None,
        engagement_id: int | None = None,
        severity: str | None = None,
        active: bool | None = None,
        verified: bool | None = None,
        duplicate: bool | None = None,
        false_p: bool | None = None,
        out_of_scope: bool | None = None,
        is_mitigated: bool | None = None,
        risk_accepted: bool | None = None,
        has_jira: bool | None = None,
        tags: list[str] | None = None,
        outside_of_sla: bool | None = None,
        component_name: str | None = None,
        title: str | None = None,
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

    async def close_finding(self, finding_id: int, is_mitigated: bool = True, false_p: bool = False, out_of_scope: bool = False, duplicate: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"active": False, "is_mitigated": is_mitigated}
        if false_p:
            data["false_p"] = True
            data["is_mitigated"] = False
        if out_of_scope:
            data["out_of_scope"] = True
            data["is_mitigated"] = False
        if duplicate:
            data["duplicate"] = True
            data["is_mitigated"] = False
        return await self._request("PATCH", f"/findings/{finding_id}/", json=data)

    async def add_finding_note(self, finding_id: int, entry: str, note_type: int | None = None, private: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"entry": entry, "private": private}
        if note_type is not None:
            data["note_type"] = note_type
        return await self._request("POST", f"/findings/{finding_id}/notes/", json=data)

    async def get_finding_notes(self, finding_id: int) -> list[dict[str, Any]]:
        result = await self._request("GET", f"/findings/{finding_id}/notes/")
        if isinstance(result, list):
            return result
        return result.get("results", [result])

    async def add_finding_tags(self, finding_id: int, tags: list[str]) -> dict[str, Any]:
        return await self._request("POST", f"/findings/{finding_id}/tags/", json={"tags": tags})

    async def remove_finding_tags(self, finding_id: int, tags: list[str]) -> dict[str, Any]:
        return await self._request("PUT", f"/findings/{finding_id}/remove_tags/", json={"tags": tags})

    async def get_finding_tags(self, finding_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/findings/{finding_id}/tags/")

    # Metadata Methods
    async def get_product_types(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/product_types/", params={"limit": limit, "offset": offset})

    async def get_test_types(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/test_types/", params={"limit": limit, "offset": offset})

    # Multipart upload support
    async def _multipart_request(self, path: str, data: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
        """POST multipart form data using the write client, without the default Content-Type header.

        httpx needs to set the multipart boundary itself, so we build a
        one-off request that copies auth/accept headers but omits Content-Type.
        """
        request_id = current_request_id.get("")
        http_client = self._write_client
        t0 = time.perf_counter()
        # Build headers without Content-Type so httpx sets the multipart boundary
        headers = {
            "Authorization": http_client.headers["authorization"],
            "Accept": "application/json",
        }
        try:
            url = f"{http_client.base_url}{path}"
            logger.debug("API multipart request", extra={"event_type": "api_request", "method": "POST", "path": path, "request_id": request_id})
            response = await http_client.post(url, data=data, files=files, headers=headers)
            response.raise_for_status()
            api_duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.debug("API response", extra={"event_type": "api_response", "method": "POST", "path": path, "status_code": response.status_code, "request_id": request_id, "api_duration_ms": api_duration_ms})
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning("API error", extra={"event_type": "api_error", "method": "POST", "path": path, "status_code": e.response.status_code, "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            raise RuntimeError(_sanitize_api_error(e, request_id))
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("Connection failed", extra={"event_type": "connection_error", "method": "POST", "path": path, "error": str(e), "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            raise RuntimeError(f"DefectDojo request failed (request_id={request_id})")
        except httpx.HTTPError as e:
            logger.error("HTTP error", extra={"event_type": "connection_error", "method": "POST", "path": path, "error": type(e).__name__, "request_id": request_id, "api_duration_ms": round((time.perf_counter() - t0) * 1000, 2)})
            raise RuntimeError(f"DefectDojo request failed (request_id={request_id})")

    # Scan Import Methods
    @staticmethod
    def _build_scan_data(
        scan_type: str,
        auto_create_context: bool,
        close_old_findings: bool,
        deduplication_on_engagement: bool,
        active: bool,
        verified: bool,
        push_to_jira: bool,
        product_name: str | None,
        engagement_name: str | None,
        product_type_name: str | None,
        minimum_severity: str | None,
        version: str | None,
        branch_tag: str | None,
        commit_hash: str | None,
        build_id: str | None,
        tags: list[str] | None,
        group_by: str | None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "scan_type": scan_type,
            "auto_create_context": str(auto_create_context),
            "close_old_findings": str(close_old_findings),
            "deduplication_on_engagement": str(deduplication_on_engagement),
            "active": str(active),
            "verified": str(verified),
            "push_to_jira": str(push_to_jira),
        }
        for key, val in [
            ("product_name", product_name), ("engagement_name", engagement_name),
            ("product_type_name", product_type_name), ("minimum_severity", minimum_severity),
            ("version", version), ("branch_tag", branch_tag), ("commit_hash", commit_hash),
            ("build_id", build_id), ("tags", tags), ("group_by", group_by),
        ]:
            if val is not None:
                data[key] = val
        return data

    async def import_scan(
        self,
        scan_type: str,
        file: bytes,
        file_name: str,
        product_name: str | None = None,
        engagement_name: str | None = None,
        auto_create_context: bool = True,
        close_old_findings: bool = True,
        deduplication_on_engagement: bool = True,
        product_type_name: str | None = None,
        active: bool = True,
        verified: bool = False,
        minimum_severity: str | None = None,
        push_to_jira: bool = False,
        version: str | None = None,
        branch_tag: str | None = None,
        commit_hash: str | None = None,
        build_id: str | None = None,
        tags: list[str] | None = None,
        group_by: str | None = None,
    ) -> dict[str, Any]:
        data = self._build_scan_data(
            scan_type, auto_create_context, close_old_findings,
            deduplication_on_engagement, active, verified, push_to_jira,
            product_name, engagement_name, product_type_name, minimum_severity,
            version, branch_tag, commit_hash, build_id, tags, group_by,
        )
        files = {"file": (file_name, file, "application/octet-stream")}
        return await self._multipart_request("/import-scan/", data=data, files=files)

    async def reimport_scan(
        self,
        scan_type: str,
        file: bytes,
        file_name: str,
        product_name: str | None = None,
        engagement_name: str | None = None,
        auto_create_context: bool = True,
        close_old_findings: bool = True,
        deduplication_on_engagement: bool = True,
        product_type_name: str | None = None,
        active: bool = True,
        verified: bool = False,
        minimum_severity: str | None = None,
        push_to_jira: bool = False,
        version: str | None = None,
        branch_tag: str | None = None,
        commit_hash: str | None = None,
        build_id: str | None = None,
        tags: list[str] | None = None,
        group_by: str | None = None,
        test_id: int | None = None,
        do_not_reactivate: bool = False,
    ) -> dict[str, Any]:
        data = self._build_scan_data(
            scan_type, auto_create_context, close_old_findings,
            deduplication_on_engagement, active, verified, push_to_jira,
            product_name, engagement_name, product_type_name, minimum_severity,
            version, branch_tag, commit_hash, build_id, tags, group_by,
        )
        data["do_not_reactivate"] = str(do_not_reactivate)
        if test_id is not None:
            data["test"] = str(test_id)
        files = {"file": (file_name, file, "application/octet-stream")}
        return await self._multipart_request("/reimport-scan/", data=data, files=files)

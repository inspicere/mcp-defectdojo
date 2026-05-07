import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from pydantic import ValidationError
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary, SeverityEnum, PaginationMetadata

client: DefectDojoClient | None = None

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastMCP):
    global client
    load_dotenv()
    try:
        client = DefectDojoClient()
        logger.info("DefectDojo client initialized: %s", client.base_url)
        yield {}
    except ValueError as e:
        logger.error("Failed to initialize DefectDojo client: %s", e)
        raise
    finally:
        if client is not None:
            await client.aclose()
            logger.info("DefectDojo client closed")


mcp = FastMCP("mcp-defectdojo", lifespan=lifespan)

VALID_SEVERITIES = [s.value for s in SeverityEnum]

def _format_response(result: dict[str, Any], model: type, offset: int = 0, limit: int = 20) -> str:
    if "results" in result:
        try:
            items = [model(**item).model_dump() for item in result["results"]]
        except ValidationError as e:
            return f"ERROR: Invalid API response data: {str(e)}"
        pagination = PaginationMetadata(
            count=result.get("count", len(items)),
            offset=offset,
            limit=limit,
            has_next=(offset + limit) < result.get("count", 0),
        ).model_dump()
        return json.dumps({"items": items, "pagination": pagination}, indent=2)
    else:
        try:
            return json.dumps(model(**result).model_dump(), indent=2)
        except ValidationError as e:
            return f"ERROR: Invalid API response data: {str(e)}"

@mcp.tool()
async def health_check() -> str:
    """Check connectivity to the DefectDojo instance. Returns 'OK: DefectDojo is reachable' or 'UNHEALTHY: <reason>'."""
    if client is None:
        return "UNHEALTHY: DefectDojo client not initialized — server may not have started correctly"
    try:
        await client.get_products(limit=1)
        return "OK: DefectDojo is reachable"
    except Exception as e:
        return f"UNHEALTHY: {e}"

# --- Product Tools ---

@mcp.tool()
async def list_products(limit: int = 20, offset: int = 0) -> str:
    """List products in DefectDojo. Args: limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_products(limit=limit, offset=offset)
    return _format_response(res, ProductSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_product(product_id: int) -> str:
    """Get a single product by ID. Args: product_id (must be > 0). Returns JSON with id, name, description, prod_type fields."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if product_id <= 0:
        return f"ERROR: product_id must be > 0, got {product_id}"
    res = await client.get_product(product_id)
    return _format_response(res, ProductSummary)

@mcp.tool()
async def create_product(name: str, description: str, prod_type_id: int) -> str:
    """Create a new product. Args: name, description, prod_type_id (must be > 0). Returns JSON with created product."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if prod_type_id <= 0:
        return f"ERROR: prod_type_id must be > 0, got {prod_type_id}"
    logger.info("Creating product: name=%s, prod_type_id=%d", name, prod_type_id)
    res = await client.create_product(name, description, prod_type_id)
    return _format_response(res, ProductSummary)

# --- Engagement Tools ---

@mcp.tool()
async def list_engagements(product_id: int, limit: int = 20, offset: int = 0) -> str:
    """List engagements for a product. Args: product_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if product_id <= 0:
        return f"ERROR: product_id must be > 0, got {product_id}"
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_engagements(product_id, limit=limit, offset=offset)
    return _format_response(res, EngagementSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_engagement(engagement_id: int) -> str:
    """Get a single engagement by ID. Args: engagement_id (must be > 0). Returns JSON with engagement fields."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if engagement_id <= 0:
        return f"ERROR: engagement_id must be > 0, got {engagement_id}"
    res = await client.get_engagement(engagement_id)
    return _format_response(res, EngagementSummary)

@mcp.tool()
async def create_engagement(product_id: int, name: str, target_start: str, target_end: str) -> str:
    """Create a new engagement. Args: product_id (> 0), name, target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created engagement."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if product_id <= 0:
        return f"ERROR: product_id must be > 0, got {product_id}"
    logger.info("Creating engagement: product_id=%d, name=%s", product_id, name)
    res = await client.create_engagement(product_id, name, target_start, target_end)
    return _format_response(res, EngagementSummary)

# --- Test Tools ---

@mcp.tool()
async def list_tests(engagement_id: int, limit: int = 20, offset: int = 0) -> str:
    """List tests for an engagement. Args: engagement_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if engagement_id <= 0:
        return f"ERROR: engagement_id must be > 0, got {engagement_id}"
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_tests(engagement_id, limit=limit, offset=offset)
    return _format_response(res, TestSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_test(test_id: int) -> str:
    """Get a single test by ID. Args: test_id (must be > 0). Returns JSON with test fields."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if test_id <= 0:
        return f"ERROR: test_id must be > 0, got {test_id}"
    res = await client.get_test(test_id)
    return _format_response(res, TestSummary)

@mcp.tool()
async def create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str) -> str:
    """Create a new test. Args: engagement_id (> 0), test_type_id (> 0), target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created test."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if engagement_id <= 0:
        return f"ERROR: engagement_id must be > 0, got {engagement_id}"
    if test_type_id <= 0:
        return f"ERROR: test_type_id must be > 0, got {test_type_id}"
    logger.info("Creating test: engagement_id=%d, test_type_id=%d", engagement_id, test_type_id)
    res = await client.create_test(engagement_id, test_type_id, target_start, target_end)
    return _format_response(res, TestSummary)

# --- Finding Tools ---

@mcp.tool()
async def list_findings(test_id: Optional[int] = None, limit: int = 20, offset: int = 0) -> str:
    """List findings, optionally filtered by test. Args: test_id (optional, > 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if test_id is not None and test_id <= 0:
        return f"ERROR: test_id must be > 0, got {test_id}"
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_findings(test_id, limit=limit, offset=offset)
    return _format_response(res, FindingSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_finding(finding_id: int) -> str:
    """Get a single finding by ID. Args: finding_id (must be > 0). Returns JSON with finding fields."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if finding_id <= 0:
        return f"ERROR: finding_id must be > 0, got {finding_id}"
    res = await client.get_finding(finding_id)
    return _format_response(res, FindingSummary)

@mcp.tool()
async def create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False) -> str:
    """Create a new finding. Args: test_id (> 0), title, severity (Critical/High/Medium/Low/Info), description, active (default true), verified (default false). Returns JSON with created finding."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if test_id <= 0:
        return f"ERROR: test_id must be > 0, got {test_id}"
    if severity not in VALID_SEVERITIES:
        return f"ERROR: severity must be one of {VALID_SEVERITIES}, got '{severity}'"
    logger.info("Creating finding: test_id=%d, title=%s, severity=%s", test_id, title, severity)
    res = await client.create_finding(test_id, title, severity, description, active, verified)
    return _format_response(res, FindingSummary)

@mcp.tool()
async def update_finding(
    finding_id: int,
    title: Optional[str] = None,
    severity: Optional[str] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None,
    verified: Optional[bool] = None,
    false_p: Optional[bool] = None,
    duplicate: Optional[bool] = None,
    out_of_scope: Optional[bool] = None,
    is_mitigated: Optional[bool] = None
) -> str:
    """Update an existing finding. Args: finding_id (> 0), plus optional: title, severity (Critical/High/Medium/Low/Info), description, active, verified, false_p, duplicate, out_of_scope, is_mitigated. At least one field required. Returns JSON with updated finding."""
    if client is None:
        return "ERROR: DefectDojo client not initialized — server may not have started correctly"
    if finding_id <= 0:
        return f"ERROR: finding_id must be > 0, got {finding_id}"
    # Filter out None values to only send updated fields
    kwargs = {k: v for k, v in locals().items() if k != 'finding_id' and v is not None}
    if not kwargs:
        return "ERROR: No fields to update. Specify at least one field to change."
    if "severity" in kwargs:
        if kwargs["severity"] not in VALID_SEVERITIES:
            return f"ERROR: severity must be one of {VALID_SEVERITIES}, got '{kwargs['severity']}'"
    logger.info("Updating finding: finding_id=%d, fields=%s", finding_id, list(kwargs.keys()))
    res = await client.update_finding(finding_id, **kwargs)
    return _format_response(res, FindingSummary)

def main():
    mcp.run()

if __name__ == "__main__":
    main()

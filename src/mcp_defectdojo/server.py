import json
from contextlib import asynccontextmanager
from typing import Any, Optional

from pydantic import ValidationError
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary, SeverityEnum, PaginationMetadata

client: DefectDojoClient | None = None


@asynccontextmanager
async def lifespan(app: FastMCP):
    global client
    load_dotenv()
    client = DefectDojoClient()
    try:
        yield {}
    finally:
        await client._client.aclose()


mcp = FastMCP("mcp-defectdojo", lifespan=lifespan)

def _format_response(result: dict[str, Any], model: type, offset: int = 0, limit: int = 20) -> str:
    if "results" in result:
        try:
            items = [model(**item).model_dump() for item in result["results"]]
        except ValidationError as e:
            return f"ERROR: Invalid API response data: {e.errors()[0]['msg']}"
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
            return f"ERROR: Invalid API response data: {e.errors()[0]['msg']}"

@mcp.tool()
async def health_check() -> str:
    """Check connectivity to the DefectDojo instance."""
    try:
        await client.get_products(limit=1)
        return "OK: DefectDojo is reachable"
    except Exception as e:
        return f"UNHEALTHY: {e}"

# --- Product Tools ---

@mcp.tool()
async def list_products(limit: int = 20, offset: int = 0) -> str:
    """List products in DefectDojo. Use limit and offset for pagination."""
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_products(limit=limit, offset=offset)
    return _format_response(res, ProductSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_product(product_id: int) -> str:
    """Get a product from DefectDojo by ID."""
    if product_id <= 0:
        return f"ERROR: product_id must be > 0, got {product_id}"
    res = await client.get_product(product_id)
    return _format_response(res, ProductSummary)

@mcp.tool()
async def create_product(name: str, description: str, prod_type_id: int) -> str:
    """Create a new product in DefectDojo."""
    if prod_type_id <= 0:
        return f"ERROR: prod_type_id must be > 0, got {prod_type_id}"
    res = await client.create_product(name, description, prod_type_id)
    return _format_response(res, ProductSummary)

# --- Engagement Tools ---

@mcp.tool()
async def list_engagements(product_id: int, limit: int = 20, offset: int = 0) -> str:
    """List engagements for a specific product in DefectDojo. Use limit and offset for pagination."""
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_engagements(product_id, limit=limit, offset=offset)
    return _format_response(res, EngagementSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_engagement(engagement_id: int) -> str:
    """Get an engagement from DefectDojo by ID."""
    if engagement_id <= 0:
        return f"ERROR: engagement_id must be > 0, got {engagement_id}"
    res = await client.get_engagement(engagement_id)
    return _format_response(res, EngagementSummary)

@mcp.tool()
async def create_engagement(product_id: int, name: str, target_start: str, target_end: str) -> str:
    """Create a new engagement in DefectDojo."""
    if product_id <= 0:
        return f"ERROR: product_id must be > 0, got {product_id}"
    res = await client.create_engagement(product_id, name, target_start, target_end)
    return _format_response(res, EngagementSummary)

# --- Test Tools ---

@mcp.tool()
async def list_tests(engagement_id: int, limit: int = 20, offset: int = 0) -> str:
    """List tests for a specific engagement in DefectDojo. Use limit and offset for pagination."""
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_tests(engagement_id, limit=limit, offset=offset)
    return _format_response(res, TestSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_test(test_id: int) -> str:
    """Get a test from DefectDojo by ID."""
    if test_id <= 0:
        return f"ERROR: test_id must be > 0, got {test_id}"
    res = await client.get_test(test_id)
    return _format_response(res, TestSummary)

@mcp.tool()
async def create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str) -> str:
    """Create a new test in DefectDojo."""
    if engagement_id <= 0:
        return f"ERROR: engagement_id must be > 0, got {engagement_id}"
    res = await client.create_test(engagement_id, test_type_id, target_start, target_end)
    return _format_response(res, TestSummary)

# --- Finding Tools ---

@mcp.tool()
async def list_findings(test_id: Optional[int] = None, limit: int = 20, offset: int = 0) -> str:
    """List findings in DefectDojo, optionally filtered by test ID. Use limit and offset for pagination."""
    if not 1 <= limit <= 100:
        return f"ERROR: limit must be between 1 and 100, got {limit}"
    if offset < 0:
        return f"ERROR: offset must be >= 0, got {offset}"
    res = await client.get_findings(test_id, limit=limit, offset=offset)
    return _format_response(res, FindingSummary, offset=offset, limit=limit)

@mcp.tool()
async def get_finding(finding_id: int) -> str:
    """Get a finding from DefectDojo by ID."""
    if finding_id <= 0:
        return f"ERROR: finding_id must be > 0, got {finding_id}"
    res = await client.get_finding(finding_id)
    return _format_response(res, FindingSummary)

@mcp.tool()
async def create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False) -> str:
    """Create a new finding in DefectDojo."""
    valid_severities = [s.value for s in SeverityEnum]
    if severity not in valid_severities:
        return f"ERROR: severity must be one of {valid_severities}, got '{severity}'"
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
    """Update an existing finding in DefectDojo."""
    if finding_id <= 0:
        return f"ERROR: finding_id must be > 0, got {finding_id}"
    # Filter out None values to only send updated fields
    kwargs = {k: v for k, v in locals().items() if k != 'finding_id' and v is not None}
    if not kwargs:
        return "ERROR: No fields to update. Specify at least one field to change."
    if "severity" in kwargs:
        valid_severities = [s.value for s in SeverityEnum]
        if kwargs["severity"] not in valid_severities:
            return f"ERROR: severity must be one of {valid_severities}, got '{kwargs['severity']}'"
    res = await client.update_finding(finding_id, **kwargs)
    return _format_response(res, FindingSummary)

def main():
    mcp.run()

if __name__ == "__main__":
    main()

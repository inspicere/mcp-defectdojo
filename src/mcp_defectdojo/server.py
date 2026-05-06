import json
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary

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

def _format_response(result, model):
    if isinstance(result, str):
        return result
    if "results" in result:
        # It's a paginated list
        return json.dumps([model(**item).model_dump() for item in result["results"]], indent=2)
    else:
        # It's a single item
        return json.dumps(model(**result).model_dump(), indent=2)

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
    res = await client.get_products(limit=limit, offset=offset)
    return _format_response(res, ProductSummary)

@mcp.tool()
async def get_product(product_id: int) -> str:
    """Get a product from DefectDojo by ID."""
    res = await client.get_product(product_id)
    return _format_response(res, ProductSummary)

@mcp.tool()
async def create_product(name: str, description: str, prod_type_id: int) -> str:
    """Create a new product in DefectDojo."""
    res = await client.create_product(name, description, prod_type_id)
    return _format_response(res, ProductSummary)

# --- Engagement Tools ---

@mcp.tool()
async def list_engagements(product_id: int, limit: int = 20, offset: int = 0) -> str:
    """List engagements for a specific product in DefectDojo. Use limit and offset for pagination."""
    res = await client.get_engagements(product_id, limit=limit, offset=offset)
    return _format_response(res, EngagementSummary)

@mcp.tool()
async def get_engagement(engagement_id: int) -> str:
    """Get an engagement from DefectDojo by ID."""
    res = await client.get_engagement(engagement_id)
    return _format_response(res, EngagementSummary)

@mcp.tool()
async def create_engagement(product_id: int, name: str, target_start: str, target_end: str) -> str:
    """Create a new engagement in DefectDojo."""
    res = await client.create_engagement(product_id, name, target_start, target_end)
    return _format_response(res, EngagementSummary)

# --- Test Tools ---

@mcp.tool()
async def list_tests(engagement_id: int, limit: int = 20, offset: int = 0) -> str:
    """List tests for a specific engagement in DefectDojo. Use limit and offset for pagination."""
    res = await client.get_tests(engagement_id, limit=limit, offset=offset)
    return _format_response(res, TestSummary)

@mcp.tool()
async def get_test(test_id: int) -> str:
    """Get a test from DefectDojo by ID."""
    res = await client.get_test(test_id)
    return _format_response(res, TestSummary)

@mcp.tool()
async def create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str) -> str:
    """Create a new test in DefectDojo."""
    res = await client.create_test(engagement_id, test_type_id, target_start, target_end)
    return _format_response(res, TestSummary)

# --- Finding Tools ---

@mcp.tool()
async def list_findings(test_id: Optional[int] = None, limit: int = 20, offset: int = 0) -> str:
    """List findings in DefectDojo, optionally filtered by test ID. Use limit and offset for pagination."""
    res = await client.get_findings(test_id, limit=limit, offset=offset)
    return _format_response(res, FindingSummary)

@mcp.tool()
async def get_finding(finding_id: int) -> str:
    """Get a finding from DefectDojo by ID."""
    res = await client.get_finding(finding_id)
    return _format_response(res, FindingSummary)

@mcp.tool()
async def create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False) -> str:
    """Create a new finding in DefectDojo."""
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
    # Filter out None values to only send updated fields
    kwargs = {k: v for k, v in locals().items() if k != 'finding_id' and v is not None}

    res = await client.update_finding(finding_id, **kwargs)
    return _format_response(res, FindingSummary)

def main():
    mcp.run()

if __name__ == "__main__":
    main()

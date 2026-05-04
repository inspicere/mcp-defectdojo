import os
import json
from mcp.server.fastmcp import FastMCP
from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary

mcp = FastMCP("mcp-defectdojo")
client = DefectDojoClient()

def _format_response(result, model):
    if isinstance(result, str):
        return result
    if "results" in result:
        # It's a paginated list
        return json.dumps([model(**item).model_dump() for item in result["results"]], indent=2)
    else:
        # It's a single item
        return json.dumps(model(**result).model_dump(), indent=2)

# --- Product Tools ---

@mcp.tool()
async def list_products() -> str:
    """List products in DefectDojo."""
    res = await client.get_products()
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
async def list_engagements(product_id: int) -> str:
    """List engagements for a specific product in DefectDojo."""
    res = await client.get_engagements(product_id)
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
async def list_tests(engagement_id: int) -> str:
    """List tests for a specific engagement in DefectDojo."""
    res = await client.get_tests(engagement_id)
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

def main():
    mcp.run()

if __name__ == "__main__":
    main()

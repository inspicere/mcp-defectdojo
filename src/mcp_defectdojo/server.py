import functools
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Optional

from pydantic import ValidationError
from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.authorization import AuthCheck, AuthContext

from .audit_logging import configure_logging, audit_tool, _session_counter
from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary, SeverityEnum, PaginationMetadata
from .security import MutationRateLimiter, validate_field_length, MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH, MAX_NAME_LENGTH

client: DefectDojoClient | None = None

logger = logging.getLogger(__name__)


def scope_check(scope: str) -> AuthCheck:
    """Require an MCP scope when auth is configured; allow all when it isn't."""
    def check(ctx: AuthContext) -> bool:
        if ctx.token is None:
            return True
        return scope in ctx.token.scopes
    return check


def _build_auth():
    load_dotenv()
    tokens = {}
    auth_token = os.environ.get("MCP_AUTH_TOKEN")
    if auth_token:
        tokens[auth_token] = {"client_id": "mcp-client", "scopes": ["read", "write"]}
    read_token = os.environ.get("MCP_READ_TOKEN")
    if read_token:
        tokens[read_token] = {"client_id": "mcp-read-client", "scopes": ["read"]}
    if not tokens:
        return None
    from fastmcp.server.auth import StaticTokenVerifier
    return StaticTokenVerifier(tokens=tokens)


def _require_client(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if client is None:
            raise ToolError("DefectDojo client not initialized — server may not have started correctly")
        return await func(*args, **kwargs)
    return wrapper


@asynccontextmanager
async def lifespan(app: FastMCP):
    global client
    load_dotenv()
    try:
        configure_logging()
        client = DefectDojoClient()
        logger.info("DefectDojo client initialized", extra={"event_type": "lifecycle", "base_url": client.base_url})
        yield {}
    except ValueError as e:
        logger.error("Failed to initialize DefectDojo client", extra={"event_type": "lifecycle", "error": str(e)})
        raise
    finally:
        summary = _session_counter.summary()
        logger.info("Session shutdown", extra={"event_type": "lifecycle", "session_summary": summary})
        if client is not None:
            await client.aclose()
            client = None
            logger.info("DefectDojo client closed", extra={"event_type": "lifecycle"})


mcp = FastMCP("mcp-defectdojo", lifespan=lifespan, auth=_build_auth())

VALID_SEVERITIES = frozenset(s.value for s in SeverityEnum)
VALID_SEVERITIES_LIST = sorted(VALID_SEVERITIES)

_mutation_limiter = MutationRateLimiter(
    max_mutations=int(os.environ.get("MUTATION_RATE_LIMIT", "60")),
    window_seconds=int(os.environ.get("MUTATION_RATE_WINDOW", "60")),
)

def _format_response(result: dict[str, Any], model: type, offset: int = 0, limit: int = 20) -> str:
    if "results" in result:
        try:
            items = [model(**item).model_dump() for item in result["results"]]
        except ValidationError as e:
            raise ToolError(f"Invalid API response data: {str(e)}")
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
            raise ToolError(f"Invalid API response data: {str(e)}")


def _validate_pagination(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise ToolError(f"limit must be between 1 and 100, got {limit}")
    if offset < 0:
        raise ToolError(f"offset must be >= 0, got {offset}")


def _validate_date(value: str, field_name: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{field_name} must be a valid YYYY-MM-DD date, got '{value}'")


def _caller_id(ctx: Context | None) -> str:
    if ctx is None:
        return "anonymous"
    try:
        return ctx.client_id or "anonymous"
    except (RuntimeError, AttributeError):
        return "anonymous"


@mcp.tool(auth=scope_check("read"))
@audit_tool
async def health_check(ctx: Context = None) -> str:
    """Check connectivity to the DefectDojo instance. Returns 'OK: DefectDojo is reachable' or 'UNHEALTHY: <reason>'."""
    if client is None:
        return "UNHEALTHY: DefectDojo client not initialized — server may not have started correctly"
    try:
        await client.get_products(limit=1)
        return "OK: DefectDojo is reachable"
    except Exception as e:
        return f"UNHEALTHY: {e}"

# --- Product Tools ---

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def list_products(limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List products in DefectDojo. Args: limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    _validate_pagination(limit, offset)
    try:
        res = await client.get_products(limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ProductSummary, offset=offset, limit=limit)

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def get_product(product_id: int, ctx: Context = None) -> str:
    """Get a single product by ID. Args: product_id (must be > 0). Returns JSON with id, name, description, prod_type fields."""
    if product_id <= 0:
        raise ToolError(f"product_id must be > 0, got {product_id}")
    try:
        res = await client.get_product(product_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ProductSummary)

@mcp.tool(auth=scope_check("write"))
@audit_tool
@_require_client
async def create_product(name: str, description: str, prod_type_id: int, ctx: Context = None) -> str:
    """Create a new product. Args: name, description, prod_type_id (must be > 0). Returns JSON with created product."""
    if prod_type_id <= 0:
        raise ToolError(f"prod_type_id must be > 0, got {prod_type_id}")
    validate_field_length(name, "name", MAX_NAME_LENGTH)
    validate_field_length(description, "description", MAX_DESCRIPTION_LENGTH)
    await _mutation_limiter.check(_caller_id(ctx))
    try:
        res = await client.create_product(name, description, prod_type_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ProductSummary)

# --- Engagement Tools ---

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def list_engagements(product_id: int, limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List engagements for a product. Args: product_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if product_id <= 0:
        raise ToolError(f"product_id must be > 0, got {product_id}")
    _validate_pagination(limit, offset)
    try:
        res = await client.get_engagements(product_id, limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, EngagementSummary, offset=offset, limit=limit)

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def get_engagement(engagement_id: int, ctx: Context = None) -> str:
    """Get a single engagement by ID. Args: engagement_id (must be > 0). Returns JSON with engagement fields."""
    if engagement_id <= 0:
        raise ToolError(f"engagement_id must be > 0, got {engagement_id}")
    try:
        res = await client.get_engagement(engagement_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, EngagementSummary)

@mcp.tool(auth=scope_check("write"))
@audit_tool
@_require_client
async def create_engagement(product_id: int, name: str, target_start: str, target_end: str, ctx: Context = None) -> str:
    """Create a new engagement. Args: product_id (> 0), name, target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created engagement."""
    if product_id <= 0:
        raise ToolError(f"product_id must be > 0, got {product_id}")
    validate_field_length(name, "name", MAX_NAME_LENGTH)
    _validate_date(target_start, "target_start")
    _validate_date(target_end, "target_end")
    await _mutation_limiter.check(_caller_id(ctx))
    try:
        res = await client.create_engagement(product_id, name, target_start, target_end)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, EngagementSummary)

# --- Test Tools ---

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def list_tests(engagement_id: int, limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List tests for an engagement. Args: engagement_id (> 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if engagement_id <= 0:
        raise ToolError(f"engagement_id must be > 0, got {engagement_id}")
    _validate_pagination(limit, offset)
    try:
        res = await client.get_tests(engagement_id, limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TestSummary, offset=offset, limit=limit)

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def get_test(test_id: int, ctx: Context = None) -> str:
    """Get a single test by ID. Args: test_id (must be > 0). Returns JSON with test fields."""
    if test_id <= 0:
        raise ToolError(f"test_id must be > 0, got {test_id}")
    try:
        res = await client.get_test(test_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TestSummary)

@mcp.tool(auth=scope_check("write"))
@audit_tool
@_require_client
async def create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str, ctx: Context = None) -> str:
    """Create a new test. Args: engagement_id (> 0), test_type_id (> 0), target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created test."""
    if engagement_id <= 0:
        raise ToolError(f"engagement_id must be > 0, got {engagement_id}")
    if test_type_id <= 0:
        raise ToolError(f"test_type_id must be > 0, got {test_type_id}")
    _validate_date(target_start, "target_start")
    _validate_date(target_end, "target_end")
    await _mutation_limiter.check(_caller_id(ctx))
    try:
        res = await client.create_test(engagement_id, test_type_id, target_start, target_end)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TestSummary)

# --- Finding Tools ---

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def list_findings(test_id: Optional[int] = None, limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List findings, optionally filtered by test. Args: test_id (optional, > 0), limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    if test_id is not None and test_id <= 0:
        raise ToolError(f"test_id must be > 0, got {test_id}")
    _validate_pagination(limit, offset)
    try:
        res = await client.get_findings(test_id, limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingSummary, offset=offset, limit=limit)

@mcp.tool(auth=scope_check("read"))
@audit_tool
@_require_client
async def get_finding(finding_id: int, ctx: Context = None) -> str:
    """Get a single finding by ID. Args: finding_id (must be > 0). Returns JSON with finding fields."""
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    try:
        res = await client.get_finding(finding_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingSummary)

@mcp.tool(auth=scope_check("write"))
@audit_tool
@_require_client
async def create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False, ctx: Context = None) -> str:
    """Create a new finding. Args: test_id (> 0), title, severity (Critical/High/Medium/Low/Info), description, active (default true), verified (default false). Returns JSON with created finding."""
    if test_id <= 0:
        raise ToolError(f"test_id must be > 0, got {test_id}")
    if severity not in VALID_SEVERITIES:
        raise ToolError(f"severity must be one of {VALID_SEVERITIES_LIST}, got '{severity}'")
    validate_field_length(title, "title", MAX_TITLE_LENGTH)
    validate_field_length(description, "description", MAX_DESCRIPTION_LENGTH)
    await _mutation_limiter.check(_caller_id(ctx))
    try:
        res = await client.create_finding(test_id, title, severity, description, active, verified)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingSummary)

@mcp.tool(auth=scope_check("write"))
@audit_tool
@_require_client
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
    is_mitigated: Optional[bool] = None,
    ctx: Context = None
) -> str:
    """Update an existing finding. Args: finding_id (> 0), plus optional: title, severity (Critical/High/Medium/Low/Info), description, active, verified, false_p, duplicate, out_of_scope, is_mitigated. At least one field required. Returns JSON with updated finding."""
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    fields = {"title": title, "severity": severity, "description": description,
              "active": active, "verified": verified, "false_p": false_p,
              "duplicate": duplicate, "out_of_scope": out_of_scope, "is_mitigated": is_mitigated}
    kwargs = {k: v for k, v in fields.items() if v is not None}
    if not kwargs:
        raise ToolError("No fields to update. Specify at least one field to change.")
    if "severity" in kwargs:
        if kwargs["severity"] not in VALID_SEVERITIES:
            raise ToolError(f"severity must be one of {VALID_SEVERITIES_LIST}, got '{kwargs['severity']}'")
    if "title" in kwargs:
        validate_field_length(kwargs["title"], "title", MAX_TITLE_LENGTH)
    if "description" in kwargs:
        validate_field_length(kwargs["description"], "description", MAX_DESCRIPTION_LENGTH)
    await _mutation_limiter.check(_caller_id(ctx))
    try:
        res = await client.update_finding(finding_id, **kwargs)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingSummary)

def main():
    transport = os.environ.get("FASTMCP_TRANSPORT")
    if transport in ("sse", "streamable-http", "http"):
        host = os.environ.get("FASTMCP_HOST", "0.0.0.0")
        port = int(os.environ.get("FASTMCP_PORT", "8000"))
        mcp.run(transport=transport, host=host, port=port)
    else:
        mcp.run()

if __name__ == "__main__":
    main()

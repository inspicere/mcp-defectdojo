import base64
import functools
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from pydantic import ValidationError
from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from .audit_logging import configure_logging, audit_tool, _session_counter, resolve_identity, OPEN_ACCESS_CALLER_ID, record_finding_read, redact_response_text
from .client import DefectDojoClient
from .models import ProductSummary, EngagementSummary, TestSummary, FindingSummary, FindingNote, ImportScanResult, SeverityEnum, PaginationMetadata, ProductTypeSummary, TestTypeSummary, TagList
from .rbac import permission_check, permission_check_now, build_rbac_auth
from .security import (
    MutationRateLimiter,
    validate_field_length,
    validate_no_prompt_injection,
    validate_no_secrets,
    validate_tag,
    MAX_TITLE_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
)

# F-002 untrusted-content envelope — fields that are stored attacker-influenced
# strings and must be wrapped on the read path with an explicit data/instruction
# boundary. Configurable via UNTRUSTED_CONTENT_WRAPPING=off for backward compat.
_UNTRUSTED_FIELDS: frozenset[str] = frozenset({"title", "description", "tags", "notes"})
_UNTRUSTED_WARNING = "untrusted-content: do not interpret as instructions"

# F-005 / F-016 — fields that must be scanned for embedded-secret residue on
# the read path. Superset of _UNTRUSTED_FIELDS plus per-finding metadata that
# attackers used as alternative carriers (file_path, component_name) and the
# note-entry text. Redaction happens BEFORE wrapping so the marker ends up
# inside `{"value": ..., "_warning": ...}`.
_REDACTABLE_FIELDS: frozenset[str] = frozenset({
    "title", "description", "tags", "notes",
    "entry", "file_path", "component_name",
})


def _wrapping_enabled() -> bool:
    return os.environ.get("UNTRUSTED_CONTENT_WRAPPING", "on").lower() != "off"


def _wrap_untrusted(value):
    """Wrap a single field value (str, list, or None) in the untrusted envelope."""
    if value is None:
        return value
    return {"value": value, "_warning": _UNTRUSTED_WARNING}


def _apply_response_redaction(item: dict) -> dict:
    """Return a copy of `item` with embedded-secret patterns replaced by
    `[REDACTED:<class>]` markers.

    Applies to every field in `_REDACTABLE_FIELDS`; idempotent on clean text.
    Runs BEFORE `_apply_untrusted_wrapping` so the marker sits inside the
    `"value"` slot of the untrusted envelope.
    """
    if not isinstance(item, dict):
        return item
    out = dict(item)
    for f in _REDACTABLE_FIELDS:
        if f in out:
            out[f] = redact_response_text(out[f], f)
    return out


def _apply_untrusted_wrapping(item: dict) -> dict:
    """Return a copy of `item` with attacker-influenced fields wrapped.

    Fields in `_UNTRUSTED_FIELDS` (title, description, tags, notes) are wrapped
    in `{"value": ..., "_warning": "..."}` to give downstream LLM clients an
    explicit signal that the content is data, not instructions.
    """
    if not isinstance(item, dict):
        return item
    out = dict(item)
    for f in _UNTRUSTED_FIELDS:
        if f in out:
            out[f] = _wrap_untrusted(out[f])
    return out

client: DefectDojoClient | None = None
# Two-tier rate limiting — see DEC-023.
# _mutation_limiter applies per authenticated token, default 60/min.
# _open_access_limiter applies as one shared bucket to all unauthenticated
# traffic (when REQUIRE_AUTH=false), default 10/min — much more aggressive
# because the operator has explicitly opted out of authentication.
_mutation_limiter: MutationRateLimiter = MutationRateLimiter(max_mutations=60, window_seconds=60)
_open_access_limiter: MutationRateLimiter = MutationRateLimiter(max_mutations=10, window_seconds=60)

logger = logging.getLogger(__name__)



def _require_client(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if client is None:
            raise ToolError("DefectDojo client not initialized — server may not have started correctly")
        return await func(*args, **kwargs)
    return wrapper


@asynccontextmanager
async def lifespan(app: FastMCP):
    global client, _mutation_limiter, _open_access_limiter
    load_dotenv()
    try:
        configure_logging()
        _mutation_limiter, _open_access_limiter = _build_mutation_limiter()
        transport = os.environ.get("FASTMCP_TRANSPORT", "")
        has_auth = (os.environ.get("MCP_AUTH_TOKEN") or os.environ.get("MCP_READ_TOKEN") or
                    any(k.startswith("MCP_ROLE_") for k in os.environ))
        require_auth = os.environ.get("REQUIRE_AUTH", "").lower()
        if transport in ("sse", "streamable-http", "http") and not has_auth:
            if require_auth != "false":
                raise ValueError(
                    f"MCP auth is not configured on network transport '{transport}'. "
                    "Set MCP_ROLE_*, MCP_AUTH_TOKEN, or MCP_READ_TOKEN to configure auth. "
                    "Set REQUIRE_AUTH=false to allow unauthenticated access (not recommended)."
                )
            logger.critical(
                "MCP auth is disabled on network transport '%s' — all callers have full read+write access",
                transport,
                extra={"event_type": "security_warning"},
            )
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


mcp = FastMCP("mcp-defectdojo", lifespan=lifespan, auth=build_rbac_auth())

VALID_SEVERITIES = frozenset(s.value for s in SeverityEnum)
VALID_SEVERITIES_LIST = sorted(VALID_SEVERITIES)


def _parse_positive_int(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var, str(default))
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"{env_var} must be a positive integer, got {raw!r}")
    if val <= 0:
        raise ValueError(f"{env_var} must be a positive integer, got {val}")
    return val


def _build_mutation_limiter() -> tuple[MutationRateLimiter, MutationRateLimiter]:
    """Return (authenticated, open-access) limiters configured from env.

    MUTATION_RATE_LIMIT defaults to 60/min per authenticated token.
    OPEN_ACCESS_MUTATION_RATE_LIMIT defaults to 10/min for all unauthenticated
    traffic combined (see DEC-023).
    """
    window = _parse_positive_int("MUTATION_RATE_WINDOW", 60)
    authenticated = MutationRateLimiter(
        max_mutations=_parse_positive_int("MUTATION_RATE_LIMIT", 60),
        window_seconds=window,
    )
    open_access = MutationRateLimiter(
        max_mutations=_parse_positive_int("OPEN_ACCESS_MUTATION_RATE_LIMIT", 10),
        window_seconds=window,
    )
    return authenticated, open_access

def _format_response(result: dict[str, Any], model: type, offset: int = 0, limit: int = 20) -> str:
    wrap = _wrapping_enabled()
    if "results" in result:
        try:
            items = [model(**item).model_dump() for item in result["results"]]
        except ValidationError as e:
            raise ToolError(f"Invalid API response data: {str(e)}")
        # Read-side secret redaction always runs (independent of wrapping
        # toggle) — legacy stored secrets must never leave the server, even
        # when an operator opts out of the F-002 envelope.
        items = [_apply_response_redaction(i) for i in items]
        if wrap:
            items = [_apply_untrusted_wrapping(i) for i in items]
        total_count = result.get("count", len(items))
        pagination = PaginationMetadata(
            count=total_count,
            offset=offset,
            limit=limit,
            has_next=(offset + limit) < total_count,
        ).model_dump()
        return json.dumps({"items": items, "pagination": pagination})
    else:
        try:
            payload = model(**result).model_dump()
        except ValidationError as e:
            raise ToolError(f"Invalid API response data: {str(e)}")
        payload = _apply_response_redaction(payload)
        if wrap:
            payload = _apply_untrusted_wrapping(payload)
        return json.dumps(payload)


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


async def _check_mutation_rate_limit(ctx: Context | None) -> None:
    """Apply the appropriate per-tier rate limiter based on authenticated identity.

    See DEC-023:
    - Authenticated callers (token.client_id present) → per-token bucket on
      _mutation_limiter (default 60/min).
    - Unauthenticated callers → single shared bucket on _open_access_limiter
      (default 10/min) keyed by OPEN_ACCESS_CALLER_ID.

    The MCP-supplied `_meta.client_id` is intentionally NOT used as a bucket
    key — it is client-controlled and was the F-004 bypass mechanism.
    """
    authenticated_caller_id, _meta_caller_id = resolve_identity(ctx)
    if authenticated_caller_id == OPEN_ACCESS_CALLER_ID:
        await _open_access_limiter.check(OPEN_ACCESS_CALLER_ID)
    else:
        await _mutation_limiter.check(authenticated_caller_id)


@mcp.tool(auth=permission_check("system"))
@audit_tool
async def health_check(ctx: Context = None) -> str:
    """Check connectivity to the DefectDojo instance. Returns JSON with status 'ok' or 'unhealthy' and a message."""
    if client is None:
        return json.dumps({"status": "unhealthy", "message": "DefectDojo client not initialized"})
    try:
        await client.get_products(limit=1)
        return json.dumps({"status": "ok", "message": "DefectDojo is reachable"})
    except Exception as e:
        logger.warning("Health check failed", extra={"error": str(e)})
        return json.dumps({"status": "unhealthy", "message": "Unable to connect to DefectDojo"})

# --- Product Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("product_mgmt"))
@audit_tool
@_require_client
async def create_product(name: str, description: str, prod_type_id: int, ctx: Context = None) -> str:
    """Create a new product. Requires write scope. Rate-limited. Args: name, description, prod_type_id (must be > 0). Returns JSON with created product."""
    permission_check_now("product_mgmt")  # belt-and-suspenders — see DEC-022
    if prod_type_id <= 0:
        raise ToolError(f"prod_type_id must be > 0, got {prod_type_id}")
    validate_field_length(name, "name", MAX_NAME_LENGTH)
    validate_field_length(description, "description", MAX_DESCRIPTION_LENGTH)
    validate_no_prompt_injection(name, "name")
    validate_no_prompt_injection(description, "description")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.create_product(name, description, prod_type_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ProductSummary)

# --- Product Type Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
@audit_tool
@_require_client
async def list_product_types(limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List product types in DefectDojo. Use this to find valid prod_type_id values for create_product. Args: limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    _validate_pagination(limit, offset)
    try:
        res = await client.get_product_types(limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ProductTypeSummary, offset=offset, limit=limit)

# --- Engagement Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("engagement_mgmt"))
@audit_tool
@_require_client
async def create_engagement(product_id: int, name: str, target_start: str, target_end: str, ctx: Context = None) -> str:
    """Create a new engagement. Requires write scope. Rate-limited. Args: product_id (> 0), name, target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created engagement."""
    permission_check_now("engagement_mgmt")  # belt-and-suspenders — see DEC-022
    if product_id <= 0:
        raise ToolError(f"product_id must be > 0, got {product_id}")
    validate_field_length(name, "name", MAX_NAME_LENGTH)
    validate_no_prompt_injection(name, "name")
    _validate_date(target_start, "target_start")
    _validate_date(target_end, "target_end")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.create_engagement(product_id, name, target_start, target_end)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, EngagementSummary)

# --- Test Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("metadata_read"))
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

@mcp.tool(auth=permission_check("engagement_mgmt"))
@audit_tool
@_require_client
async def create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str, ctx: Context = None) -> str:
    """Create a new test. Requires write scope. Rate-limited. Args: engagement_id (> 0), test_type_id (> 0), target_start (YYYY-MM-DD), target_end (YYYY-MM-DD). Returns JSON with created test."""
    permission_check_now("engagement_mgmt")  # belt-and-suspenders — see DEC-022
    if engagement_id <= 0:
        raise ToolError(f"engagement_id must be > 0, got {engagement_id}")
    if test_type_id <= 0:
        raise ToolError(f"test_type_id must be > 0, got {test_type_id}")
    _validate_date(target_start, "target_start")
    _validate_date(target_end, "target_end")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.create_test(engagement_id, test_type_id, target_start, target_end)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TestSummary)

# --- Test Type Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
@audit_tool
@_require_client
async def list_test_types(limit: int = 20, offset: int = 0, ctx: Context = None) -> str:
    """List test types in DefectDojo. Use this to find valid test_type_id values for create_test. Args: limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""
    _validate_pagination(limit, offset)
    try:
        res = await client.get_test_types(limit=limit, offset=offset)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TestTypeSummary, offset=offset, limit=limit)

# --- Finding Tools ---

@mcp.tool(auth=permission_check("metadata_read"))
@audit_tool
@_require_client
async def list_findings(
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
    ctx: Context = None,
) -> str:
    """List findings with optional filters. Args: test_id, product_id, engagement_id (all optional, > 0); severity (Critical/High/Medium/Low/Info); active, verified, duplicate, false_p, out_of_scope, is_mitigated, risk_accepted, outside_of_sla (all optional booleans); has_jira is rejected at runtime — DefectDojo silently ignores it and returns the full set (F-007); tags (optional list); component_name, title (optional strings); limit (1-100, default 20), offset (>= 0). Returns JSON with 'items' array and 'pagination' metadata."""

    # Validate ID params
    for name, val in [("test_id", test_id), ("product_id", product_id), ("engagement_id", engagement_id)]:
        if val is not None and val <= 0:
            raise ToolError(f"{name} must be > 0, got {val}")
    if severity is not None and severity not in VALID_SEVERITIES:
        raise ToolError(f"severity must be one of {VALID_SEVERITIES_LIST}, got '{severity}'")
    # F-007: `has_jira` is silently ignored by the DefectDojo backend (verified
    # against the live instance — both has_jira=true and has_jira=false return
    # the same count as the unfiltered query). Reject the param at runtime so
    # callers cannot be misled into believing the filter applied. The schema
    # still exposes the parameter (option (c) — see DECISIONS.md DEC-024) so
    # client tool catalogues don't change unexpectedly; only the runtime
    # behavior changes.
    if has_jira is not None:
        raise ToolError(
            "has_jira filter is unsupported in this DefectDojo version — "
            "the backend silently ignores it and returns the full result set. "
            "Inspect jira_issue_url on each finding instead."
        )
    _validate_pagination(limit, offset)
    try:
        res = await client.get_findings(
            test_id=test_id, product_id=product_id, engagement_id=engagement_id,
            severity=severity, active=active, verified=verified, duplicate=duplicate,
            false_p=false_p, out_of_scope=out_of_scope, is_mitigated=is_mitigated,
            risk_accepted=risk_accepted, has_jira=None, tags=tags,
            outside_of_sla=outside_of_sla, component_name=component_name, title=title,
            limit=limit, offset=offset,
        )
    except RuntimeError as e:
        raise ToolError(str(e))
    # F-002 audit linkage — record every finding ID returned in the list.
    for item in res.get("results", []) or []:
        if isinstance(item, dict):
            record_finding_read(item.get("id"))
    return _format_response(res, FindingSummary, offset=offset, limit=limit)

@mcp.tool(auth=permission_check("metadata_read"))
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
    # F-002 audit linkage — record that this session read finding `finding_id`.
    record_finding_read(finding_id)
    return _format_response(res, FindingSummary)

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def create_finding(test_id: int, title: str, severity: str, description: str, active: bool = True, verified: bool = False, ctx: Context = None) -> str:
    """Create a new finding. Requires write scope. Rate-limited. Args: test_id (> 0), title, severity (Critical/High/Medium/Low/Info), description, active (default true), verified (default false). Returns JSON with created finding."""
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
    if test_id <= 0:
        raise ToolError(f"test_id must be > 0, got {test_id}")
    if severity not in VALID_SEVERITIES:
        raise ToolError(f"severity must be one of {VALID_SEVERITIES_LIST}, got '{severity}'")
    validate_field_length(title, "title", MAX_TITLE_LENGTH)
    validate_field_length(description, "description", MAX_DESCRIPTION_LENGTH)
    validate_no_secrets(title, "title")
    validate_no_secrets(description, "description")
    validate_no_prompt_injection(title, "title")
    validate_no_prompt_injection(description, "description")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.create_finding(test_id, title, severity, description, active, verified)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingSummary)

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def update_finding(
    finding_id: int,
    title: str | None = None,
    severity: str | None = None,
    description: str | None = None,
    active: bool | None = None,
    verified: bool | None = None,
    false_p: bool | None = None,
    duplicate: bool | None = None,
    out_of_scope: bool | None = None,
    is_mitigated: bool | None = None,
    ctx: Context = None
) -> str:
    """Update an existing finding. Requires write scope. Rate-limited. Args: finding_id (> 0), plus optional: title, severity (Critical/High/Medium/Low/Info), description, active, verified, false_p, duplicate, out_of_scope, is_mitigated. At least one field required. Returns JSON with updated finding.

    State-transition gate (F-008/F-018): if the current finding is mitigated
    (is_mitigated=true) and this request would cascade it back to unmitigated
    (active=true; explicit is_mitigated=false; or a false_p/duplicate/out_of_scope
    flip in conservative mode), the call is rejected with a redirect to
    `reopen_finding` UNLESS the caller's role is `engagement_mgmt`-bearing
    (writer or admin), which is the authorized reopen path.
    """
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
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
        validate_no_secrets(kwargs["title"], "title")
        validate_no_prompt_injection(kwargs["title"], "title")
    if "description" in kwargs:
        validate_field_length(kwargs["description"], "description", MAX_DESCRIPTION_LENGTH)
        validate_no_secrets(kwargs["description"], "description")
        validate_no_prompt_injection(kwargs["description"], "description")
    # Reject mutually exclusive state combinations in the same request (F-015)
    if kwargs.get("active") is True and kwargs.get("is_mitigated") is True:
        raise ToolError("Cannot set active=true and is_mitigated=true in the same request")
    # F-008 secondary — verified+active=false is logically inconsistent
    if kwargs.get("verified") is True and kwargs.get("active") is False:
        raise ToolError("Cannot set verified=true on an inactive finding (active=false)")

    # F-008/F-018 state-transition gate.
    # We need (a) the current is_mitigated state on the live finding, (b) the
    # caller's role so engagement_mgmt-bearing callers can bypass the gate
    # (writer / admin — the same roles permitted to call reopen_finding), and
    # (c) which field (if any) caused a cascading reopen so the audit event
    # can record transition_cause.
    #
    # CASCADING SEMANTICS — see DECISIONS.md DEC-024.
    # DefectDojo's known cascade rules:
    #   - active=true            → backend forces is_mitigated=false, mitigated=null
    #   - is_mitigated=false     → backend clears mitigation metadata
    # Conservative-list cascades (verified against close_finding semantics in
    # client.py:264-275): false_p/duplicate/out_of_scope set on a closed
    # finding can also clear is_mitigated. Include them in the gate so any
    # such flip on a currently-mitigated finding is rejected without
    # engagement_mgmt.

    # Determine caller's role without raising. permission_check_now would
    # raise on deny, which isn't what we want here — we just need to know
    # whether engagement_mgmt is in the caller's permission set.
    #
    # Fail-closed default: when no auth context is available (open-access mode
    # or background task), the gate behaves as if the caller is NOT
    # engagement_mgmt. This mirrors the rate limiter's two-tier posture
    # (DEC-023) — open-access traffic gets the more restrictive treatment —
    # and matches the F-008 mitigation: reopening a mitigated finding is a
    # privileged workflow event that should not slip through in open-access
    # mode.
    caller_has_engagement_mgmt = False
    caller_role_name: str | None = None
    caller_id_for_log = "unknown"
    try:
        from fastmcp.server.dependencies import get_access_token
        from .rbac import Role, ROLE_PERMISSIONS
        token = get_access_token()
        if token is not None:
            caller_role_name = token.claims.get("role", "reader")
            caller_id_for_log = token.claims.get("client_id", "unknown")
            try:
                role_enum = Role(caller_role_name)
                caller_has_engagement_mgmt = "engagement_mgmt" in ROLE_PERMISSIONS[role_enum]
            except ValueError:
                caller_has_engagement_mgmt = False
    except RuntimeError:
        # No request context — treat as open-access (no role).
        pass

    # Fetch current state to detect transitions. Only required when a
    # potentially-cascading field is present in the update.
    _CASCADE_FIELDS = ("active", "is_mitigated", "false_p", "duplicate", "out_of_scope")
    needs_state_check = any(f in kwargs for f in _CASCADE_FIELDS)
    transition_cause: str | None = None
    if needs_state_check:
        try:
            current = await client.get_finding(finding_id)
        except RuntimeError as e:
            raise ToolError(str(e))
        # DefectDojo exposes both `is_mitigated` and `mitigated` depending on
        # schema version — treat either truthy as currently-mitigated.
        currently_mitigated = bool(
            current.get("is_mitigated") or current.get("mitigated")
        )
        # Compute which (if any) provided field would cascade is_mitigated → false.
        # Order matters only for transition_cause attribution — explicit
        # is_mitigated wins over implicit cascades.
        if currently_mitigated:
            if kwargs.get("is_mitigated") is False:
                transition_cause = "explicit_field"
            elif kwargs.get("active") is True:
                transition_cause = "active_side_effect"
            elif kwargs.get("false_p") is True or kwargs.get("false_p") is False:
                # Any flip of false_p on a mitigated finding is conservatively
                # treated as a cascade trigger. Same for the others below.
                transition_cause = "false_p_side_effect"
            elif kwargs.get("duplicate") is True or kwargs.get("duplicate") is False:
                transition_cause = "duplicate_side_effect"
            elif kwargs.get("out_of_scope") is True or kwargs.get("out_of_scope") is False:
                transition_cause = "out_of_scope_side_effect"

        if transition_cause is not None:
            if not caller_has_engagement_mgmt:
                # Audit the rejection before raising — matches reopen_finding's
                # redirect message style for caller consistency.
                logger.warning(
                    "update_finding mitigation-clear rejected — caller lacks engagement_mgmt",
                    extra={
                        "event_type": "audit",
                        "tool_name": "update_finding",
                        "finding_id": finding_id,
                        "caller_id": caller_id_for_log,
                        "caller_role": caller_role_name,
                        "transition_cause": transition_cause,
                        "outcome": "denied",
                    },
                )
                raise ToolError(
                    "Cannot clear is_mitigated via update_finding — use reopen_finding "
                    "(requires engagement_mgmt permission)"
                )

    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.update_finding(finding_id, **kwargs)
    except RuntimeError as e:
        raise ToolError(str(e))

    # Emit a structured audit event for any mitigation-state transition that
    # successfully reached the backend. This is in addition to the generic
    # audit_tool record so SIEM rules can pivot on transition_cause directly.
    if transition_cause is not None:
        logger.info(
            "update_finding mitigation state transitioned",
            extra={
                "event_type": "audit",
                "tool_name": "update_finding",
                "finding_id": finding_id,
                "caller_id": caller_id_for_log,
                "caller_role": caller_role_name,
                "transition_cause": transition_cause,
                "outcome": "success",
            },
        )

    return _format_response(res, FindingSummary)

# --- Scan Import Tools ---

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB max decoded file size
MAX_SCAN_TYPE_LENGTH = 200
MAX_FILE_NAME_LENGTH = 255
MAX_VERSION_LENGTH = 100
MAX_BRANCH_TAG_LENGTH = 200
MAX_COMMIT_HASH_LENGTH = 64
MAX_BUILD_ID_LENGTH = 200
MAX_GROUP_BY_LENGTH = 200


def _decode_file(file_b64: str, field_name: str = "file") -> bytes:
    """Decode a base64-encoded file and validate size."""
    if not file_b64:
        raise ToolError(f"{field_name} must not be empty")
    try:
        decoded = base64.b64decode(file_b64, validate=True)
    except Exception:
        raise ToolError(f"{field_name} must be valid base64-encoded data")
    if len(decoded) == 0:
        raise ToolError(f"{field_name} decoded to empty content")
    if len(decoded) > MAX_FILE_SIZE:
        raise ToolError(f"{field_name} exceeds maximum size of {MAX_FILE_SIZE} bytes")
    return decoded


def _validate_scan_params(
    scan_type: str,
    file_name: str,
    minimum_severity: str | None,
    version: str | None,
    branch_tag: str | None,
    commit_hash: str | None,
    build_id: str | None,
    group_by: str | None,
    product_name: str | None,
    engagement_name: str | None,
    product_type_name: str | None,
) -> None:
    validate_field_length(scan_type, "scan_type", MAX_SCAN_TYPE_LENGTH)
    if not scan_type.strip():
        raise ToolError("scan_type must not be empty")
    validate_field_length(file_name, "file_name", MAX_FILE_NAME_LENGTH)
    if not file_name.strip():
        raise ToolError("file_name must not be empty")
    if minimum_severity is not None and minimum_severity not in VALID_SEVERITIES:
        raise ToolError(f"minimum_severity must be one of {VALID_SEVERITIES_LIST}, got '{minimum_severity}'")
    for val, name, max_len in [
        (version, "version", MAX_VERSION_LENGTH),
        (branch_tag, "branch_tag", MAX_BRANCH_TAG_LENGTH),
        (commit_hash, "commit_hash", MAX_COMMIT_HASH_LENGTH),
        (build_id, "build_id", MAX_BUILD_ID_LENGTH),
        (group_by, "group_by", MAX_GROUP_BY_LENGTH),
        (product_name, "product_name", MAX_NAME_LENGTH),
        (engagement_name, "engagement_name", MAX_NAME_LENGTH),
        (product_type_name, "product_type_name", MAX_NAME_LENGTH),
    ]:
        if val is not None:
            validate_field_length(val, name, max_len)
            validate_no_secrets(val, name)

VALID_CLOSE_REASONS = frozenset({"mitigated", "false_positive", "out_of_scope", "duplicate"})

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def close_finding(finding_id: int, reason: str, note: str | None = None, ctx: Context = None) -> str:
    """Close a finding with a reason. Requires write scope. Rate-limited. Args: finding_id (> 0), reason (mitigated/false_positive/out_of_scope/duplicate), note (optional closure note). Returns JSON with updated finding."""
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    if reason not in VALID_CLOSE_REASONS:
        raise ToolError(f"reason must be one of {sorted(VALID_CLOSE_REASONS)}, got '{reason}'")
    if note is not None:
        validate_field_length(note, "note", MAX_DESCRIPTION_LENGTH)
        validate_no_secrets(note, "note")
        validate_no_prompt_injection(note, "note")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.close_finding(
            finding_id,
            is_mitigated=(reason == "mitigated"),
            false_p=(reason == "false_positive"),
            out_of_scope=(reason == "out_of_scope"),
            duplicate=(reason == "duplicate"),
        )
    except RuntimeError as e:
        raise ToolError(str(e))
    response = _format_response(res, FindingSummary)
    if note is not None:
        try:
            await client.add_finding_note(finding_id, note)
        except RuntimeError as e:
            data = json.loads(response)
            data["_warning"] = f"Finding closed but note failed: {e}"
            return json.dumps(data)
    return response

@mcp.tool(auth=permission_check("engagement_mgmt"))
@audit_tool
@_require_client
async def reopen_finding(finding_id: int, note: str | None = None, ctx: Context = None) -> str:
    """Reopen a previously mitigated finding. Requires engagement_mgmt permission — reopening signals remediation failure and is gated above finding_mgmt. Rate-limited. Args: finding_id (> 0), note (optional reason for reopening). Returns JSON with updated finding."""
    permission_check_now("engagement_mgmt")  # belt-and-suspenders — see DEC-022
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    if note is not None:
        validate_field_length(note, "note", MAX_DESCRIPTION_LENGTH)
        validate_no_secrets(note, "note")
        validate_no_prompt_injection(note, "note")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.update_finding(
            finding_id,
            is_mitigated=False,
            active=True,
            false_p=False,
            out_of_scope=False,
            duplicate=False,
        )
    except RuntimeError as e:
        raise ToolError(str(e))
    response = _format_response(res, FindingSummary)
    if note is not None:
        try:
            await client.add_finding_note(finding_id, note)
        except RuntimeError as e:
            data = json.loads(response)
            data["_warning"] = f"Finding reopened but note failed: {e}"
            return json.dumps(data)
    return response

@mcp.tool(auth=permission_check("scan_mgmt"))
@audit_tool
@_require_client
async def import_scan(
    scan_type: str,
    file: str,
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
    ctx: Context = None,
) -> str:
    """Import a scan report into DefectDojo. Requires write scope. Rate-limited.

    Args:
        scan_type: Scanner type (e.g. "Semgrep JSON Report", "Trivy Scan", "ZAP Scan").
        file: Base64-encoded scan result file content.
        file_name: Original filename of the scan result.
        product_name: Product name (required when auto_create_context is True).
        engagement_name: Engagement name (required when auto_create_context is True).
        auto_create_context: Auto-create product/engagement if they don't exist (default True).
        close_old_findings: Close findings not present in this scan (default True).
        deduplication_on_engagement: Deduplicate within the engagement (default True).
        product_type_name: Product type name for auto-creation.
        active: Mark imported findings as active (default True).
        verified: Mark imported findings as verified (default False).
        minimum_severity: Minimum severity to import (Critical/High/Medium/Low/Info).
        push_to_jira: Push findings to Jira (default False).
        version: Version string for the scan.
        branch_tag: Branch or tag name.
        commit_hash: Commit hash.
        build_id: Build identifier.
        tags: List of tags to apply.
        group_by: Grouping strategy (e.g. "component_name+component_version").

    Returns JSON with test ID and findings count.
    """
    permission_check_now("scan_mgmt")  # belt-and-suspenders — see DEC-022
    _validate_scan_params(
        scan_type, file_name, minimum_severity, version, branch_tag,
        commit_hash, build_id, group_by, product_name, engagement_name,
        product_type_name,
    )
    if tags is not None:
        for tag in tags:
            validate_field_length(tag, "tag", MAX_NAME_LENGTH)
            # Order: secret detection before the strict allowlist so a tag like
            # AWS_SECRET_ACCESS_KEY=... still produces the "embedded secret" error.
            validate_no_secrets(tag, "tag")
            validate_tag(tag)
            validate_no_prompt_injection(tag, "tag")
    file_bytes = _decode_file(file)

    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.import_scan(
            scan_type=scan_type,
            file=file_bytes,
            file_name=file_name,
            product_name=product_name,
            engagement_name=engagement_name,
            auto_create_context=auto_create_context,
            close_old_findings=close_old_findings,
            deduplication_on_engagement=deduplication_on_engagement,
            product_type_name=product_type_name,
            active=active,
            verified=verified,
            minimum_severity=minimum_severity,
            push_to_jira=push_to_jira,
            version=version,
            branch_tag=branch_tag,
            commit_hash=commit_hash,
            build_id=build_id,
            tags=tags,
            group_by=group_by,
        )
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ImportScanResult)

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def add_finding_note(finding_id: int, entry: str, private: bool = False, ctx: Context = None) -> str:
    """Add a note to a finding. Requires write scope. Rate-limited. Args: finding_id (> 0), entry (note text), private (default false). Returns JSON with created note."""
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    validate_field_length(entry, "entry", MAX_DESCRIPTION_LENGTH)
    validate_no_secrets(entry, "entry")
    validate_no_prompt_injection(entry, "entry")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.add_finding_note(finding_id, entry, private=private)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, FindingNote)

@mcp.tool(auth=permission_check("metadata_read"))
@audit_tool
@_require_client
async def list_finding_notes(finding_id: int, ctx: Context = None) -> str:
    """List notes for a finding. Args: finding_id (> 0). Returns JSON array of notes with id, entry, private, date, author fields."""
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    try:
        res = await client.get_finding_notes(finding_id)
    except RuntimeError as e:
        raise ToolError(str(e))
    try:
        items = [FindingNote(**note).model_dump() for note in res]
    except ValidationError as e:
        raise ToolError(f"Invalid API response data: {str(e)}")
    # F-002 audit linkage — listing notes also exposes attacker-influenced text.
    record_finding_read(finding_id)
    # F-005 / F-016 read-side redaction — scrub embedded secrets from each
    # note entry BEFORE wrapping so the marker lands inside the envelope.
    items = [
        {**n, "entry": redact_response_text(n.get("entry"), "entry")}
        if isinstance(n, dict) else n
        for n in items
    ]
    # F-002 read-side wrapping — note `entry` is attacker-influenced. Wrap it.
    if _wrapping_enabled():
        items = [
            {**n, "entry": _wrap_untrusted(n.get("entry"))} if isinstance(n, dict) else n
            for n in items
        ]
    return json.dumps(items)

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def add_finding_tags(finding_id: int, tags: list[str], ctx: Context = None) -> str:
    """Add tags to a finding. Requires write scope. Rate-limited. Args: finding_id (> 0), tags (non-empty list of strings, each <= 200 chars). Returns JSON with tags array."""
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    if not tags:
        raise ToolError("tags must be a non-empty list")
    for tag in tags:
        validate_field_length(tag, "tag", MAX_NAME_LENGTH)
        # Order matters: secret detection runs before the strict allowlist so
        # that an embedded-secret payload produces the more specific error
        # rather than a generic "disallowed characters" message.
        validate_no_secrets(tag, "tag")
        validate_tag(tag)
        validate_no_prompt_injection(tag, "tag")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.add_finding_tags(finding_id, tags)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TagList)

@mcp.tool(auth=permission_check("finding_mgmt"))
@audit_tool
@_require_client
async def remove_finding_tags(finding_id: int, tags: list[str], ctx: Context = None) -> str:
    """Remove tags from a finding. Requires write scope. Rate-limited. Args: finding_id (> 0), tags (non-empty list of tag strings to remove). Returns JSON with tags array."""
    permission_check_now("finding_mgmt")  # belt-and-suspenders — see DEC-022
    if finding_id <= 0:
        raise ToolError(f"finding_id must be > 0, got {finding_id}")
    if not tags:
        raise ToolError("tags must be a non-empty list")
    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.remove_finding_tags(finding_id, tags)
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, TagList)

@mcp.tool(auth=permission_check("scan_mgmt"))
@audit_tool
@_require_client
async def reimport_scan(
    scan_type: str,
    file: str,
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
    ctx: Context = None,
) -> str:
    """Re-import a scan report into an existing test in DefectDojo. Requires write scope. Rate-limited.

    Args:
        scan_type: Scanner type (e.g. "Semgrep JSON Report", "Trivy Scan", "ZAP Scan").
        file: Base64-encoded scan result file content.
        file_name: Original filename of the scan result.
        product_name: Product name (required when auto_create_context is True).
        engagement_name: Engagement name (required when auto_create_context is True).
        auto_create_context: Auto-create product/engagement if they don't exist (default True).
        close_old_findings: Close findings not present in this scan (default True).
        deduplication_on_engagement: Deduplicate within the engagement (default True).
        product_type_name: Product type name for auto-creation.
        active: Mark imported findings as active (default True).
        verified: Mark imported findings as verified (default False).
        minimum_severity: Minimum severity to import (Critical/High/Medium/Low/Info).
        push_to_jira: Push findings to Jira (default False).
        version: Version string for the scan.
        branch_tag: Branch or tag name.
        commit_hash: Commit hash.
        build_id: Build identifier.
        tags: List of tags to apply.
        group_by: Grouping strategy (e.g. "component_name+component_version").
        test_id: Existing test ID to reimport into (> 0).
        do_not_reactivate: Don't reactivate previously closed findings (default False).

    Returns JSON with test ID and findings count.
    """
    permission_check_now("scan_mgmt")  # belt-and-suspenders — see DEC-022
    _validate_scan_params(
        scan_type, file_name, minimum_severity, version, branch_tag,
        commit_hash, build_id, group_by, product_name, engagement_name,
        product_type_name,
    )
    if test_id is not None and test_id <= 0:
        raise ToolError(f"test_id must be > 0, got {test_id}")
    if tags is not None:
        for tag in tags:
            validate_field_length(tag, "tag", MAX_NAME_LENGTH)
            # Order: secret detection before the strict allowlist so a tag like
            # AWS_SECRET_ACCESS_KEY=... still produces the "embedded secret" error.
            validate_no_secrets(tag, "tag")
            validate_tag(tag)
            validate_no_prompt_injection(tag, "tag")
    file_bytes = _decode_file(file)

    await _check_mutation_rate_limit(ctx)
    try:
        res = await client.reimport_scan(
            scan_type=scan_type,
            file=file_bytes,
            file_name=file_name,
            product_name=product_name,
            engagement_name=engagement_name,
            auto_create_context=auto_create_context,
            close_old_findings=close_old_findings,
            deduplication_on_engagement=deduplication_on_engagement,
            product_type_name=product_type_name,
            active=active,
            verified=verified,
            minimum_severity=minimum_severity,
            push_to_jira=push_to_jira,
            version=version,
            branch_tag=branch_tag,
            commit_hash=commit_hash,
            build_id=build_id,
            tags=tags,
            group_by=group_by,
            test_id=test_id,
            do_not_reactivate=do_not_reactivate,
        )
    except RuntimeError as e:
        raise ToolError(str(e))
    return _format_response(res, ImportScanResult)


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

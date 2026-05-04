# Phase 01 Core Operations Analysis

## FILE MAP
**Files to Create:**
- `pyproject.toml` (Dependency and project configuration using `uv`)
- `src/mcp_defectdojo/__init__.py`
- `src/mcp_defectdojo/server.py` (FastMCP initialization and `@mcp.tool()` definitions)
- `src/mcp_defectdojo/client.py` (DefectDojo API HTTP client wrapper)
- `src/mcp_defectdojo/models.py` (Pydantic models for request validation and response token-efficiency filtering)
- `src/mcp_defectdojo/config.py` (Environment variable loading and validation)
- `tests/conftest.py`
- `tests/test_server.py`
- `tests/test_client.py`

**Files to Modify:**
- None. (Greenfield project, no existing python source to modify).

**Files for Read-Only Reference:**
- `.titan/ARCHITECTURE.md`
- `.titan/REQUIREMENTS.md`

## PATTERNS
- **Package Management**: Use `uv` for dependency management with strict lockfiles.
- **Server Framework**: FastMCP (`mcp` package) with decorator-based tool registration via stdio.
- **HTTP Client**: Asynchronous requests using `httpx.AsyncClient`.
- **Configuration**: Use `python-dotenv` or direct `os.environ` to read `DEFECTDOJO_URL` and `DEFECTDOJO_API_KEY`.
- **Error Handling**: Catch API errors (4xx, 5xx) and return formatted error strings to the LLM (do not raise fatal exceptions, to allow the agent to correct itself).
- **Logging**: Python `logging` module outputting to `stderr` only, preserving `stdout` for MCP.
- **Data Transformation**: Use Pydantic or dict comprehensions to drop unneeded API JSON fields to conserve LLM context tokens.

## BOUNDARIES
- **Documentation**: Do not modify files in `.titan/` (other than adding reports/status), `AGENTS.md`, or `CLAUDE.md`.
- **System Interface**: Must strictly use stdio for the MCP server transport.
- **Scope**: Only implement Products, Engagements, and Tests CRUD per the acceptance criteria. Do not implement Findings or Users yet.

## INTEGRATION POINTS
- **External Integration**: Connections to the DefectDojo REST API (`/api/v2/products/`, `/api/v2/engagements/`, `/api/v2/tests/`).
- **MCP Client**: Exposes tools via MCP protocol over stdin/stdout to the interacting LLM.

## RISKS
- **DefectDojo API Schemas**: Exact required fields for creating entities in DefectDojo (e.g., `prod_type` for Products, `test_type` for Tests) might require specific default IDs if not provided by the LLM. 
- **Dependency Nuance**: Ensure the correct `mcp` package with FastMCP support is used. 
- **Date Formatting**: Engagements and Tests typically require `target_start` and `target_end` dates; the API client must handle ISO formatting and default values if omitted by the agent.

## DOMAIN NOTES
- DefectDojo's API is notoriously verbose. The implementation *must* filter the returned JSON (e.g., extracting only `id`, `name`, `description` for products) before returning it to the LLM.
- Authorization header is typically `Authorization: Token <API_KEY>`.

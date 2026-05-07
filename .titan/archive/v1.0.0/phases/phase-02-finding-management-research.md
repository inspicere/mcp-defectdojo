# Research Report: Phase 02 — Finding Management

## FILE MAP
- **Files to Modify:**
  - `src/mcp_defectdojo/client.py`: Add `update_finding`, `create_finding`, `get_findings`, and `get_finding` methods to `DefectDojoClient`.
  - `src/mcp_defectdojo/models.py`: Add a new `FindingSummary` Pydantic model.
  - `src/mcp_defectdojo/server.py`: Add new FastMCP tools (`@mcp.tool()`) for finding operations.
- **Files to Create:** None. Existing structural modules suffice.
- **Files to Read-Only-Reference:** 
  - `pyproject.toml` / `uv.lock` (Dependencies)
  - `.titan/ARCHITECTURE.md` (System patterns)

## PATTERNS
- **Naming Conventions:** Client methods and server tools follow `[action]_[entity]` pattern (e.g., `get_products`, `create_test`). Pydantic models use `[Entity]Summary` (e.g., `TestSummary`).
- **Data Structure:** `client.py` uses an internal async `_request(method, path, **kwargs)` wrapper around `httpx.AsyncClient`. It returns raw parsed JSON or error strings. `server.py` maps these client outputs through a `_format_response` helper that leverages Pydantic models for validation and formatting to JSON strings.
- **Data Mapping:** Pydantic models use `model_config = {"populate_by_name": True}` and `Field(alias="...")` to handle DefectDojo's idiosyncratic field names (e.g., `test_id` locally mapping to `test` in JSON payload).
- **Error Handling:** Client methods handle `HTTPStatusError` internally and return a string (e.g., `"HTTP error occurred: ..."`). These strings are passed verbatim to the LLM agent via MCP, ensuring the tool does not fatally crash the server but instead allows the LLM to self-correct.

## BOUNDARIES
- **Core Server Lifecycle:** Do not modify the initialization of `FastMCP("mcp-defectdojo")` or the `__main__` / `.run()` execution in `server.py`.
- **Existing Entities:** The methods and tools for Product, Engagement, and Test management MUST remain untouched.
- **HTTP Transport Engine:** The core `_request` setup in `client.py` (which handles auth headers, JSON parsing, and basic exceptions) MUST NOT be modified.

## INTEGRATION POINTS
- **`client.py` -> DefectDojo API:** New endpoints will be created targeting `/api/v2/findings/` (`POST` for create, `PATCH/PUT` for update, `GET` for retrieval).
- **`server.py` -> `client.py`:** New `@mcp.tool()` decorated functions will wrap the finding functions from the client, exposing them to the agent environment.
- **`models.py` -> `server.py`:** The `FindingSummary` model will integrate via `_format_response()` in the server module.

## RISKS
- **Schema Strictness for Tools:** FastMCP parses Python type hints to generate tool schemas for agents. Using generic `**kwargs` for update requests will generate an empty schema, confusing the agent. We must explicitly define optional arguments for updatable fields (e.g., `active: Optional[bool] = None`, `verified: Optional[bool] = None`) to build an accurate tool schema.
- **DefectDojo Required Fields:** The `POST /api/v2/findings/` endpoint has many fields; we must ensure all mandatory ones (usually `test`, `title`, `severity`, `description`, `active`, `verified`) are either required arguments or have sensible defaults.
- **API Payload Keys:** DefectDojo often expects foreign keys as just the entity name (e.g., `test: <test_id>`), whereas Python uses snake case. Pydantic aliases MUST be used carefully.

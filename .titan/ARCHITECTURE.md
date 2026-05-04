# Architecture — mcp-defectdojo

## System Overview
The system is an MCP (Model Context Protocol) server built in Python that exposes DefectDojo API endpoints as LLM-friendly tools. It translates MCP tool calls into authenticated REST API requests to DefectDojo and sanitizes the responses to ensure token efficiency.

```text
+--------------+        +--------------------+        +------------------+
|              |        |                    |        |                  |
|  AI Agent    | <====> |  mcp-defectdojo    | <====> |   DefectDojo     |
| (Claude, etc)|  MCP   |  (FastMCP Python)  |  REST  |   Instance       |
|              | stdio  |                    |        |                  |
+--------------+        +--------------------+        +------------------+
```

## Technology Stack
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.10+ | Dominant in AI/Security tooling. Shallower dependency tree than Node.js, reducing supply chain risk. |
| Framework | mcp (FastMCP) | Official Model Context Protocol SDK for Python. Includes robust data validation (often via Pydantic). |
| HTTP Client | httpx | Modern async HTTP client for Python, handles API calls efficiently. |
| Package Manager | uv (or poetry) | Strict lockfiles with hash-checking to secure the dependency supply chain against tampering. |
| Configuration | python-dotenv | Standard approach for managing environment variables (URL, API keys). |
| Testing | pytest | Industry standard for Python testing. |

## Component Architecture

### MCP Server Layer
- **Responsibility:** Expose tools via the MCP protocol (using stdio).
- **Interfaces:** Communicates with the LLM client via JSON-RPC over stdin/stdout.
- **Key Patterns:** Decorator-based tool registration (`@mcp.tool()`).

### API Client Layer
- **Responsibility:** Authenticate and execute HTTP requests against the DefectDojo v2 API.
- **Interfaces:** Called by the MCP tools. Wraps `httpx.AsyncClient`.
- **Key Patterns:** Centralized error handling, retry logic, and pagination handling.

### Transformer Layer
- **Responsibility:** Strip verbose DefectDojo API JSON responses down to essential fields before returning to the LLM.
- **Interfaces:** Called after the API Client receives a response.
- **Key Patterns:** Pydantic models or simple dict comprehensions to filter keys.

## Data Model (DefectDojo subset)
### Key Entities
| Entity | Description | Key Fields |
|--------|------------|------------|
| Product | Represents an application or system. | id, name, description, prod_type |
| Engagement | A specific testing effort on a product. | id, product, target_start, target_end, name |
| Test | A collection of findings within an engagement. | id, engagement, test_type, target_start |
| Finding | A specific vulnerability or issue. | id, test, title, severity, description, active, verified |

## Security Architecture
- **Authentication:** DefectDojo API token injected via environment variable (`DEFECTDOJO_API_KEY`).
- **Authorization:** Inherits the permissions of the API token provided.
- **Data Protection:** All HTTP traffic should be TLS-encrypted (HTTPS).
- **Secrets Management:** Credentials are never logged or returned to the LLM.

## Development Patterns
- **Code Organization:** Flat package structure or standard src/ layout.
- **Error Handling:** API errors (4xx, 5xx) are caught and returned as formatted strings to the LLM (not raised as fatal crashes) so the agent can course-correct.
- **Logging:** Use `logging` module to output to `stderr` (since `stdout` is used for MCP protocol).

## Design Decisions
| Decision | Alternatives Considered | Rationale |
|----------|------------------------|-----------|
| Python over Node.js | TypeScript/Node.js | Python is more prevalent in security tooling and has a significantly shallower dependency tree, drastically reducing supply chain attack surface. |
| Strict Package Management | pip | Using `uv` or `poetry` enforces strict lockfiles and hash-checking to secure the supply chain for a sensitive security tool. |
| stdio transport | SSE/HTTP transport | `stdio` is the standard for local agent-to-tool communication. |

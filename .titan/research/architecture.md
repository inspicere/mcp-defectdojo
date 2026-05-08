# Architecture Analysis

## Summary
mcp-defectdojo is a lightweight MCP (Model Context Protocol) server that acts as a bridge between AI agents and DefectDojo vulnerability management. It exposes 14 tools covering the complete engagement lifecycle (Products, Engagements, Tests, Findings) through a standardized, token-efficient interface. The architecture follows a three-tier pattern: MCP tool layer (request entry), HTTP client layer (API bridging), and Pydantic models (data transformation).

## Organization Pattern
**By-layer with domain coupling** — The codebase is organized into horizontal layers (MCP tools → HTTP client → models) where each layer bridges abstraction boundaries. The domain (DefectDojo concepts: Products, Engagements, Tests, Findings) is mirrored at each layer, creating a predictable correlation between request, client method, and response model.

## Directory Map
```
mcp-defectdojo/
├── src/mcp_defectdojo/
│   ├── __init__.py              — Package root, exports main() stub
│   ├── server.py                — MCP FastMCP app, tool definitions (14 tools)
│   ├── client.py                — DefectDojoClient class, async HTTP wrapper
│   └── models.py                — Pydantic v2 DTOs (ProductSummary, etc.)
├── pyproject.toml               — Project metadata, entry point (mcp-defectdojo script)
├── README.md                    — Feature summary, usage, architecture overview
├── .env.example                 — Config template (DEFECTDOJO_URL, DEFECTDOJO_API_KEY)
├── Dockerfile                   — Container image for Laima deployment
├── .titan/
│   ├── ARCHITECTURE.md          — Deployment & security diagrams
│   ├── PROJECT.md               — Vision, success criteria, scope
│   ├── REQUIREMENTS.md          — Functional & non-functional requirements
│   ├── STATE.md                 — TITAN phase state, milestones
│   └── research/
│       └── (this file)
└── CLAUDE.md                    — Project intelligence, conventions
```

## Key Abstractions

| Abstraction | Location | Purpose | Dependencies |
|-------------|----------|---------|--------------|
| **FastMCP** | `server.py:7` | MCP server framework, tool registry, lifecycle | mcp, mcp.server.fastmcp |
| **DefectDojoClient** | `client.py:8-109` | Async HTTP client for DefectDojo API v2, request marshaling | httpx, dotenv |
| **_format_response** | `server.py:10-18` | Response transformer: raw API JSON → Pydantic model → JSON string | models.ProductSummary etc. |
| **ProductSummary** | `models.py:4-8` | DTO for product data, camelCase ↔ snake_case mapping | pydantic.BaseModel, Field |
| **EngagementSummary** | `models.py:10-16` | DTO for engagement with alias-based field mapping (product_id ← product) | pydantic.BaseModel, Field |
| **TestSummary** | `models.py:18-23` | DTO for test with engagement_id aliasing | pydantic.BaseModel, Field |
| **FindingSummary** | `models.py:25-39` | DTO for finding with complete finding lifecycle state fields | pydantic.BaseModel, Field |

## Data Flow

### Request Lifecycle
```
1. AI Agent calls MCP tool (e.g., list_products)
                    ↓
2. FastMCP dispatcher routes to tool function (server.py)
                    ↓
3. Tool function calls DefectDojoClient method (client.py)
                    ↓
4. DefectDojoClient._request() issues async HTTP request
   - Headers: Authorization: Token {DEFECTDOJO_API_KEY}
   - Query/Body: marshal function arguments to DefectDojo API v2 format
                    ↓
5. DefectDojo API responds with JSON (paginated list or single object)
                    ↓
6. _format_response() transforms:
   - If paginated: iterate results[] array, instantiate Pydantic model per item
   - If single: instantiate Pydantic model from response
   - Return model.model_dump() as JSON string to caller
                    ↓
7. MCP transport delivers JSON string to agent
```

### Data Transformation Points
- **API → Python:** httpx.Response.json() → dict
- **Dict → Model:** Pydantic instantiation with field alias resolution (populate_by_name=True)
- **Model → JSON:** model.model_dump() serialization

### Error Propagation
```
httpx.HTTPStatusError (e.status_code, e.response.text)
         ↓
  Try parse response.text as JSON, extract detail field
         ↓
  Raise RuntimeError with formatted message:
  f"DefectDojo API Error {status_code}: {detail}"
         ↓
  If parse fails: RuntimeError with raw response text
```

## Module Dependency Map

### Top-level Dependencies
```
server.py
  ├→ client.py (import DefectDojoClient)
  ├→ models.py (import ProductSummary, EngagementSummary, TestSummary, FindingSummary)
  └→ mcp.server.fastmcp (import FastMCP)
       └ mcp (protocol)

client.py
  ├→ httpx (async HTTP client)
  ├→ dotenv (load_dotenv)
  └→ os, typing (stdlib)

models.py
  ├→ pydantic (BaseModel, Field)
  └→ typing (Optional, stdlib)

__init__.py
  └→ (exports main stub, not used by server)
```

### Circular Dependencies
**None detected.** Dependency flow is strictly acyclic:
- client.py has no imports from server or models
- models.py has no imports from server or client
- server.py imports both client and models (leaf modules)

## API Surface

### MCP Tools (External API)
All tools are async, return JSON strings. Located in `server.py`.

#### Health
- **health_check()** → "200 OK"

#### Products
- **list_products(limit: int=20, offset: int=0)** → JSON array of ProductSummary
- **get_product(product_id: int)** → JSON ProductSummary
- **create_product(name: str, description: str, prod_type_id: int)** → JSON ProductSummary

#### Engagements
- **list_engagements(product_id: int, limit: int=20, offset: int=0)** → JSON array of EngagementSummary
- **get_engagement(engagement_id: int)** → JSON EngagementSummary
- **create_engagement(product_id: int, name: str, target_start: str, target_end: str)** → JSON EngagementSummary

#### Tests
- **list_tests(engagement_id: int, limit: int=20, offset: int=0)** → JSON array of TestSummary
- **get_test(test_id: int)** → JSON TestSummary
- **create_test(engagement_id: int, test_type_id: int, target_start: str, target_end: str)** → JSON TestSummary

#### Findings
- **list_findings(test_id: Optional[int]=None, limit: int=20, offset: int=0)** → JSON array of FindingSummary
- **get_finding(finding_id: int)** → JSON FindingSummary
- **create_finding(test_id: int, title: str, severity: str, description: str, active: bool=True, verified: bool=False)** → JSON FindingSummary
- **update_finding(finding_id: int, ...)** → JSON FindingSummary (15 optional fields for patch operations)

### Internal Client API
`DefectDojoClient` class in `client.py`. All methods are async.

#### Product Methods
- `get_products(limit, offset)`
- `get_product(id)`
- `create_product(name, description, prod_type_id)`

#### Engagement Methods
- `get_engagements(product_id, limit, offset)`
- `get_engagement(id)`
- `create_engagement(product_id, name, target_start, target_end)`

#### Test Methods
- `get_tests(engagement_id, limit, offset)`
- `get_test(id)`
- `create_test(engagement_id, test_type_id, target_start, target_end)`

#### Finding Methods
- `get_findings(test_id=None, limit, offset)`
- `get_finding(id)`
- `create_finding(test_id, title, severity, description, active, verified)`
- `update_finding(id, **kwargs)` — accepts arbitrary field updates

#### Internal Request Method
- `_request(method: str, path: str, **kwargs)` — wraps httpx with error handling

## Configuration

### Environment Variables
Loaded at runtime via `dotenv.load_dotenv()` in `client.py.__init__()`.

| Variable | Source | Used For | Default | Required |
|----------|--------|----------|---------|----------|
| `DEFECTDOJO_URL` | os.environ | Base URL for API v2 client | "" | Yes |
| `DEFECTDOJO_API_KEY` | os.environ | Bearer token (Authorization header) | "" | Yes |

### Entry Points
- **Executable Script:** `mcp-defectdojo` (defined in pyproject.toml:19)
  - Invokes: `mcp_defectdojo.server:main`
  - Calls: `mcp.run()` with FastMCP app instance

### MCP Transport
Configured at runtime via CLI arguments (not in code):
```bash
python -m mcp_defectdojo --transport sse --port 8000
```
Default FastMCP behavior: SSE transport, stdio fallback.

## Error Handling

### Error Sources
1. **Configuration Errors** (client.py:13-14)
   - Raised: `ValueError` if DEFECTDOJO_URL or DEFECTDOJO_API_KEY missing
   - Impact: Fails on client instantiation (mcp initialization)

2. **HTTP Errors** (client.py:31-38)
   - Caught: `httpx.HTTPStatusError` on non-2xx responses
   - Parsed: Attempt to extract `detail` field from JSON response
   - Raised: `RuntimeError` with formatted message
   - Impact: Tool call returns error to agent via MCP

3. **No Validation Errors**
   - Pydantic models use basic field type hints; no explicit validators
   - API-level validation handled by DefectDojo server

### Error Message Format
```
"DefectDojo API Error {status_code}: {error_detail}"
```
If response is not JSON:
```
"HTTP error occurred: {status_code} - {raw_response_text}"
```

### Logging
- No structured logging implemented
- No audit trail or request/response logging
- All errors surfaced to caller only

## Architectural Patterns

### Adapter Pattern
`DefectDojoClient` adapts DefectDojo's REST API (raw HTTP) to an async Python interface. Each method corresponds 1:1 to a DefectDojo API endpoint.

### Factory / Builder Pattern
`_format_response()` acts as a conditional response factory, routing results through appropriate Pydantic models based on response structure (paginated vs. single).

### Data Transfer Object (DTO)
Pydantic models (ProductSummary, etc.) act as DTOs, decoupling internal representation from API contract. The `populate_by_name=True` config allows graceful handling of camelCase API fields.

### Alias-Based Field Mapping
Models use Pydantic's `Field(alias="...")` to handle snake_case ↔ camelCase conversion transparently:
```python
product_id: int = Field(alias="product")  # API sends "product", we expose "product_id"
```

### Async/Await Pattern
All I/O operations (HTTP, DNS) are async via `httpx.AsyncClient`, enabling concurrent tool calls from agents.

### Layered Architecture
- **Tool Layer** (server.py): business logic, tool definitions, request routing
- **Client Layer** (client.py): HTTP marshaling, authentication, error handling
- **Model Layer** (models.py): data validation, serialization

## Key Observations

### Architectural Strengths
1. **Clean Separation of Concerns:** Tool definitions are isolated from HTTP logic and data validation.
2. **Async-First:** httpx.AsyncClient and async/await throughout enables high concurrency.
3. **Extensibility:** Adding new entities (e.g., Vulnerabilities) requires only:
   - New Pydantic model in models.py
   - New client methods in client.py
   - New tool functions in server.py
4. **Type Safety:** Pydantic v2 provides runtime validation and IDE support via type hints.
5. **Error Resilience:** HTTPStatusError is caught and re-raised as RuntimeError, preventing protocol-level crashes.

### Architectural Weaknesses / Gaps
1. **No Retry Logic:** Client makes single-shot requests; no exponential backoff or transient error handling.
2. **No Logging/Audit Trail:** All errors and requests are silent to external observers. Difficult to diagnose failures.
3. **No Response Caching:** Every tool call hits DefectDojo API; no caching layer for frequently accessed data (e.g., product lists).
4. **Hardcoded Pagination Defaults:** limit=20, offset=0 are baked into tool signatures; agents cannot request full dataset easily.
5. **No Field Validation:** Pydantic models accept any type that fits the schema; no domain-specific validation (e.g., severity in ["low", "medium", "high"]).
6. **Incomplete DTO Coverage:** Models only include summary fields; full payload (e.g., all Finding fields) not represented.
7. **No Rate Limiting:** No client-side rate limit detection or backoff; possible to trigger DefectDojo throttling.
8. **Config Redundancy:** DEFECTDOJO_URL and DEFECTDOJO_API_KEY must be set per server instance; no Vault integration in runtime (only at Ansible deploy time).

### Unusual Patterns
1. **main() stub in __init__.py:** Exports a no-op `main()` function. The actual entry point is `server:main`, not `__init__:main`. This stub is unused.
2. **_format_response() as conditional router:** Uses isinstance and dict key checks to infer response structure. Fragile if API changes response envelope.
3. **Update Finding with **kwargs:** `update_finding()` accepts arbitrary keyword arguments and passes them directly to PATCH. Relies on DefectDojo to validate; Python layer has no type safety for optional fields.

### Missing Capabilities
1. **Delete operations:** No tool to delete products, engagements, tests, or findings.
2. **Bulk operations:** No batch create/update.
3. **Search/Filter:** Findings list supports only test_id filter; no advanced search (e.g., by severity, status).
4. **Webhooks/Subscriptions:** No subscription to DefectDojo events.
5. **Product Types, Test Types:** No tools to list/manage product and test type lookups.

### Deployment Readiness
1. **Container Image:** Dockerfile exists; can be deployed to Laima network.
2. **Health Check:** Stub health_check() tool exists; no actual liveness probe.
3. **Configuration Management:** Environment variable based; compatible with Vault injection via Ansible.
4. **Async Runtime:** Requires async event loop (uvicorn or similar for production).

## Functional Coverage

### DefectDojo Resource Hierarchy
```
Product
  ├─ Engagement
  │  ├─ Test
  │  │  └─ Finding (results from a test)
```

### Tool Coverage by Resource
| Resource | List | Get | Create | Update | Delete |
|----------|------|-----|--------|--------|--------|
| Product | ✓ | ✓ | ✓ | — | — |
| Engagement | ✓ | ✓ | ✓ | — | — |
| Test | ✓ | ✓ | ✓ | — | — |
| Finding | ✓ | ✓ | ✓ | ✓ | — |
| Vulnerability | — | — | — | — | — |

### CRUD Coverage
- **Read:** Full (list + get for all resources)
- **Create:** Full (products, engagements, tests, findings)
- **Update:** Partial (findings only)
- **Delete:** None

## Performance Characteristics

### Time Complexity
- **List operations:** O(limit) network calls; server handles pagination via offset/limit params
- **Get operations:** O(1) network calls per ID
- **Create operations:** O(1) network calls
- **Update operations:** O(1) network calls

### Concurrency
- Async/await pattern allows 100s of concurrent tool calls (limited by httpx connection pool, default ~100)
- No connection pooling tuning; uses httpx defaults

### Memory
- DefectDojoClient maintains single httpx.AsyncClient (persistent connection pool)
- Pydantic models are lightweight; no caching layer

## State Management

### Server State
- **Stateless MCP:** All state is external (DefectDojo)
- **Client State:** Single DefectDojoClient instance per server process (shared across all agents)
- **Session State:** None; each tool call is independent

### Connection State
- httpx.AsyncClient manages connection pool internally
- Connections are persistent within a server process lifetime
- No explicit connection lifecycle management

## Testing Surface
No test files found in repository. The project relies on:
1. Integration testing (real DefectDojo instance required)
2. Manual verification
3. TITAN audit phase (automated by CI/CD)

## Deliverables Status
- **Phase 01:** Complete (core CRUD, 14 tools, health check)
- **Phase 02:** Complete (finding management enhancements)
- **Phase 03:** Complete (error translation, pagination limits)
- **Current:** v0.1.0 shipped, audited

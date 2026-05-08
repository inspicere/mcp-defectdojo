# Conventions Analysis — mcp-defectdojo

## Summary
The mcp-defectdojo project is a Python MCP (Model Context Protocol) server with a lean, modern codebase following TITAN phase-based development. The style emphasizes async/await patterns, Pydantic v2 for data validation, semantic versioning via conventional commits with phase prefixes, and clean separation of concerns (client, server, models). All code is simple, readable, and purpose-built for DefectDojo integration rather than generic abstractions.

## Naming
| Element | Convention | Example |
|---------|-----------|---------|
| **Files** | Lowercase with underscores | `server.py`, `client.py`, `models.py` |
| **Modules** | Package name: `mcp_defectdojo` (snake_case with underscore) | `src/mcp_defectdojo/` |
| **Classes** | PascalCase with semantic suffixes | `DefectDojoClient`, `ProductSummary`, `EngagementSummary` |
| **Functions** | Lowercase with underscores; private functions prefixed with `_` | `_format_response()`, `list_products()`, `get_products()` |
| **Methods** | Lowercase with underscores, HTTP verbs for client methods | `get_products()`, `create_product()`, `update_finding()` |
| **Variables** | Lowercase with underscores; semantic names | `base_url`, `api_key`, `product_id`, `engagement_id` |
| **Async Functions** | Declared with `async def`, named consistently with sync counterparts | `async def get_products()` |
| **MCP Tools** | Verb + noun, snake_case | `list_products`, `get_finding`, `create_engagement`, `update_finding` |
| **Constants** | Uppercase with underscores (limited use, mostly environment variable names) | `DEFECTDOJO_URL`, `DEFECTDOJO_API_KEY` |
| **Pydantic Models** | PascalCase with `Summary` suffix (read-only DTOs) | `ProductSummary`, `FindingSummary`, `TestSummary` |
| **Type Hints** | Explicit, using `typing` and `Optional` | `Optional[int]`, `Dict[str, Any]`, `List[str]` |

## Formatting
| Rule | Value |
|------|-------|
| **Indentation** | Spaces, 4 spaces per level (standard Python) |
| **Line Length** | Pragmatic, observed max ~136 characters (lines 100-107 chars common) |
| **Quotes** | Double quotes for strings (consistent throughout) |
| **Trailing Commas** | Present in multi-line structures (e.g., function signatures, data literals) |
| **Blank Lines** | 2 blank lines between top-level definitions (PEP 8); 1 blank line between methods in classes |
| **Import Style** | Alphabetical within groups, no blank lines between imports in same group |
| **Async/Await** | Consistent use of `async def` and `await` for all HTTP operations |
| **String Formatting** | f-strings for simple formatting; JSON for complex data |
| **Comparisons** | Explicit `is not None` checks (e.g., `if test_id is not None:`) |

## File Structure
### Typical Python File Layout
```python
# 1. Imports (stdlib first, then third-party, then internal)
import json
from typing import Optional
from mcp.server.fastmcp import FastMCP

# 2. Blank line

# 3. Module-level definitions (FastMCP instance, client instance)
mcp = FastMCP("mcp-defectdojo")
client = DefectDojoClient()

# 4. Utility/helper functions (prefixed with _)
def _format_response(result, model):
    ...

# 5. Main tool functions (decorated with @mcp.tool())
@mcp.tool()
async def health_check() -> str:
    ...

# 6. Comments separating tool groups (# --- Product Tools ---)

# 7. Main entry point or class methods at end
def main():
    ...

if __name__ == "__main__":
    main()
```

### Directory Layout
```
/home/terrabot/mcp-defectdojo/
├── src/mcp_defectdojo/
│   ├── __init__.py       (minimal)
│   ├── server.py          (MCP server, tool definitions)
│   ├── client.py          (DefectDojoClient class)
│   └── models.py          (Pydantic DTOs)
├── pyproject.toml         (uv project config)
├── uv.lock                (locked dependencies)
├── .env.example           (environment template)
├── README.md              (user documentation)
├── Dockerfile             (containerization)
└── .titan/                (TITAN phase tracking, architecture decisions)
```

## Testing
| Aspect | Convention |
|--------|-----------|
| **Test Files** | Not yet implemented; would follow `test_*.py` pattern |
| **Test Framework** | Likely `pytest` (mentioned in README but no tests present) |
| **Fixture Patterns** | N/A — no test suite yet |
| **Mocking** | N/A |
| **Coverage** | No coverage tracking present |

## Documentation
- **Docstrings:** Present on all tool functions (one-liner summaries) and method signatures (basic descriptions of parameters).
- **Inline Comments:** Minimal; only clarify non-obvious logic (e.g., "It's a paginated list" in `_format_response()`).
- **README:** High-level overview with Features, Configuration, Usage, Architecture sections.
- **CLAUDE.md:** Project context and conventions for TITAN framework; references STATE, DECISIONS, KNOWLEDGE.
- **Phase Documentation:** Comprehensive plans, summaries, and evaluation reports in `.titan/` for each phase.
- **Code Comments:** Focus on "why" (e.g., filtering None values in `update_finding()`) rather than "what" (code is self-documenting).

## Design Patterns

| Pattern | Location | Usage |
|---------|----------|-------|
| **Factory** | `DefectDojoClient.__init__()` | Initializes singleton HTTP client with environment configuration |
| **Repository** | `DefectDojoClient` | Encapsulates all HTTP operations for a domain entity |
| **Adapter** | `_format_response()` | Translates API responses to Pydantic models and JSON strings |
| **Decorator** | `@mcp.tool()` | Registers functions as MCP-accessible tools |
| **Data Transfer Object** | `ProductSummary`, `FindingSummary`, etc. | Pydantic models strip verbose API responses to essential fields |
| **Singleton** | `mcp` instance in `server.py` | Single FastMCP server instance manages all tools |
| **Command Pattern** | MCP tool functions | Each tool is an isolated, stateless command |

## Explicit Rules
From **CLAUDE.md**:
- **Commits:** Format as `titan(phase-NN): description` — atomic, one per task.
- **Branches:** Name as `titan/phase-NN-name` — one per phase.
- **Verification:** Mandatory after every build phase.
- **State Management:** Always update STATE.md after completing work.

From **pyproject.toml**:
- **Python Version:** `>=3.12` (modern, async-native).
- **Build System:** `uv_build` (hash-locked dependencies for supply-chain security).
- **Entry Point:** `mcp-defectdojo = "mcp_defectdojo.server:main"`.

From **Dockerfile**:
- **Base Image:** `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` (minimal, uv-native).
- **Build:** `uv sync --frozen --no-dev` (reproducible, no dev dependencies in production).
- **Bytecode:** Enabled via `UV_COMPILE_BYTECODE=1` (faster cold starts).

From **.gitignore**:
- Exclude `__pycache__/`, `.venv/`, `.idea/`, `.vscode/`, `*.swp`, `.titan/` (TITAN state).
- Track `uv.lock` (hash-based reproducibility).

## Implicit Rules
1. **Async-first:** All I/O operations (HTTP requests) use `async def` and `await`. No synchronous blocking operations in tools.
2. **Error Transparency:** `_request()` catches `HTTPStatusError` and wraps it in `RuntimeError` with formatted JSON details.
3. **Pagination via Parameters:** `list_*` tools accept `limit` and `offset` parameters; defaults are `limit=20, offset=0`.
4. **Optional Parameters:** Filtering is done post-fetch in client methods (e.g., `if test_id is not None: params["test"] = test_id`).
5. **JSON Formatting:** All tool responses are JSON strings (via `json.dumps(..., indent=2)` for readability).
6. **Pydantic Aliasing:** Models use `Field(alias="...")` to map camelCase API responses to snake_case Python attributes.
7. **Single Responsibility:** Each file has one purpose: `server.py` = tools, `client.py` = HTTP logic, `models.py` = data schemas.
8. **Environment First:** Configuration is loaded from `.env` via `python-dotenv` in client constructor; early validation of required vars.
9. **Token Efficiency:** Pydantic models only include fields relevant to LLM decision-making (strips verbose API bloat).

## Git Conventions

### Commit Message Format
```
<type>(scope): <subject>

<body>
```

**Type** (observed):
- `feat` — New feature (e.g., `feat: Phase 02 Finding Management build step`)
- `docs` — Documentation updates (e.g., `docs(titan): add verification reports`)
- `chore` — Build, config, dependency updates (e.g., `chore(titan): phase-01 initialization`)
- `titan` — TITAN framework tasks (e.g., `titan(phase-01): audit completion`)
- `build` — Build system or project initialization (e.g., `build: complete Phase 01 tasks`)
- `fix` — Bug fixes (e.g., `titan(audit): fix audit findings`)

**Scope** (observed):
- `titan` — TITAN-related changes
- `phase-NN` — Phase-specific work
- Omitted for simple changes

**Subject**:
- Lowercase, imperative mood (e.g., "add", "implement", "fix"), no period.
- Short (under 50 characters preferred, observed up to 90).

**Body**:
- Explains "why", not "what" (what is visible in diff).
- Free-form or bullet-point format.

### Branch Naming
- **Format:** `titan/phase-NN-<description>`
- **Example:** `titan/phase-01-core-operations`, `titan/phase-02-finding-management`, `titan/phase-01-deployment-configuration`
- **Main:** `main` branch for releases.

## Inconsistencies
1. **README.md Mismatch:** Documentation mentions 14 tools and `list_vulnerabilities`, but only 11 tools exist in `server.py` (no vulnerabilities endpoint implemented).
2. **Environment Variable Naming:** Code uses `DEFECTDOJO_API_KEY` in client, but README references `DEFECTDOJO_API_TOKEN`.
3. **Unused Imports:** `Dict`, `List` imported in `client.py` but not used (only `Any`).
4. **Docstring Completeness:** Some tools lack detailed parameter descriptions (e.g., `create_test()` doesn't explain `test_type_id`).
5. **Error Handling in `_request()`:** Nested try/except inside the HTTPStatusError handler is overly defensive; the outer exception handler catches everything, making the inner one unreachable if JSON parsing fails in isolation.

## Type Annotation Practices
- **Explicit Typing:** All function signatures include return type hints.
- **Optional:** Used for nullable fields (e.g., `Optional[int]`, `Optional[str]`).
- **Any:** Used when API response structure is dynamic or unvalidated (e.g., `async def _request(...) -> Any`).
- **Pydantic Validation:** Models use `BaseModel` with field annotations; `populate_by_name=True` allows both alias and snake_case names.
- **Generic Types:** Minimal use (observed in `Dict[str, Any]` for headers and JSON payloads).

## Dependency Philosophy
- **Core:** `mcp` (Model Context Protocol), `fastmcp` (server framework), `httpx` (async HTTP).
- **Data:** `pydantic` (v2, for validation and serialization).
- **Configuration:** `python-dotenv` (environment variables).
- **Build:** `uv` (package manager with hash-based locking).
- **Version Pinning:** `pyproject.toml` uses `>=` constraints (e.g., `httpx>=0.28.1`) with lockfile enforcing exact versions.

## Development Workflow
1. **TITAN Phases:** Work is organized into phases (01-core, 02-findings, 03-optimization, etc.).
2. **Task Tracking:** Each phase has a PLAN.md with acceptance criteria, tasks, and file boundaries.
3. **Verification:** After each phase, run `/titan:verify` to check architecture, code quality, and acceptance criteria.
4. **State Management:** Keep `.titan/STATE.md` updated with phase progress, decisions in `.titan/DECISIONS.md`, and learnings in `.titan/KNOWLEDGE.md`.
5. **Documentation:** Archive completed phases in `.titan/archive/v<version>/phases/` with evaluation reports.

## Summary Table
| Aspect | Standard |
|--------|----------|
| **Language** | Python 3.12+ |
| **Async Runtime** | Native asyncio |
| **Web Framework** | FastMCP (MCP-native) |
| **HTTP Client** | httpx (async) |
| **Data Validation** | Pydantic v2 |
| **Package Manager** | uv (hash-locked) |
| **Deployment** | Docker (bookworm-slim) |
| **Code Style** | PEP 8 (implicit; no linter config found) |
| **VCS Workflow** | TITAN phases → atomic commits → main |
| **Commit Format** | `<type>(<scope>): <subject>` |
| **Comments** | Rare; self-documenting code preferred |
| **Tests** | Not yet present (pytest ready) |
| **Security** | Environment-based config, Bearer token auth |


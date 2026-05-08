# Stack Analysis

## Summary
mcp-defectdojo is a Python 3.12+ MCP server built on FastMCP 3.2.4 with Pydantic v2 for data validation and httpx for async HTTP communication with DefectDojo. The project uses uv as its package manager with a deterministic lockfile, and ships with a Dockerfile based on Debian bookworm-slim. The codebase is lean (278 lines across 4 Python files) and entirely async.

## Languages
| Language | Version | File Count | Lines (approx) |
|----------|---------|------------|-----------------|
| Python | 3.12+ | 4 | 278 |
| YAML | — | 2 | ~80 |
| Markdown | — | 5 | ~2,500 |
| Dockerfile | — | 1 | ~15 |

## Frameworks
| Framework | Version | Latest | Status |
|-----------|---------|--------|--------|
| FastMCP | 3.2.4 | 3.2.4 | Current |
| Pydantic | 2.13.3 | 2.13.3 | Current |
| httpx | 0.28.1 | 0.28.1 | Current |
| mcp | 1.27.0 | 1.27.0 | Current |
| python-dotenv | 1.2.2 | 1.2.2 | Current |

## Dependencies
- Direct: 5 (fastmcp, httpx, mcp, pydantic, python-dotenv)
- Dev: 0 (none declared)
- Transitive: 74
- Outdated (major): none detected
- Outdated (minor): none detected

### Direct Dependencies
1. `fastmcp >=3.2.4` — MCP server framework, tool registration, SSE transport
2. `httpx >=0.28.1` — Async HTTP client for DefectDojo API calls
3. `mcp >=1.27.0` — Reference MCP protocol implementation
4. `pydantic >=2.13.3` — Data validation with alias mapping
5. `python-dotenv >=1.2.2` — Environment variable loading from .env files

### Notable Transitive Dependencies
- anyio 4.13.0 — async primitives
- httpcore 1.0.9 — low-level HTTP transport
- httpx-sse 0.4.3 — SSE support for MCP transport
- uvicorn — ASGI server (via mcp)
- starlette — ASGI framework (via mcp)
- cryptography 47.0.0 — crypto operations
- opentelemetry-api — observability hooks

## Build System
- **Build tool:** uv_build (Rust-based, `>=0.11.5,<0.12.0`)
- **Entry point:** `mcp-defectdojo = "mcp_defectdojo.server:main"`
- **Lock file:** `uv.lock` (1,254 lines, revision 3, deterministic)
- **Docker:** Single-stage build from `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- **Docker optimizations:** Bytecode compilation (`UV_COMPILE_BYTECODE=1`), frozen lockfile (`uv sync --frozen --no-dev`)

## Package Manager
- **Tool:** uv (Astral's Rust-based Python package manager)
- **Lock file:** `uv.lock` — present, fresh, all transitive deps pinned with checksums
- **Python requirement:** >=3.12
- **Workflow:** Dependencies in `pyproject.toml` → `uv lock` → `uv sync --frozen`

## Runtime
- **Required:** Python >=3.12 (pyproject.toml `requires-python`)
- **Pinned:** Python 3.12 (`.python-version` file)
- **Available:** Python 3.13.5 (system)
- **Transport:** SSE (Server-Sent Events) for MCP protocol
- **Execution:** `uv run mcp-defectdojo` or direct entry point script

## Dev Tooling
- **Linting:** None configured (README mentions ruff but not in deps)
- **Formatting:** None configured
- **Type checking:** None configured (Pydantic provides runtime validation)
- **Pre-commit:** Not configured
- **Editor config:** Not present

## CI/CD
- **Pipelines:** None (no .github/workflows/, .gitlab-ci.yml, or Forgejo Actions)
- **Automated testing:** None
- **Build automation:** Manual via local commands
- **TITAN integration:** Phase-based workflow via slash commands

## Testing Stack
- **Status:** No tests exist
- **Test runner:** None configured (README mentions pytest)
- **Async testing:** Not configured (pytest-asyncio absent)
- **Mocking:** Not configured
- **Coverage:** Not configured

## Infrastructure
- **Dockerfile:** Present, production-ready single-stage build
- **Base image:** `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- **Orchestration:** None (no docker-compose, k8s, or Helm)
- **Configuration:** Environment variables via `.env` + `python-dotenv`
- **External services:** DefectDojo API (remote, Bearer token auth)
- **Deployment target:** Laima homelab infrastructure (Ansible-managed)

## Key Observations
- **All dependencies are current** — no version lag across the entire 74-package tree
- **Zero dev dependencies declared** — pytest, ruff mentioned in README but not in pyproject.toml
- **uv provides excellent build reproducibility** — lockfile with checksums and multi-Python wheel variants
- **Container-first design** — Dockerfile present but no orchestration layer
- **Missing production tooling** — no logging framework, no retry library (tenacity mentioned in README but absent), no structured observability
- **Minimal footprint** — 5 direct deps for a focused, stateless adapter service

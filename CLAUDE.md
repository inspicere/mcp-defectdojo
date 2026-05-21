# CLAUDE.md

> Loaded automatically by Claude Code at the start of every session.

## Project

**mcp-defectdojo** — MCP server for DefectDojo vulnerability management.

- Python 3.12+, FastMCP framework, httpx async HTTP client
- 24 MCP tools with RBAC (4 roles, 6 permission groups)
- Structured JSON audit logging with HMAC integrity chain

## Architecture

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastMCP tool definitions, input validation, response formatting |
| `client.py` | httpx async client, dual API key routing, error sanitization |
| `models.py` | Pydantic response models (strict validation) |
| `rbac.py` | Role-based access control, token-role binding |
| `security.py` | Rate limiting, field length validation |
| `audit_logging.py` | Structured JSON logging, HMAC chain, secret redaction, SIEM forwarding |

## Development

```bash
uv sync                              # Install with dev dependencies
uv run pytest --tb=short -q --cov    # Run tests with coverage
uv run pip-audit                     # Dependency vulnerability scan
```

## Conventions

- Tests live in `tests/` — one test file per source module plus feature-focused files
- All tools use `_format_response()` for Pydantic-validated JSON output
- Write tools are rate-limited via `MutationRateLimiter`
- Error messages to MCP clients are sanitized — never expose internal field names
- Secrets are redacted from all log output via `RedactingFilter`

## Releases (PyPI + MCP Registry)

Public package: `mcp-defectdojo` on PyPI (since v3.2.6, 2026-05-21). Registry server: `io.github.inspicere/mcp-defectdojo`.

**PyPI publish** — token in Vault at `secret/pypi` (project-scoped, named after the project). Use the pipe pattern; never inline:

```bash
uv build
twine check dist/*
vault kv get -field=token secret/pypi | UV_PUBLISH_TOKEN=$(cat) uv publish
```

**MCP Registry publish** — `mcp-publisher 1.7.9` at `/usr/local/bin/mcp-publisher` (Linux amd64, installed via curl one-liner — no Homebrew). Login is interactive device-code OAuth (`mcp-publisher login github`); the publish step itself is non-interactive:

```bash
mcp-publisher publish   # reads ./server.json
```

**Gotchas**:

- The registry `description` field is capped at **100 chars**; PyPI's `pyproject.description` is not. Keep server.json's description short.
- PyPI ownership verification reads the rendered README from the package description and looks for the HTML comment `<!-- mcp-name: io.github.<user>/<name> -->`. The marker MUST be in the PyPI release BEFORE the registry publish — order matters.
- Bump `pyproject.toml` `version` AND the `packages[].version` in `server.json` before any release.

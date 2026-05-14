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

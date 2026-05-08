# mcp-defectdojo

MCP server for DefectDojo vulnerability management integration. Provides MCP tools for AI agents to query and manage security findings, products, engagements, tests, and vulnerabilities.

## Features

- 14 MCP tools covering DefectDojo CRUD operations
- Async HTTP client with retry logic via httpx + tenacity
- Pydantic v2 models with camelCase API mapping
- Bearer token authentication
- Health check endpoint
- Structured JSON audit logging with caller identity and correlation IDs
- Sensitive data redaction (API keys, tokens never appear in logs)
- Configurable log levels via LOG_LEVEL env var

## Installation

```bash
pip install -e .
```

## Configuration

Set the following environment variables:

- `DEFECTDOJO_URL` — Base URL of your DefectDojo instance
- `DEFECTDOJO_API_TOKEN` — API token with appropriate permissions
- `LOG_LEVEL` — Log verbosity: DEBUG, INFO (default), WARNING, ERROR

## Usage

Start the MCP server:

```bash
python -m mcp_defectdojo --transport sse --port 8000
```

Or via Docker:

```bash
docker compose up -d
```

The server exposes 14 tools:

- `list_products`, `create_product`, `get_product`
- `list_engagement`, `create_engagement`, `get_engagement`
- `list_tests`, `create_test`, `get_test`
- `list_findings`, `get_finding`, `create_finding`, `update_finding`
- `list_vulnerabilities`
- `health_check` — validate DefectDojo connectivity

## Deployment

The server runs as a Docker container on mcp-host (10.0.0.10:3500) in the Laima homelab. It connects to DefectDojo at defectdojo-01 (10.0.0.20:8080) using a dedicated `svc-mcp` service account (Writer role) with the API token stored in HashiCorp Vault at `secret/mcp/defectdojo_api_key`.

### Service Account

The MCP server uses a least-privilege service account (`svc-mcp`, Writer role) instead of the admin token. This grants read + create + edit on products, engagements, tests, and findings, but denies access to user management and system settings.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .
```

## Architecture

- **server.py** — FastMCP app with SSE transport, tool registry, CLI entry point
- **client.py** — AsyncHTTPClient wrapper with retry, timeout, auth
- **models.py** — Pydantic v2 DTOs for DefectDojo API types
- **audit_logging.py** — Structured JSON formatter, RedactingFilter, audit_tool decorator, ContextVar-based request_id propagation

## License

MIT

# mcp-defectdojo

MCP server for DefectDojo vulnerability management integration. Provides MCP tools for AI agents to query and manage security findings, products, engagements, tests, and vulnerabilities.

## Features

- 14 MCP tools covering DefectDojo CRUD operations
- Async HTTP client with retry logic via httpx + tenacity
- Pydantic v2 models with camelCase API mapping
- Bearer token authentication
- Health check endpoint
- Structured logging for audit trail

## Installation

```bash
pip install -e .
```

## Configuration

Set the following environment variables:

- `DEFECTDOJO_URL` — Base URL of your DefectDojo instance
- `DEFECTDOJO_API_TOKEN` — API token with appropriate permissions

## Usage

Start the MCP server:

```bash
python -m mcp_defectdojo --transport sse --port 8000
```

The server exposes 14 tools:

- `list_products`, `create_product`
- `list_engagement`, `create_engagement`
- `list_tests`, `create_test`
- `list_findings`, `get_finding`, `update_finding`
- `list_vulnerabilities`
- `health_check` — validate DefectDojo connectivity

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

## License

MIT

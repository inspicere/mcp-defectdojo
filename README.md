# mcp-defectdojo

MCP server for [DefectDojo](https://www.defectdojo.com/) vulnerability management. Exposes 23 tools for managing products, engagements, tests, findings, scan imports, and finding lifecycle through the Model Context Protocol.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A running DefectDojo instance with API access

## Quick Start

```bash
# Clone and install
git clone <repo-url> && cd mcp-defectdojo
cp .env.example .env
# Edit .env — set DEFECTDOJO_URL and DEFECTDOJO_API_KEY at minimum
uv sync

# Run (stdio mode, for use with MCP clients)
uv run mcp-defectdojo
```

## Configuration

All configuration is via environment variables. Copy `env.example` to `.env` for local development.

### Required

| Variable | Description |
|----------|-------------|
| `DEFECTDOJO_URL` | Base URL of the DefectDojo instance (must use `https://` unless overridden) |
| `DEFECTDOJO_API_KEY` | API key for DefectDojo (generate at DefectDojo > API v2 > Your API Key) |

### Optional — Dual API Key Mode

For least-privilege access, use separate read/write keys instead of `DEFECTDOJO_API_KEY`:

| Variable | Description |
|----------|-------------|
| `DEFECTDOJO_READ_API_KEY` | Read-only API key (used for GET requests) |
| `DEFECTDOJO_WRITE_API_KEY` | Write API key (used for POST/PATCH requests) |

### Optional — MCP Authentication

| Variable | Description |
|----------|-------------|
| `MCP_AUTH_TOKEN` | Bearer token for MCP clients. Grants read + write scope. |
| `MCP_READ_TOKEN` | Read-only bearer token. Grants only read scope (list/get tools). |

### Optional — Transport

| Variable | Default | Description |
|----------|---------|-------------|
| `FASTMCP_TRANSPORT` | `stdio` | Transport mode: `stdio`, `sse`, `streamable-http`, `http` |
| `FASTMCP_HOST` | `0.0.0.0` | Bind address for network transports |
| `FASTMCP_PORT` | `8000` | Port for network transports |

### Optional — Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOW_INSECURE_HTTP` | `false` | Allow `http://` URLs (TLS required by default) |
| `MUTATION_RATE_LIMIT` | `60` | Max mutations per rate window |
| `MUTATION_RATE_WINDOW` | `60` | Rate window in seconds |

### Optional — Logging & Audit

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `AUDIT_HMAC_KEY` | *(ephemeral)* | HMAC key for audit log integrity chain. Required for cross-restart log verification. Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `AUDIT_LOG_FILE` | *(stderr only)* | Path for dedicated audit log file (JSON-lines, logrotate-compatible) |

### Optional — SIEM Log Forwarding

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_SYSLOG` | *(disabled)* | Syslog destination. Format: `[transport://]host[:port]`. Transports: `tcp`, `udp`, `tcp+tls` (default). |
| `AUDIT_LOG_SYSLOG_CA` | *(system CAs)* | Custom CA certificate for syslog TLS verification |
| `AUDIT_LOG_HTTPS_URL` | *(disabled)* | HTTPS endpoint for log forwarding (JSON array POST) |
| `AUDIT_LOG_HTTPS_TOKEN` | *(none)* | Bearer token for HTTPS endpoint authentication |
| `AUDIT_LOG_HTTPS_BATCH_SIZE` | `10` | Number of log records per HTTPS batch |
| `AUDIT_LOG_HTTPS_FLUSH_SECS` | `5` | Seconds before flushing a partial batch |

## Tools

### Read Tools (require `read` scope)

| Tool | Description |
|------|-------------|
| `health_check` | Check connectivity to DefectDojo |
| `list_products` | List products with pagination |
| `get_product` | Get a single product by ID |
| `list_product_types` | List product types (for use in `create_product`) |
| `list_engagements` | List engagements for a product |
| `get_engagement` | Get a single engagement by ID |
| `list_tests` | List tests for an engagement |
| `get_test` | Get a single test by ID |
| `list_test_types` | List test types (for use in `create_test`) |
| `list_findings` | List findings with 18 filter parameters |
| `get_finding` | Get a single finding by ID |
| `list_finding_notes` | List notes on a finding |

### Write Tools (require `write` scope, rate-limited)

| Tool | Description |
|------|-------------|
| `create_product` | Create a new product |
| `create_engagement` | Create a new engagement |
| `create_test` | Create a new test |
| `create_finding` | Create a new finding |
| `update_finding` | Update an existing finding |
| `close_finding` | Close a finding with reason (mitigated/false_positive/out_of_scope/duplicate) |
| `add_finding_note` | Attach a note to a finding |
| `add_finding_tags` | Add tags to a finding |
| `remove_finding_tags` | Remove tags from a finding |
| `import_scan` | Upload scan results (225+ scan types, multipart) |
| `reimport_scan` | Re-upload scan results to an existing test |

Write tools are subject to mutation rate limiting (default: 60 per 60s per caller).

## Security Model

- **TLS enforced** — `DEFECTDOJO_URL` must use `https://` unless `ALLOW_INSECURE_HTTP=true`
- **Per-tool scope enforcement** — Tools are gated by `read` or `write` scope via MCP auth tokens
- **Mutation rate limiting** — Sliding window per-caller rate limiter on all write operations
- **Input validation** — Field length limits, type validation, date format checking
- **Secret redaction** — All sensitive env vars are redacted from log output
- **HMAC audit chain** — Each audit log entry includes an HMAC-SHA256 computed over the previous entry, creating a tamper-evident chain
- **Structured JSON logging** — All log output is structured JSON with correlation IDs, caller identity, and duration tracking

When running on a network transport (`sse`, `http`), always set `MCP_AUTH_TOKEN`. The server logs a CRITICAL warning if auth is disabled on a network transport.

### SIEM Integration

Audit logs can be forwarded to a SIEM in three ways:

**Syslog (RFC 5424)** — TCP, UDP, or TCP+TLS. Set one env var:

```bash
AUDIT_LOG_SYSLOG=tcp+tls://syslog.example.com:6514
```

Bare hostnames default to TCP+TLS on port 6514. For custom CA certificates, set `AUDIT_LOG_SYSLOG_CA`.

**HTTPS webhook** — Posts JSON arrays to any HTTPS endpoint (Splunk HEC, Elasticsearch, Datadog, Loki):

```bash
AUDIT_LOG_HTTPS_URL=https://splunk-hec.example.com:8088/services/collector
AUDIT_LOG_HTTPS_TOKEN=your-hec-token
```

Records are batched (default: 10 records or 5 seconds) and delivered by a background thread. The HTTPS token is redacted from all log output.

**File + external shipper** — Write to a local file and ship with Filebeat, Fluentd, or similar:

```bash
AUDIT_LOG_FILE=/var/log/mcp-defectdojo/audit.log
```

All three methods output the same HMAC-chained, redacted, structured JSON. Multiple methods can be enabled simultaneously.

## Deployment

### Docker

```bash
docker build -t mcp-defectdojo .
docker run --env-file .env mcp-defectdojo
```

For network transports:

```bash
docker run --env-file .env -p 8000:8000 \
  -e FASTMCP_TRANSPORT=sse \
  mcp-defectdojo
```

### Systemd / Direct

```bash
uv sync --frozen --no-dev
uv run mcp-defectdojo
```

## Development

```bash
uv sync                    # Install with dev dependencies
uv run pytest              # Run tests
uv run pytest --cov        # Run with coverage
```

## License

See [LICENSE](LICENSE) for details.

# mcp-defectdojo

MCP server for [DefectDojo](https://www.defectdojo.com/) vulnerability management. Exposes 24 tools for managing products, engagements, tests, findings, scan imports, and finding lifecycle through the Model Context Protocol.

**[Getting Started Guide](docs/getting-started.md)** — step-by-step setup, from install through connecting your first MCP client.

## Quick Start

```bash
git clone https://github.com/inspicere/mcp-defectdojo.git && cd mcp-defectdojo
cp .env.example .env
# Edit .env — set DEFECTDOJO_URL and DEFECTDOJO_API_KEY
uv sync --frozen
uv run mcp-defectdojo
```

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and a running DefectDojo instance.

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

### Optional — MCP Authentication (RBAC)

Token-role bindings using `MCP_ROLE_*` env vars (preferred):

| Variable | Description |
|----------|-------------|
| `MCP_ROLE_<NAME>` | Format: `<token>:<role>`. Binds a bearer token to a role. Name becomes the caller ID. |

Four roles are available, each inheriting from the one below:

| Role | Permissions |
|------|------------|
| `admin` | All permissions including `product_mgmt` |
| `writer` | `engagement_mgmt`, `finding_mgmt`, `scan_mgmt`, `metadata_read`, `system` |
| `scanner` | `scan_mgmt`, `metadata_read`, `system` |
| `reader` | `metadata_read`, `system` |

Example: `MCP_ROLE_CI=tok_abc123:scanner` grants the token scanner-level access.

Legacy variables (mapped to RBAC roles for backward compatibility):

| Variable | Maps to |
|----------|---------|
| `MCP_AUTH_TOKEN` | `admin` role |
| `MCP_READ_TOKEN` | `reader` role |

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
| `MUTATION_RATE_LIMIT` | `60` | Max mutations per rate window per **authenticated** caller (per-token bucket) |
| `OPEN_ACCESS_MUTATION_RATE_LIMIT` | `10` | Max mutations per rate window across **all unauthenticated** traffic (one shared bucket — applies only when `REQUIRE_AUTH=false`) |
| `MUTATION_RATE_WINDOW` | `60` | Rate window in seconds (applies to both buckets) |

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

### Read Tools (require `metadata_read`)

| Tool | Permission | Description |
|------|------------|-------------|
| `health_check` | `system` | Check connectivity to DefectDojo |
| `list_products` | `metadata_read` | List products with pagination |
| `get_product` | `metadata_read` | Get a single product by ID |
| `list_product_types` | `metadata_read` | List product types (for use in `create_product`) |
| `list_engagements` | `metadata_read` | List engagements for a product |
| `get_engagement` | `metadata_read` | Get a single engagement by ID |
| `list_tests` | `metadata_read` | List tests for an engagement |
| `get_test` | `metadata_read` | Get a single test by ID |
| `list_test_types` | `metadata_read` | List test types (for use in `create_test`) |
| `list_findings` | `metadata_read` | List findings with 18 filter parameters |
| `get_finding` | `metadata_read` | Get a single finding by ID |
| `list_finding_notes` | `metadata_read` | List notes on a finding |

### Write Tools (rate-limited)

| Tool | Permission | Description |
|------|------------|-------------|
| `create_product` | `product_mgmt` | Create a new product |
| `create_engagement` | `engagement_mgmt` | Create a new engagement |
| `create_test` | `engagement_mgmt` | Create a new test |
| `create_finding` | `finding_mgmt` | Create a new finding |
| `update_finding` | `finding_mgmt` | Update an existing finding |
| `close_finding` | `finding_mgmt` | Close a finding with reason (mitigated/false_positive/out_of_scope/duplicate) |
| `reopen_finding` | `engagement_mgmt` | Reopen a closed finding (clears `is_mitigated`/`false_p`/`out_of_scope`/`duplicate`, sets `active=true`) |
| `add_finding_note` | `finding_mgmt` | Attach a note to a finding |
| `add_finding_tags` | `finding_mgmt` | Add tags to a finding |
| `remove_finding_tags` | `finding_mgmt` | Remove tags from a finding |
| `import_scan` | `scan_mgmt` | Upload scan results (225+ scan types, multipart) |
| `reimport_scan` | `scan_mgmt` | Re-upload scan results to an existing test |

Write tools are subject to mutation rate limiting:
- **Authenticated callers:** 60 mutations / 60s **per token** (one bucket per `MCP_ROLE_<NAME>` binding).
- **Unauthenticated callers** (only when `REQUIRE_AUTH=false`): 10 mutations / 60s **shared across all unauthenticated traffic**.

Rate-limit errors include a `Retry-After: <N>s` hint so clients can back off.

## Audit Log Field Trust Model

The audit log distinguishes between trusted and untrusted identity fields. SIEM rules and incident-response runbooks should key on the trusted fields.

| Field | Source | Trust | Use |
|-------|--------|-------|-----|
| `authenticated_caller_id` | Bearer-token-bound `client_id` (set by `MCP_ROLE_<NAME>` binding via `StaticTokenVerifier`) | **Trusted** | Authentication identity. Drives rate-limit bucketing and access-control decisions. Always `"open-access"` when no auth is configured. |
| `caller_id` | `_meta.client_id` from the inbound JSON-RPC request body | **Untrusted** (client-controlled) | Tracing / forensic correlation only. Kept for SIEM backward compatibility. May be spoofed — never use as an authorization or rate-limit key. |
| `request_id` | Per-call MCP request ID | Trusted (server-generated) | Per-call correlation across log lines. |

When `authenticated_caller_id == "open-access"`, the server emits a `security_warning` log line on every tool call (with `meta_caller_id` recording the legacy meta value for forensics) so SIEM operators can detect unauthenticated traffic on production deployments.

## Security Model

- **TLS enforced** — `DEFECTDOJO_URL` must use `https://` unless `ALLOW_INSECURE_HTTP=true`
- **RBAC enforcement** — 4-role model (admin/writer/scanner/reader) with 6 permission groups; each tool requires a specific permission
- **Mutation rate limiting** — Sliding window per-caller rate limiter on all write operations
- **Input validation** — Field length limits, type validation, date format checking
- **Error sanitization** — API error responses are mapped to generic messages; internal field names and validation rules are never exposed to MCP clients
- **Secret redaction** — All sensitive env vars are redacted from log output
- **HMAC audit chain** — Each audit log entry includes an HMAC-SHA256 computed over the previous entry, creating a tamper-evident chain
- **Structured JSON logging** — All log output is structured JSON with correlation IDs, caller identity, and duration tracking

When running on a network transport (`sse`, `http`), authentication is **required by default**. The server will refuse to start without at least one auth token configured. Set `REQUIRE_AUTH=false` to explicitly allow unauthenticated access (not recommended for production).

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUIRE_AUTH` | *(enforced)* | Set to `false` to allow unauthenticated network access |

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

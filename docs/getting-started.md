# Getting Started

This guide walks you through installing, configuring, and connecting mcp-defectdojo to your DefectDojo instance.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** package manager (or Docker)
- A running **DefectDojo** instance with API access
- A DefectDojo **API key** (generate at: DefectDojo → API v2 → Your Token)

## Step 1: Install

### Option A: uv (recommended for development)

```bash
git clone https://github.com/inspicere/mcp-defectdojo.git
cd mcp-defectdojo
uv sync --frozen
```

### Option B: Docker

```bash
git clone https://github.com/inspicere/mcp-defectdojo.git
cd mcp-defectdojo
docker build -t mcp-defectdojo .
```

## Step 2: Configure

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with the two required variables:

```env
DEFECTDOJO_URL=https://your-defectdojo-instance.example.com
DEFECTDOJO_API_KEY=your_api_key_here
```

> **Note:** The URL must use `https://`. If your instance uses plain HTTP (not recommended), set `ALLOW_INSECURE_HTTP=true`.

## Step 3: Verify connectivity

Start the server in stdio mode and confirm it can reach DefectDojo:

```bash
# With uv
uv run mcp-defectdojo

# With Docker
docker run --env-file .env mcp-defectdojo
```

The server starts and waits for MCP client connections. If the DefectDojo URL or API key is wrong, you'll see an error on startup.

To test connectivity independently, you can use the MCP inspector or any MCP client to call the `health_check` tool. It returns:

```json
{"status": "ok", "message": "DefectDojo is reachable"}
```

## Step 4: Connect an MCP client

### Claude Desktop

Add to your Claude Desktop MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "defectdojo": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcp-defectdojo", "run", "mcp-defectdojo"],
      "env": {
        "DEFECTDOJO_URL": "https://your-defectdojo-instance.example.com",
        "DEFECTDOJO_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Claude Code

Add to your MCP settings (`.mcp.json` or project settings):

```json
{
  "mcpServers": {
    "defectdojo": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcp-defectdojo", "run", "mcp-defectdojo"],
      "env": {
        "DEFECTDOJO_URL": "https://your-defectdojo-instance.example.com",
        "DEFECTDOJO_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### Network transport (multi-client)

For shared deployments where multiple clients connect over the network:

```bash
# .env additions
FASTMCP_TRANSPORT=sse
FASTMCP_HOST=0.0.0.0
FASTMCP_PORT=8000
MCP_ROLE_CI=tok_scanner_abc:scanner
MCP_ROLE_ANALYST=tok_analyst_xyz:writer
```

```bash
# Start the server
uv run mcp-defectdojo

# Or with Docker
docker run --env-file .env -p 8000:8000 mcp-defectdojo
```

Clients connect to `http://localhost:8000/sse` (or your host/port) with their assigned bearer token.

## Step 5: Secure for production

For stdio mode (single-user, local), no additional auth is needed — the OS process boundary provides isolation.

For network transports, authentication is **required by default**. Configure at least one token:

```env
# Simple: single admin token
MCP_AUTH_TOKEN=your_secret_bearer_token

# Better: role-based tokens with least privilege
MCP_ROLE_CI=tok_ci_abc123:scanner
MCP_ROLE_ANALYST=tok_analyst_xyz:writer
MCP_ROLE_ADMIN=tok_admin_secret:admin
```

### Roles and permissions

| Role | Can do |
|------|--------|
| `reader` | List and get products, engagements, tests, findings |
| `scanner` | Everything in reader + import/reimport scans |
| `writer` | Everything in scanner + create/update/close findings, manage engagements |
| `admin` | Everything in writer + create products |

### Dual API keys (least privilege on DefectDojo side)

Create two API keys in DefectDojo — one with read-only permissions and one with write:

```env
DEFECTDOJO_READ_API_KEY=read_only_key_here
DEFECTDOJO_WRITE_API_KEY=write_key_here
```

When both are set, GET requests use the read key and mutations use the write key.

## Step 6: Enable audit logging (optional)

For compliance or incident response, enable persistent audit logs:

```env
# Write audit logs to a file (JSON-lines, logrotate-compatible)
AUDIT_LOG_FILE=/var/log/mcp-defectdojo/audit.log

# HMAC key for tamper-evident log chain (persists across restarts)
# Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
AUDIT_HMAC_KEY=your_generated_hex_key
```

### SIEM forwarding

Forward audit logs to your SIEM in real-time:

```env
# Syslog (TCP+TLS)
AUDIT_LOG_SYSLOG=tcp+tls://syslog.example.com:6514

# Or HTTPS webhook (Splunk HEC, Elasticsearch, Datadog, Loki)
AUDIT_LOG_HTTPS_URL=https://splunk-hec.example.com:8088/services/collector
AUDIT_LOG_HTTPS_TOKEN=your_hec_token
```

## Next steps

- See [README.md](../README.md) for the full configuration reference and tool list
- See [CHANGELOG.md](../CHANGELOG.md) for version history
- Run `uv run pytest` to verify your installation with the test suite

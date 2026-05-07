# Architecture — mcp-defectdojo

## Deployment Architecture
The MCP server will be deployed as a containerized service managed by systemd or a container orchestrator in the Laima network, with configuration injected via environment variables managed by Vault.

```text
+---------------------+
|   Laima Infrastructure|
|  +---------------+  |
|  |     Vault     |  |
|  +-------+-------+  |
|          |          |
|  +-------v-------+  |
|  |   MCP Server  |  |
|  |  (Container)  |  |
|  +---------------+  |
+---------------------+
```

## Security Architecture
- **Configuration:** API keys retrieved from HashiCorp Vault at runtime.
- **Isolation:** Service runs as a non-root user within the container.

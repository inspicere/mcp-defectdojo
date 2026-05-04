# Requirements — mcp-defectdojo

## Functional Requirements

### Must-Have (P0)

#### FR-006: Containerization
The MCP server must be containerized to run in the Laima network.
**Acceptance Criteria:**
- Given a Dockerfile, When the image is built, Then it starts the MCP server using `uv run mcp-defectdojo`.

#### FR-007: Deployment Automation
The MCP server must be deployable via Ansible.
**Acceptance Criteria:**
- Given an Ansible playbook, When executed, Then the container is deployed and running on the target Laima host.

#### FR-008: Health Check Endpoint
The server must provide a health status.
**Acceptance Criteria:**
- Given a running service, When health-checked, Then it returns a 200 OK status.

### Non-Functional Requirements (NFR)

#### NFR-003: Configuration
Deployment must use secrets management from the Vault to inject `DEFECTDOJO_API_KEY`.

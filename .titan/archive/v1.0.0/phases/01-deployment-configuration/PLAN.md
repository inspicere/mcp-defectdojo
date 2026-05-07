---
phase: 01
name: Deployment Configuration
goal: Deploy MCP server to Laima network
branch: titan/phase-01-deployment-configuration
status: approved
created: 2026-05-04T05:30:00Z
estimated_tasks: 3
estimated_waves: 2
---

# Phase 01 — Deployment Configuration — Execution Plan

## Goal
Deploy the `mcp-defectdojo` server as a containerized service on Laima infrastructure.

## Context
- The project is now stable (v0.1.0). 
- Goal is to containerize and automate deployment via Ansible using Vault for secrets.

## Acceptance Criteria (This Phase)
- FR-006: Containerization (Dockerfile exists and image builds)
- FR-007: Deployment automation (Ansible playbook exists)
- FR-008: Health Check Endpoint (FastMCP standard endpoint)
- NFR-003: Vault integration

## Tasks
### Task T1: Containerize MCP Server
- **AC**: FR-006
- **Mode**: agent
- **Files to Modify**: None
- **Files to Create**: `Dockerfile`
- **Files to Read**: `pyproject.toml`, `uv.lock`
- **Action**: Create a `Dockerfile` that uses the `ghcr.io/astral-sh/uv` image, copies the source code, and builds/installs dependencies. Entrypoint: `uv run mcp-defectdojo`.
- **Verification Steps**: 1. `docker build -t mcp-defectdojo .` 2. Confirm image is built.
- **Done Criteria**: Image built successfully.

### Task T2: Implement Health Check Endpoint
- **AC**: FR-008
- **Mode**: agent
- **Files to Modify**: `src/mcp_defectdojo/server.py`
- **Files to Create**: None
- **Files to Read**: None
- **Action**: Add a simple health check function decorated with `@mcp.tool()` or a custom route if FastMCP supports standard HTTP.
- **Verification Steps**: `curl localhost:8080/health` (or equivalent).
- **Done Criteria**: Endpoint returns 200 OK.

### Task T3: Ansible Deployment Playbook
- **AC**: FR-007, NFR-003
- **Mode**: in-session
- **Files to Modify**: None
- **Files to Create**: `deploy/playbook.yml`
- **Files to Read**: `Dockerfile`
- **Action**: Create an Ansible playbook that pulls secrets from Vault, builds/runs the container, and sets environment variables.
- **Verification Steps**: Playbook dry-run (check) succeeds.
- **Done Criteria**: Playbook written and reviewed.

## Execution Strategy
### Wave 1 — Containerization & Health (parallel)
- T1: Containerize
- T2: Health Check

### Wave 2 — Deployment Automation
- T3: Ansible Playbook

## Boundaries — DO NOT MODIFY
- `src/mcp_defectdojo/*.py` (Logic)

## Checkpoints
| # | After | Type | Description |
|---|-------|------|-------------|
| 1 | Wave 1 | human-verify | Confirm Dockerfile and health check |

## Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Vault secrets failure | Medium | High | Use Ansible `vault_kv` lookup with dry-run |
| Container image size | Low | Medium | Use multi-stage build |

## Validation
- [x] Every AC has at least one task
- [x] Every task has verification steps
- [x] Boundaries are explicit
- [x] Wave dependencies are acyclic
- [x] Total scope fits context budget
EOF
,path:
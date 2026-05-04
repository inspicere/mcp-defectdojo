# Project Vision — mcp-defectdojo

## Vision Statement
An MCP server that provides a clean, token-efficient tool interface for AI agents to interact with DefectDojo. It acts as a reliable bridge, eliminating the need for agents to research raw API syntax or handle authentication, thereby saving tokens and reducing hallucinations.

## Problem Statement
When AI agents interact directly with the DefectDojo API, they must repeatedly research authentication flows and endpoint syntax. This wastes context window tokens, costs real money, and increases the likelihood of API errors and hallucinations.

## Target Users
### Primary
- **Homelab Owners and Security Hobbyists:** Using AI agents to automate risk management, triage vulnerabilities, and track security posture without manual GUI interaction.
### Secondary
- **Security Engineers and Developers:** Using autonomous agents to integrate DefectDojo into enterprise CI/CD pipelines or security operations centers.

## Competitive Landscape
| Existing Solution | Strengths | Weaknesses | Our Differentiator |
|-------------------|-----------|------------|-------------------|
| Raw REST API | Full coverage | Requires agent to learn/auth per session | Abstracted as direct, LLM-friendly tools via MCP |

## Success Criteria
1. Agents can successfully manage the engagement lifecycle (Products, Engagements, Tests, Findings) using MCP tools.
2. Significant reduction in token usage for DefectDojo interactions compared to raw API discovery.
3. Stable open-source release suitable for public consumption.

## Scope
### In Scope
- MCP Tools for CRUD operations on Engagements.
- MCP Tools for associated entities (Products, Tests, Findings).
- Secure credential management via server configuration/environment variables.

### Out of Scope
- Full parity with every single endpoint in the DefectDojo v2 API (initially focusing on the core risk/engagement workflow).

## Constraints
- **Technical:** Must comply with the Model Context Protocol (MCP) standard.

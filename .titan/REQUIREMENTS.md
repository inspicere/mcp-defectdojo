# Requirements — mcp-defectdojo

## Functional Requirements

### Must-Have (P0)

#### FR-001: Product Management
Agents must be able to list, read, and create products in DefectDojo.
**Acceptance Criteria:**
- Given valid authentication, When the agent requests to list products, Then a summary list of products is returned.
- Given a product name and description, When the agent requests to create a product, Then the product is created in DefectDojo and its ID is returned.

#### FR-002: Engagement Management
Agents must be able to list, read, and create engagements under specific products.
**Acceptance Criteria:**
- Given a product ID, When the agent requests to create an engagement, Then the engagement is created and its ID is returned.

#### FR-003: Test Management
Agents must be able to list, read, and create tests within engagements to group findings.
**Acceptance Criteria:**
- Given an engagement ID and test type, When the agent requests to create a test, Then the test is created and its ID is returned.

#### FR-004: Finding Review and Triage (Update)
Agents must be able to update existing findings (e.g., from automated scanners) to modify reproducibility, status, severity, and other fields.
**Acceptance Criteria:**
- Given a finding ID and updated fields, When the agent requests to update the finding, Then the finding is updated in DefectDojo and the new state is returned.

#### FR-005: Finding Creation
Agents must be able to create new findings from scratch if they uncover vulnerabilities during their operations.
**Acceptance Criteria:**
- Given a test ID and finding details (title, severity, description), When the agent requests to create a finding, Then the finding is created and its ID is returned.

### Should-Have (P1)
#### FR-010: Error Translation
Provide helpful error messages back to the agent if an API call fails, allowing the agent to self-correct (e.g., "Finding ID 123 not found").

### Could-Have (P2)
#### FR-020: Report Uploads
Ability for agents to trigger or upload raw scan reports via the DefectDojo API.

### Won't-Have (P3 — Explicitly Excluded)
- User Management (Agents don't need to manage users or groups).

## Non-Functional Requirements

### NFR-001: API Configuration
The MCP server must be configurable via environment variables (e.g., `DEFECTDOJO_URL`, `DEFECTDOJO_API_KEY`) so credentials are never passed in the prompt.

### NFR-002: Token Efficiency
Responses from the DefectDojo API must be stripped of unnecessary metadata before being returned to the agent to conserve context window tokens.

## Risk Assessment
| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Agent hallucinates IDs | High | Low | FR-010: Return clear 404/400 errors so the agent can retry by listing valid IDs. |
| Overwhelming response sizes | Medium | High | NFR-002: Only return essential fields from API list endpoints. |

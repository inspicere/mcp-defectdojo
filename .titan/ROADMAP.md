# Roadmap — mcp-defectdojo

## Phase Overview
Phase 1: Core Operations  ████░░░░░░  [S]
Phase 2: Finding Mgmt     ░░░░░░░░░░  [M]
Phase 3: Optimization     ░░░░░░░░░░  [S]

## Phase 1: Core Operations — Products, Engagements, and Tests
**Goal:** Agents can navigate the structural hierarchy of DefectDojo.
**Estimated Complexity:** S
**Features:**
- FR-001: Product Management (Create, List, Read)
- FR-002: Engagement Management (Create, List, Read)
- FR-003: Test Management (Create, List, Read)
**Dependencies:** None
**Milestone:** ★ Agents can successfully set up the structure for a new security review or locate an existing one.

## Phase 2: Finding Management — Triage and Creation
**Goal:** Agents can fully interact with findings.
**Estimated Complexity:** M
**Features:**
- FR-004: Finding Review and Triage (Update)
- FR-005: Finding Creation
**Dependencies:** Phase 1 complete (needs structural IDs)
**Milestone:** ★ Agents can review scanner outputs, update reproducibility/status, and create new manual findings.

## Phase 3: Optimization — Errors and Context
**Goal:** Make the tool highly resilient and token-efficient for agents.
**Estimated Complexity:** S
**Features:**
- FR-010: Error Translation
- NFR-002: Token Efficiency (response trimming)
**Dependencies:** Phase 1 and 2
**Milestone:** ★ First public release ready for the community.

## Dependency Map
Phase 1 ──→ Phase 2 ──→ Phase 3

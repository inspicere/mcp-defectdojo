# Project Intelligence — AGENTS.md

> This file is loaded automatically by OpenCode at the start of every session.
> It contains critical project context, conventions, and rules.
> Content mirrors CLAUDE.md — kept in sync for cross-tool compatibility.

## Project
- **Name:** mcp-defectdojo
- **Domain:** mcp server
- **Type:** greenfield
- **Framework:** TITAN

## TITAN State
- Read `.titan/STATE.md` for current project position
- Read `.titan/DECISIONS.md` before making architectural choices
- Read `.titan/KNOWLEDGE.md` for accumulated learnings

## Conventions
- **Commits:** `titan(phase-NN): description` — atomic, one per task
- **Branches:** `titan/phase-NN-name` — one per phase
- **Verification:** Mandatory after every build phase

## Commands
Run `/titan:help` for the complete command reference.
To continue from where you left off: `/titan:resume`

## Rules
- Never skip verification (/titan:08-verify)
- Always read PLAN.md before building
- Always update STATE.md after completing work
- Respect file boundaries defined in plans
- Document non-trivial decisions in DECISIONS.md

# TITAN Decision Log

> Every non-trivial decision with rationale. Future sessions consult this first.

| # | Date | Decision | Rationale | Revisitable? |
|---|------|----------|-----------|-------------|
| 1 | 2026-05-04 | Domain: mcp server | User selection during initialization | Yes — /titan:settings |
| 2 | 2026-05-04 | Profile: balanced | User selection during initialization | Yes — /titan:settings |

| 3 | 2026-05-04 | Tech Stack: Python/FastMCP/httpx | Defaulted to Python as it is standard for security tools. | Yes |
| 4 | 2026-05-04 | Package Management: uv | Chosen to enforce strict lockfiles and hash-checking for supply chain security. | Yes |
| 5 | 2026-05-04 | Deployment: Container/Ansible | Consistent with Laima infra patterns (Dockerfile + Ansible playbook). | Yes |
| 6 | 2026-05-06 | Audit report accuracy | Previous auto-generated audit claimed fixes applied; re-audited against actual source code. Authoritative report: `.titan/phases/01-deployment-configuration/AUDIT.md` | No |
| 7 | 2026-05-07 | Phase 03 split into 3.1 (Validation & Pagination) + 3.2 (Logging & Robustness) | Scope exceeded 3-task budget: 3 FRs + 13 deferred findings across multiple functions in 3 files. Split by feature cohesion — 3.1 covers user-facing quality (FR-012, FR-013), 3.2 covers operational quality (FR-014, tests, robustness). | No |

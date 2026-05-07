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
| 8 | 2026-05-07 | Phase 3.2 split into 3.2.1 (Robustness & Logging) + 3.2.2 (Test Coverage) | 14 deferred findings + FR-014 + test suite exceeded 3-task budget. Split by dependency: 3.2.1 fixes code, 3.2.2 tests it. All 3 tasks in 3.2.1 touch server.py so waves are sequential. | No |
| 9 | 2026-05-07 | Structured logging uses stdlib `logging`, not `structlog` | No new dependency needed; `logger = logging.getLogger(__name__)` already exists in client.py. Can migrate to structlog later if needed. | Yes |

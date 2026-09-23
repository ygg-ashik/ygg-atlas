# ygg-atlas

Enterprise data-intelligence platform for YouGotAGift: a governed semantic layer ("the atlas")
over all commerce apps, ads, analytics, campaigns, and revenue — exposed through an AI chat
interface and MCP. See `docs/specs/2026-09-23-ygg-atlas-mvp-design.md` for the full design.

## Architecture

Monorepo:
- `backend/` — FastAPI (Python 3.12, uv). Chat API + agent loop + atlas semantic registry + connectors + MCP server.
- `frontend/` — React 19 + Vite + TypeScript + Tailwind + shadcn/ui. Chat UI with SSE streaming.
- `evals/` — golden Q&A suite; must pass before merge.
- `docs/specs/` — design docs; `docs/plans/` — implementation plans.

Deployment: AWS EC2 (`ssh atlas`), docker compose, reverse proxy + HTTPS. NOT GCP Cloud Run.

## Non-negotiable guardrails

1. **No raw text-to-SQL.** The agent answers only through atlas tools backed by vetted metric/entity
   definitions in `backend/app/atlas/definitions/`. If the registry can't answer, the agent asks a
   clarifying question — it never generates freeform SQL or invents numbers.
2. **Provenance on every number.** Every metric answer carries metric id, source, and data freshness,
   threaded through the SSE `done` event and rendered as provenance chips in the UI.
3. **Connectors are read-only.** Source-DB connections use read-only credentials and per-source table
   allowlists (`backend/app/connectors/`). Never point a connector at a production primary for heavy queries.
4. **Scope from token, never from prompt.** Auth/permissions come from the Firebase token (domain-locked
   to `@yougotagift.com`). Nothing user-typed can widen data access.
5. **Audit everything.** Every atlas tool execution is written to the audit log (`backend/app/models/audit.py`).
6. **Evals gate merges.** New agent/prompt/registry behavior needs golden coverage in `evals/goldens/`.

## Component standard (applies to ALL code)

Every module is self-contained and enterprise-grade:
- One clear purpose per module; public interface at its root (`__init__.py` / `index.ts`).
- Never reach into another feature's internals; no cross-feature imports.
- Dependency direction only downward: `features → api/lib → ui` (frontend),
  `api → agent/atlas → connectors` (backend). Enforced by ESLint `no-restricted-imports` on the frontend.
- Each unit testable in isolation.
- No legacy silos — refactor in place, keep the tree clean.

## Datetime/Timezone rules

All datetimes are UTC end-to-end. Every SQLModel `datetime` field MUST declare
`sa_type=TIMESTAMP(timezone=True)`:

```python
from sqlalchemy import TIMESTAMP
created_at: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    sa_type=TIMESTAMP(timezone=True),
)
```

Violating this causes asyncpg insert errors.

## Development

Backend:
```bash
cd backend && uv sync
uv run uvicorn app.main:app --reload --port 8081
uv run pytest --cov=app            # >80% coverage on new code
uv run ruff check . && uv run ruff format --check .
```

Frontend:
```bash
cd frontend && pnpm install
pnpm dev                            # Vite dev server (proxy to :8081)
pnpm test                           # vitest
pnpm lint && pnpm typecheck
```

Full stack: `docker compose up` (Postgres 16 + backend + frontend).
Evals: `cd backend && uv run python ../evals/run_evals.py`

## Quality gates (before marking any task complete)

- All tests pass; coverage >80% for new code
- No lint or type errors
- Follows the component standard above
- No security issues (secrets, PII leaks, scope bypass)
- Docs updated if behavior changed

## Workflow

- Branching: `feature/<name>` → `staging` → `production`.
- Commits: `<type>(<scope>): <description>` (feat, fix, docs, refactor, test, chore).
- TDD: write the failing test first (Red → Green → Refactor).
- Design docs in `docs/specs/`, implementation plans in `docs/plans/`.

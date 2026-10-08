# ygg-atlas

Enterprise data-intelligence platform for YouGotAGift: a governed semantic layer ("the atlas")
over all commerce apps, ads, analytics, campaigns, and revenue — exposed through an AI chat
interface and MCP. See `docs/specs/2026-09-23-ygg-atlas-mvp-design.md` for the full design.

## Architecture

Monorepo:
- `backend/` — FastAPI (Python 3.12, uv). Chat API + agent loop + atlas semantic registry + data-source plugins + MCP server.
  - `app/sources/<id>/` — one self-contained plugin per data source (`manifest.py` with its own
    Settings, connector, `definitions/*.yaml`). A plugin is enabled iff its env vars are set.
  - `app/agent/providers/` — LLM provider loops (OpenAI or Anthropic, chosen by which key is in `.env`).
- `frontend/` — React 19 + Vite + TypeScript + Tailwind + shadcn/ui. Chat UI with SSE streaming.
- `evals/` — golden Q&A suite; must pass before merge.
- `docs/specs/` — design docs; `docs/plans/` — implementation plans.

Deployment: AWS EC2 (`ssh atlas`), docker compose, reverse proxy + HTTPS. NOT GCP Cloud Run.

## Non-negotiable guardrails

1. **No raw text-to-SQL.** The agent answers only through atlas tools backed by vetted metric/entity
   definitions in each plugin's `backend/app/sources/<id>/definitions/`. If the registry can't answer, the agent asks a
   clarifying question — it never generates freeform SQL or invents numbers.
2. **Provenance on every number.** Every metric answer carries metric id, source, and data freshness,
   threaded through the SSE `done` event and rendered as provenance chips in the UI.
3. **Connectors are read-only.** Source-DB connections use read-only credentials and per-plugin table
   allowlists (`allowed_tables` in each `manifest.py`, linted at load by `backend/app/atlas/registry.py`;
   SELECT-only enforced by `SQLSourceConnector` in `backend/app/sources/base.py`). Never point a connector
   at a production primary for heavy queries. Source DBs are IP-restricted: connect only from the atlas
   EC2 box (`ssh atlas`), never from a laptop.
4. **Scope from token, never from prompt.** Auth/permissions come from the Firebase token (domain-locked
   to `@yougotagift.com`). Nothing user-typed can widen data access.
5. **Audit everything.** Every atlas tool execution is written to the audit log (`backend/app/models/audit.py`).
6. **Evals gate merges.** New agent/prompt/registry behavior needs golden coverage in `evals/goldens/`.

## Component standard (applies to ALL code)

Every module is self-contained and enterprise-grade:
- One clear purpose per module; public interface at its root (`__init__.py` / `index.ts`).
- Never reach into another feature's internals; no cross-feature imports.
- Dependency direction only downward: `features → api/lib → ui` (frontend),
  `api → agent → atlas → sources` (backend). Enforced by ESLint `no-restricted-imports` on the frontend.
- Each unit testable in isolation.
- No legacy silos — refactor in place, keep the tree clean.

## Design standard (applies to ALL UI work)

**`DESIGN.md` (repo root) is the single source of truth for every screen, component, and visual change.**
The standard is "Atlas Hybrid Glass": Apple glass foundation + Claude voice + Codex agent transparency +
Higgsfield presets + Atlas provenance UI.

- **Read `DESIGN.md` before any frontend/UI task.** Live reference: `docs/design/reference/atlas-hybrid-glass.html` (Mode ①).
- **Tokens only.** Colors, type, radii, spacing, motion come from DESIGN.md via the CSS variables in
  `frontend/src/index.css`. No hard-coded hex, ad-hoc durations, or one-off font sizes in components.
- **New component or token → add it to DESIGN.md first**, in the same PR, then build it.
- **Technique** (springs, interruptible motion, glass materials, reduced-motion) follows the vendored
  `apple-design` skill (`.claude/skills/apple-design/`). If it conflicts with DESIGN.md, **DESIGN.md wins.**
- **Non-negotiables:** glass only on floating chrome, never under data; provenance chip on every number;
  every agent write/schedule/send goes through a review card; respect `prefers-reduced-motion` and
  `prefers-reduced-transparency`.
- **Approved UI libraries:** `motion`, `streamdown`, `@number-flow/react`, `sonner`, `cmdk`, Radix primitives,
  self-hosted `@fontsource-variable/*` fonts. Adding another UI/animation library needs explicit approval.
- After editing DESIGN.md: `npx @google/design.md lint DESIGN.md` (0 errors required).

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
uv run alembic upgrade head        # apply migrations (also run by the Docker image at start)
uv run alembic revision -m "..."   # new migration in migrations/versions/
TEST_PG_URL=postgresql+asyncpg://… uv run pytest tests/test_alembic_postgres.py   # migrations on a disposable Postgres
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

Quality gate (repo root): `make check` runs every CI gate except the dependency and secret scans
(`make audit` runs the dependency scan). `make format` auto-fixes, `make hooks` installs the
pre-commit hooks.

## Quality gates (before marking any task complete)

- `make check` is green (format, lint, types, architecture contracts, tests, build)
- All tests pass; coverage >80% for new code
- No lint or type errors
- Follows the component standard above
- UI changes follow `DESIGN.md`, checked in light, dark, reduced-motion and reduced-transparency
- No security issues (secrets, PII leaks, scope bypass)
- Docs updated if behavior changed

## Workflow

- Branching: `feature/<name>` → `staging` → `production`.
- Commits: `<type>(<scope>): <description>` (feat, fix, docs, refactor, test, chore).
- TDD: write the failing test first (Red → Green → Refactor).
- Design docs in `docs/specs/`, implementation plans in `docs/plans/`.

## Engineering standards (applies to ALL code)

This repository is production code. The full rulebook is **`ARCHITECTURE.md`** (layers, module
anatomy, where code goes, limits, enforcement). Machines enforce it; CI is the final authority.

**Mandatory skills:**
- Invoke **`engineering-standards`** before writing or modifying any code, tests, migrations or
  plugin YAML.
- Invoke **`production-code-review`** before declaring a coding task complete, before committing,
  and before opening a PR.

**The contract:**
- Inspect the existing architecture and reuse existing abstractions before creating new ones. No
  new top-level structure without justification and matching import-linter contracts.
- Backend: thin routers (parse, call a service, return a schema). Business logic in services, all
  database access in repositories, Pydantic schemas separate from SQLModel tables. Layers
  `main > api|mcp > agent > atlas > sources`, never upward.
- Frontend: thin pages, data through hooks, features never import features, shared components
  only in `ui/` when generic and used by two or more features.
- No `utils.py` / `utils.ts` grab-bags. Something moves to `core/` only with a stable, generic
  responsibility and several real consumers.
- Python: Ruff at 88 columns, annotations on every function, no `Any` shortcuts, timezone-aware
  UTC datetimes. TypeScript: `strict` plus `noUncheckedIndexedAccess`, no `any`.
- No abstractions for hypothetical needs, no unrelated changes, no weakened or skipped tests.
- Never relax a rule in `pyproject.toml`, `eslint.config.js` or `tsconfig.json` to make code
  pass. A justified exception is one line with the exact code and a reason.

**Validation before calling work done:** `make check` green, then the `production-code-review`
verdict. If a check fails, fix the underlying problem; never bypass the check.

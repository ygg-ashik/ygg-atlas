# ygg-atlas

**The neural map of YouGotAGift.** A governed semantic layer over all commerce apps, ads,
analytics, campaigns, and revenue — exposed through an AI chat interface and MCP, so anyone
(and any agent) can get trusted, provenance-backed answers about the business.

> Design doc: [`docs/specs/2026-09-23-ygg-atlas-mvp-design.md`](docs/specs/2026-09-23-ygg-atlas-mvp-design.md)

## What it does (MVP)

- **Chat over existing data** — app databases (read-only) + GA4, answered through a governed
  semantic registry (never raw text-to-SQL). Streaming SSE chat with provenance chips on every number.
- **Atlas semantic registry** — entities, metrics, and funnels defined as vetted YAML + SQL/GA4
  queries in `backend/app/atlas/definitions/`.
- **MCP endpoint** — the same atlas tools exposed over Model Context Protocol for external agents
  (Claude Desktop, other MCP clients).
- **Evals** — golden Q&A suite in `evals/` gates behavior changes.

## Repo layout

```
backend/    FastAPI: chat API, agent loop, atlas registry, connectors, MCP server
frontend/   React 19 + Vite chat app (Firebase auth, @yougotagift.com only)
evals/      golden questions + replay harness
docs/       specs and plans
```

## Quick start (local)

Prereqs: Docker, Node 22 + pnpm, Python 3.12 + uv.

```bash
cp backend/.env.example backend/.env      # fill ANTHROPIC_API_KEY etc.
cp frontend/.env.example frontend/.env.local
docker compose up -d postgres
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8081
# new terminal
cd frontend && pnpm install && pnpm dev
```

Or the whole stack: `docker compose up`.

## Tests

```bash
cd backend && uv run pytest --cov=app
cd frontend && pnpm test
cd backend && uv run python ../evals/run_evals.py   # golden suite (needs seeded demo data)
```

## Deployment (AWS EC2)

The app runs on an existing EC2 machine, reachable via `ssh atlas`.

```bash
ssh atlas
cd /opt/ygg-atlas && git pull
docker compose up -d --build
```

Runbook details (env files, reverse proxy, HTTPS) live in `docs/plans/` once provisioned.

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
cp backend/.env.example backend/.env      # fill ANTHROPIC_API_KEY etc.; set ENVIRONMENT=development
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
cd backend && uv run pytest -n auto --cov=app   # parallel; drop -n auto to debug serially
cd frontend && pnpm test
cd backend && uv run python ../evals/run_evals.py   # golden suite (needs seeded demo data)
```

Evals run each golden under a synthetic per-golden policy (its `allow` patterns, default `*`), not
the database grants. They are an operator-only tool, never an access path for users.

## Deployment (AWS EC2)

The app runs on an existing EC2 machine, reachable via `ssh atlas` (Amazon Linux 2023,
docker + compose; buildx installed at `~/.docker/cli-plugins/`). The repo lives at
`~/ygg-atlas` and is synced from a dev machine (git is not installed on the box):

```bash
# from your machine, repo root
rsync -az --delete --exclude '.git' --exclude 'node_modules' --exclude '.venv' \
  --exclude 'dist' --exclude '__pycache__' --exclude '.env' --exclude '.env.local' \
  ./ atlas:~/ygg-atlas/

ssh atlas
cd ~/ygg-atlas
docker compose up -d --build
docker compose exec backend uv run --no-dev python scripts/seed_demo.py   # demo data
curl http://127.0.0.1:8081/healthz
```

Migrations run automatically when the backend container starts (`alembic upgrade head`). The
baseline is idempotent, so a database created by the old `create_all` upgrades in place; it is also
irreversible (`alembic downgrade base` refuses), so back up before risky migrations.

### Sign-in (Firebase Auth, Google only)

- **Provider and authorized domains** are config as code in `firebase.json` (project in
  `.firebaserc`). Apply with `firebase deploy --only auth` while signed in to the Firebase CLI as a
  `@yougotagift.com` account. atlas uses Firebase **Auth only**; users, permissions and chat live in
  Postgres.
- **Web config** (public): repo-root `.env` on the box, from `.env.example`. docker compose passes it
  to the frontend build as args. Rebuild the frontend after changing it.
- **Backend**: `FIREBASE_PROJECT_ID=ygg-atlas` in `backend/.env`. Tokens are verified against
  Google's public keys, so no service account is needed.
- **Access**: the box is private (`http://10.4.216.35:8080` over VPN). Without an authorized
  hostname, use a tunnel: `ssh -L 8080:localhost:8080 atlas`, then open `http://localhost:8080`.

`ENVIRONMENT` fails closed: unset means `production`, which refuses `AUTH_DISABLED=true` and requires
`FIREBASE_PROJECT_ID`. While the box still runs with `AUTH_DISABLED=true`, `backend/.env` must set
`ENVIRONMENT=development` or the backend will not start. `BOOTSTRAP_ADMINS` (comma-separated emails)
creates the first admins (only emails with no user yet; an existing user's role is never changed,
so promote one with the CLI's `set-role`); the dev user is a plain viewer.

Server-only files on the box (not in git):
- `backend/.env` — secrets: `ANTHROPIC_API_KEY`, `FIREBASE_PROJECT_ID`, `ATLAS_MCP_TOKEN`.
  Currently `AUTH_DISABLED=true` for smoke testing; set `false` once Firebase is configured.
- `docker-compose.override.yml` — binds all ports to `127.0.0.1` so nothing is publicly
  exposed while auth is disabled. Remove the binds and add a reverse proxy (nginx/caddy
  with HTTPS) when going live.

MCP endpoint (for Claude Desktop / other agents): `http://127.0.0.1:8081/mcp-server/mcp`
(streamable HTTP; set `ATLAS_MCP_TOKEN` and send it as a bearer token).

### Access control (phase 2)

Signing in gives a **viewer** role with **no data**. Admins grant data with groups and grants;
deny always wins, and admins see data only through grants too. Until the admin UI (phase 5), use
the CLI on the box:

    docker compose exec backend uv run --no-dev python -m app.access.cli groups
    docker compose exec backend uv run --no-dev python -m app.access.cli add-member someone@yougotagift.com marketing
    docker compose exec backend uv run --no-dev python -m app.access.cli grant group:marketing allow 'demo/*' --reason "launch"
    docker compose exec backend uv run --no-dev python -m app.access.cli access someone@yougotagift.com

Every change is in `rbac_changes`. The same operations exist as `/api/v1/admin/...` for admins.
MCP is off unless `ATLAS_MCP_TOKEN` is set; it runs as `MCP_SERVICE_EMAIL` under that user's grants.
Locally, `make dev-access` (after signing in once) grants the dev user all data.

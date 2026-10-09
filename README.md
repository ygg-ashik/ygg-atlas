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
  (Claude Code and scripts today; claude.ai, Claude Desktop and mobile after 4b), each caller
  authenticated with its own atlas-issued token.
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
- `backend/.env` — secrets and settings: `ANTHROPIC_API_KEY`, `FIREBASE_PROJECT_ID`,
  `ATLAS_PUBLIC_URL` (see [MCP](#mcp-claude-code-scripts-and-service-accounts)).
  Currently `AUTH_DISABLED=true` for smoke testing; set `false` once Firebase is configured.
- `docker-compose.override.yml` — binds all ports to `127.0.0.1` so nothing is publicly
  exposed while auth is disabled. Remove the binds and add a reverse proxy (nginx/caddy
  with HTTPS) when going live.

MCP endpoint: `http://localhost:8080/mcp-server/mcp` through the tunnel (streamable HTTP, through
nginx). Every caller authenticates with its own token; see below.

### Access control (phase 2)

Signing in gives a **viewer** role with **no data**. Admins grant data with groups and grants;
deny always wins, and admins see data only through grants too. Until the admin UI (phase 5), use
the CLI on the box:

    docker compose exec backend uv run --no-dev python -m app.access.cli groups
    docker compose exec backend uv run --no-dev python -m app.access.cli add-member someone@yougotagift.com marketing
    docker compose exec backend uv run --no-dev python -m app.access.cli grant group:marketing allow 'demo/*' --reason "launch"
    docker compose exec backend uv run --no-dev python -m app.access.cli access someone@yougotagift.com

Every change is in `rbac_changes`. The same operations exist as `/api/v1/admin/...` for admins.
Locally, `make dev-access` (after signing in once) grants the dev user all data.

### MCP: Claude Code, scripts and service accounts

Every MCP caller uses an atlas-issued token, stored only as a hash: an **OAuth** login (Claude Code),
a **personal access token (PAT)** for scripts and CI, or a **service token** for a service account.
A call runs as that user under their own groups and grants, and is audited with the token and
client id. Connecting needs the `mcp:use` capability (the `analyst` role and above); a user without
it gets an empty `tools/list` and a tool-level denial on `tools/call` (never an HTTP 403). The MCP
endpoint never honours `AUTH_DISABLED`: every MCP request needs a valid bearer, even in development.

**Claude Code (OAuth, recommended).** The box is private, so connect through the SSH tunnel:

```bash
ssh -L 8080:localhost:8080 atlas          # keep this open
claude mcp add --transport http atlas http://localhost:8080/mcp-server/mcp
```

Then run `/mcp` in Claude Code, pick **atlas**, choose **Authenticate**, sign in with your
`@yougotagift.com` Google account in the browser and approve. `claude mcp login atlas`
re-authenticates later (for example after a revocation). OAuth works only through the tunnel
(`localhost`), not over the VPN IP: MCP clients send OAuth credentials only over https or to
localhost.

**Scripts and CI (PAT).** Until the self-service UI (phase 5), an admin mints the token on the box.
It is printed once and never stored in clear:

```bash
docker compose exec backend uv run --no-dev python -m app.mcp.cli create-pat someone@yougotagift.com --name ci [--days 90]
# then, on the machine that uses it (through the tunnel):
claude mcp add --transport http atlas http://localhost:8080/mcp-server/mcp \
  --header "Authorization: Bearer ${ATLAS_PAT}"
```

PATs last `PAT_DEFAULT_DAYS` (90) by default, at most `PAT_MAX_DAYS` (365); each user can hold at
most 10 live PATs. They open the MCP door only, never the REST API. Your shell expands
`${ATLAS_PAT}` when you run `claude mcp add`, so the token itself is stored in clear in
`~/.claude.json`: treat that file as a secret, and revoke the PAT if it leaks.

**Service accounts** (an unattended job that should not act as a person). The account gets a role
like any user (and groups and grants through the access CLI); its email is
`svc-<slug>@atlas.internal`:

```bash
docker compose exec backend uv run --no-dev python -m app.mcp.cli create-service-account "Nightly ETL" --role analyst
docker compose exec backend uv run --no-dev python -m app.mcp.cli create-service-token svc-nightly-etl@atlas.internal --name etl
```

**Revoking.** `list-tokens [--email E] [--kind pat|service|oauth]`, `revoke-token <id>`,
`revoke-all <email>`, `list-clients` and `revoke-client <client-id>` in the same CLI; the same
operations exist under `/api/v1/me/tokens`, `/api/v1/me/connected-apps` and `/api/v1/admin/...`.
Disabling a user revokes all of their tokens. Token and client changes are recorded in
`credential_events`. `gc` deletes expired codes, requests, tokens and idle clients.

**Migrating from the shared token.** `ATLAS_MCP_TOKEN` and `MCP_SERVICE_EMAIL` are gone (leftover
values in `backend/.env` are ignored; delete them), and migration 0005 disables
`mcp-shared@atlas.internal`. Before deploying: mint a PAT (or a service account and token) for
every script that used the shared token, then announce the switch. After the deploy, people re-add
the server with the OAuth command above and scripts switch to `--header "Authorization: Bearer …"`.

**Rate limits** (in process; the backend must run a single uvicorn worker; a refusal is 429 with
`Retry-After`): 120 MCP calls per minute per token; 10 consent requests per minute per user
(viewing and deciding count together); and per source, 30/min on `/token`, 30/min on
`/authorize`, 10/h on client registration (`/register`) and 20 failed bearer attempts per minute.
Only bearers atlas does not recognise count as failed (unknown, revoked or malformed); a real token
that merely expired never does. Until 4b the backend has no trusted client address: a loopback,
private (RFC 1918, IPv6 ULA) or link-local peer — nginx, the SSH tunnel, the compose network — is
an "unknown" source. So `/token`, `/authorize` and `/register` each have one global budget shared
by everybody, and the failed-bearer guard only logs (`ratelimit.bearer_failure_unattributed`) and
never blocks. If a team onboarding at once hits the registration limit, wait an hour or restart the
backend.

**Hosted connectors (claude.ai, Claude Desktop, mobile) wait for 4b.** They need a public https
URL. 4b is configuration plus one code precondition (step 6). Checklist:

1. **DNS and TLS.** A public host and an outer TLS proxy on the box (nginx + certbot, or Caddy) in
   front of the frontend container (`:8080`); open 443 to Anthropic's range `160.79.104.0/21` and
   the office only.
2. **Outer proxy rules.** It must:
   - preserve `Host` (send the public host, not `localhost:8080`): the MCP transport's
     DNS-rebinding check accepts only `ATLAS_PUBLIC_URL`'s host and loopback, and answers 421
     otherwise;
   - turn buffering off for `/mcp-server/` (nginx `proxy_buffering off` and a long
     `proxy_read_timeout`; Caddy `flush_interval -1`) so streamed MCP responses flush;
   - not intercept `/.well-known/`: pass every `/.well-known/oauth-*` request through unchanged.
     The container nginx answers only `location ^~ /.well-known/oauth-` (every backend discovery
     path starts with it), so the outer proxy may keep `/.well-known/acme-challenge/` for
     certbot;
   - set `X-Forwarded-For` to the client address.

   The container nginx overwrites `X-Forwarded-Proto` with its own scheme (`http`). That is
   harmless: the backend builds every advertised URL from `ATLAS_PUBLIC_URL`, never from the request
   scheme. Do not rely on that header.
3. **Settings.** `ATLAS_PUBLIC_URL=https://<host>` in `backend/.env`; `CORS_ORIGINS` gains
   `https://<host>`.
4. **Firebase.** Add `https://<host>` to `auth.providers.googleSignIn.authorizedRedirectUris` in
   `firebase.json` (next to `http://localhost` and the VPN address), then `firebase deploy --only
   auth`; check that `<host>` is listed under Authentication → Settings → Authorized domains in the
   Firebase console.
5. **Trusted proxy headers.** Run uvicorn (`backend/Dockerfile` CMD) with `--proxy-headers
   --forwarded-allow-ips=<compose subnet CIDR>`. The backend sees the container nginx's address, and
   the outer proxy reaches that nginx through the compose gateway, so both hops are in the compose
   network's subnet: pin the subnet in `docker-compose.yml` (or read it with `docker network
   inspect`) and trust that CIDR, not a single address. Only then do per-source limits key on the
   real client and the failed-bearer guard block. Unpublish the backend's own port `8081` (or keep
   it bound to `127.0.0.1`, so only someone already on the box reaches it): a request that reaches
   the backend around nginx arrives from the trusted compose gateway and could forge
   `X-Forwarded-For`.
6. **Bind consent to the initiating browser** (HttpOnly cookie set on `/authorize`) — a code change
   that must land before hosted callbacks are opened (ARCHITECTURE.md §6).
7. **Verify.** Rebuild and restart, then run `backend/scripts/mcp_oauth_smoke.py` (phase 4, Task 12)
   with `--base-url https://<public host>` (PATs and the consent bearer from the environment:
   `ATLAS_PAT`, `ATLAS_REVOKED_PAT`, `ATLAS_FIREBASE_TOKEN`). Existing OAuth logins
   re-authenticate once (their audience changes); PATs and service tokens keep working.

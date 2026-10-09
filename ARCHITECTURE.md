# ygg-atlas architecture and engineering rules

This is the rulebook for where code goes and how it is written. Every rule names what enforces
it. Machines enforce what can be checked mechanically (`make check`, pre-commit, CI); the
`engineering-standards` and `production-code-review` skills cover the rest. If this file and the
code disagree, fix one of them in the same change.

## 1. Principles

1. **Self-contained modules.** One clear purpose per module, a public interface at its root
   (`__init__.py` / `index.ts`), and no reaching into another module's internals.
2. **Dependencies point one way.** Higher layers may import lower ones, never the reverse.
3. **Thin edges, thick core.** Routes, MCP handlers and React pages translate input and output.
   Business logic lives in services and the atlas kernel.
4. **Fail closed.** Missing configuration, unknown input or a denied check means "no", never a
   silent default that widens access.
5. **Govern the data.** Business data is reached only through atlas tools backed by vetted
   definitions (see `CLAUDE.md` guardrails).
6. **Smallest correct change.** Reuse existing abstractions before adding new ones. No
   abstractions for hypothetical futures.

## 2. Backend (`backend/app`)

### 2.1 Layers

```
app.main                           app wiring only
app.api | app.mcp | app.insights   edges (thin) + read-only insights
app.agent                          LLM loop, prompts, guardrails, providers
app.atlas                          governed semantic layer: tools, registry, provenance
app.sources                        source plugins (leaves)
─────────────────────────────────────────────────────────────────────
identity: app.identity (who is calling)     access: app.access (what they may do and see)
          both depend only on platform; access may use identity; agent/atlas use neither
platform: app.models · app.database · app.config   (+ app.core, new)
```

| Rule | Enforced by (import-linter contract) |
|---|---|
| main > api, mcp, insights > agent > atlas > sources, never upward | "Backend layers" |
| `api`, `mcp` and `insights` are siblings and never import each other | "Backend layers" (`\|` layer) |
| Source plugins import nothing above them, plus no atlas DB, no HTTP | "Source plugins are leaves" |
| Plugins never import each other | "Source plugins are independent" |
| Platform modules never import features | "Platform modules never depend on features" |
| Identity imports only platform modules | "Identity depends only on platform modules" |
| Access imports only identity and platform modules | "Access depends only on identity and platform modules" |
| Agent and atlas take a policy object, never identity or access | "Agent and atlas never import identity or access" |
| Identity and access follow the §2.2 anatomy | "Identity module layering", "Access module layering" |
| MCP follows its own layering: `server \| cli` > `router` > `oauth_routes \| dependencies` > `oauth_provider` > `auth \| ratelimit \| schemas \| access_log` | "MCP module layering" |

New top-level packages must be added to the contracts in `backend/pyproject.toml` in the same
change. The plugin independence contract lists plugins by name: **a new source plugin must be
added to it** in the change that creates the plugin.

### 2.2 Module anatomy (every new feature module)

A feature module (for example `app/identity`, `app/access`, `app/chat`) is a vertical slice:

```
app/<module>/
    __init__.py      public interface: what other modules may import
    router.py        thin: parse input → call service → return schema. No DB, no business logic
    service.py       business logic and use cases. No FastAPI, no SQL
    repository.py    all database access for this module. No business decisions
    models.py        SQLModel tables (persistence shape)
    schemas.py       Pydantic request/response models (API shape), separate from models
    <topic>.py       named helpers specific to this module (never utils.py)
```

Dependency direction inside a module: `router → service → repository → models`. A router never
imports a repository or `sqlmodel`/`sqlalchemy`. When the first module with this anatomy lands,
a `layers` contract with `containers` is added so import-linter enforces it.

```python
# router.py: the whole job of a route
@router.post("/groups", response_model=GroupOut)
async def create_group(
    payload: GroupCreate,
    service: GroupService = Depends(get_group_service),
    principal: Principal = Depends(get_principal),
) -> GroupOut:
    return await service.create_group(principal, payload)
```

### 2.3 Where code goes

| Situation | Place |
|---|---|
| Helper used by one module | Inside that module, in a file named for what it does |
| Helper used by several files in one module | `app/<module>/<topic>.py` |
| Genuinely cross-cutting with a stable, generic responsibility and several real consumers | `app/core/<topic>.py` (`security.py`, `pagination.py`, `datetime.py`, `exceptions.py`) |
| Data-source access | A source plugin (`app/sources/<id>/`) |
| A new business metric | YAML in the owning plugin's `definitions/`, never Python |
| Never | `utils.py`, `helpers.py`, `common.py` grab-bags; moving code to `core` just because two places use it |

### 2.4 Python rules (Ruff, Pyright)

- Formatting: Ruff, **88 columns**. Imports sorted, absolute only (no relative imports).
- Every function has parameter and return annotations. `Any` only for genuinely untyped JSON
  (`dict[str, Any]`), never as a shortcut.
- Size limits: cyclomatic complexity ≤ 10, ≤ 6 arguments, ≤ 12 branches, ≤ 6 returns,
  ≤ 50 statements per function.
- No `print` in app code (use `structlog`), no commented-out code, no mutable global state
  (`global`); use `functools.cache` factories or explicit holders.
- Datetimes are timezone-aware UTC only (Ruff `DTZ`, plus the `CLAUDE.md` UTC rule).
- Security lint (bandit `S`) applies to all app code. SQL is never built from user input; values
  are always bind parameters.
- Pyright runs in `standard` mode on `app`, `tests` and `scripts`. New self-contained modules are
  added to `[tool.pyright].strict`.

## 3. Frontend (`frontend/src`)

### 3.1 Layers

```
App.tsx / main.tsx       routing and composition only
features/<name>/         self-contained product features
api/                     HTTP and SSE client, TanStack Query hooks (shared)
lib/                     app-wide non-visual infrastructure (theme, firebase, formatting)
ui/                      presentational primitives (no data, no product knowledge)
```

| Rule | Enforced by |
|---|---|
| features → api, lib → ui only | ESLint `no-restricted-imports` per layer |
| Features never import other features; compose them in `App.tsx` | ESLint |
| `api` and `lib` never import features; `ui` imports nothing above it | ESLint |
| No climbing out of a module with `../../`; use the `@/` alias | ESLint |
| Visual decisions follow `DESIGN.md` tokens | `CLAUDE.md` design standard |

### 3.2 Feature anatomy

Small features may be flat files. Once a feature passes about 8 files, it splits into:

```
features/<name>/
    index.ts          public interface (what App.tsx imports)
    components/       feature-local components, one responsibility each
    hooks/            state and data hooks (use<Thing>.ts)
    api/              feature-specific API calls, if not shared
    types/            feature types
    <topic>.ts        named pure helpers (never utils.ts)
```

- Pages and routes stay thin: compose feature components, no fetching or business logic inline.
- Presentational components never call the API directly; data arrives through hooks.
- A component lives in `ui/` only if it is generic and used by two or more features. A feature's
  own table or card stays in the feature even when it is a "component".
- Never duplicate an existing `ui/` primitive.

### 3.3 TypeScript and React rules (TypeScript, ESLint, Prettier)

- TypeScript `strict` plus `noUncheckedIndexedAccess`, `noImplicitReturns`, `noImplicitOverride`,
  `noUnusedLocals`, `noUnusedParameters`.
- No `any`. Type-only imports use `type`.
- Limits: ≤ 300 lines per file, ≤ 150 lines per function, complexity ≤ 12, nesting depth ≤ 4,
  ≤ 4 parameters (use an options object), no nested ternaries.
- Prettier: 100 columns, single quotes, trailing commas.
- No `console.log` (`console.warn` and `console.error` are allowed).

## 4. Tests

- Test-driven: write the failing test first.
- Backend: pytest, run in parallel with pytest-xdist (`-n auto`); coverage of `app` ≥ 80%
  (`fail_under`). Frontend: Vitest + Testing Library.
- Test behavior through public interfaces, not private helpers.
- Never weaken, skip or delete a test to make a change pass. A test that encodes wrong behavior is
  fixed in the same change, with the reason in the commit message.
- New agent, prompt or registry behavior needs golden coverage in `evals/goldens/`.

## 5. Enforcement

| Layer | What runs | When |
|---|---|---|
| Claude | `engineering-standards` skill before writing code; `production-code-review` skill before calling work done | every coding task |
| Pre-commit | Ruff (fix and format), Prettier, ESLint on changed files; import contracts; secret scan; whitespace and large-file checks | `git commit` |
| `make check` | Backend: `ruff format --check`, `ruff check`, `pyright`, `lint-imports`, `pytest -n auto --cov`. Frontend: Prettier check, ESLint, `tsc`, Vitest, build | before every PR |
| `make audit` | Dependency scan: `pip-audit` on lockfile pins resolved for this platform (`scripts/locked_requirements.py`, because pip-audit evaluates markers against its own interpreter, not the project venv), and `pnpm audit --prod` | before dependency changes |
| CI | Everything in `make check`, plus `make audit` and a gitleaks secret scan | every push and PR; a red build cannot merge |

**Suppressions.** A rule is never weakened in config to make code pass. A justified exception is
one line, naming the exact code and a reason:

```python
def _ga4_client() -> object:
    from google.analytics.data_v1beta import (  # noqa: PLC0415  # optional "ga4" extra
        BetaAnalyticsDataClient,
    )

    return BetaAnalyticsDataClient()
```

```ts
// eslint-disable-next-line react-hooks/exhaustive-deps -- starters must stay stable per session
```

## 6. Known debt (ratchet list)

Each item is removed by the change that touches the code, and the matching rule then tightens.

| Debt | Target |
|---|---|
| `app/api/chat.py` queries the database directly | Split into `app/chat/{router,service,repository}` on the next chat change |
| `app/config.py` and `app/database.py` predate `app/core` | Move into `app/core/` when next modified |
| `atlas_audit_log.user_uid` is a legacy text owner key (the log is append-only); `user_id` is the real owner since migration 0003 | Stop writing `user_uid` once nothing reads it |
| `[tool.pyright].strict` covers new modules (`insights`, `identity`, `access`, `mcp`) | Each new module joins it on creation |
| MCP per-source rate limits are global until 4b: uvicorn runs without trusted proxy headers, and `app/mcp/ratelimit.py` treats a loopback, private or link-local peer (nginx, the SSH tunnel, the compose network) as the source "unknown". So `/token`, `/authorize` and `/register` each share one global key, and the failed-bearer guard only logs for an unknown source, never blocks (ruling E1). It counts only bearers the door does not recognise, never an expired real token | At 4b run uvicorn with `--proxy-headers --forwarded-allow-ips=<compose subnet>`; a public client IP is then keyed as itself and the guard blocks it |
| MCP rate limits are in process, so correctness needs a single uvicorn worker | Move to a shared store (Postgres or Redis) before adding workers or replicas |
| OAuth consent is not bound to the browser that started `/authorize` (a victim could approve an attacker-started request) | Set an HttpOnly txn cookie on `/authorize` and require it on consent before hosted connectors (4b) |
| `identity.revoke_user_tokens` swallows errors after the disable commit: if it fails and the user is later re-enabled, old tokens work again | Alert on the `identity.revoke_all_failed` log event; make the revocation part of the disable transaction when access and identity share a unit of work |
| OAuth Client ID Metadata Documents (CIMD) are not supported; clients register with DCR | Add CIMD with port-agnostic loopback matching and an SSRF-safe fetch if a client needs it |
| Frontend features are flat files | Split per §3.2 when a feature passes about 8 files |
| An x86_64 macOS toolchain (an Intel Mac, or the x86_64 uv/Python under Rosetta used on the current M1 dev machine) gets `cryptography` 48.0.1, because no newer x86_64 macOS wheels exist; 3 advisories apply to that local venv only, so `make audit-backend` is expected red there. Linux (CI, Docker, EC2) and arm64 macOS use the patched 50.x | Switch dev machines to a native arm64 uv and Python, then drop the platform pin |
| `@grpc/grpc-js` is forced to ^1.13.6 by a pnpm override (Firebase's Firestore pins a vulnerable 1.9.x; atlas uses only Firebase auth in the browser) | Remove when Firebase ships a fixed Firestore |

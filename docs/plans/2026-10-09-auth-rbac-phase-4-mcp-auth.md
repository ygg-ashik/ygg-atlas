# Auth & RBAC Phase 4: MCP Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Before writing any code, follow `.claude/skills/engineering-standards/SKILL.md`; before
> calling a task done, run the gate below and the `production-code-review` skill.

**Goal:** Every MCP request runs as a real, individually revocable person or service account. Claude
Code (and later claude.ai, Desktop, mobile and Cowork) connects through a spec-conformant OAuth 2.1
authorization server with PKCE, dynamic client registration, audience binding and rotating refresh
tokens with reuse detection. Scripts and CI use personal access tokens (`atl_pat_`) or service tokens
(`atl_svc_`). `tools/list` shows only what the caller may use, every call is audited with its
credential, and the shared `ATLAS_MCP_TOKEN` is gone.

**Architecture:** `app/identity` owns every credential: hashed token rows, OAuth clients, pending
authorizations, codes and the append-only `credential_events` log, plus the single bearer door
`authenticate_bearer`. It never imports `app/access` or the MCP SDK. `app/mcp` is the policy-aware
edge: it adapts the identity services to the pinned MCP SDK (`mcp==1.30.0`) handlers, models and
bearer middleware, owns the route table, the discovery documents, the consent and token APIs, rate
limits and a CLI, and checks `mcp:use` through `app/access`. The atlas kernel only gains two
`AtlasCaller` fields and two audit columns.

**Tech stack:** FastAPI, Starlette, MCP Python SDK 1.30.0 (`mcp.server.auth.*`, FastMCP), SQLModel /
SQLAlchemy async, Alembic, pytest (+ xdist), httpx ASGI transport, ruff, pyright (strict for
`app/identity`, `app/access`, `app/mcp`), import-linter; React 19 + Vite + Vitest for the consent page.

**Spec:** `docs/specs/2026-10-08-auth-rbac-design.md` §3 (doors, checks, disable revokes tokens),
§4.1 (MCP flow and denial pages), §4.3 (OAuth 2.1 conformance), §6 (enforcement point 1:
`tools/list`), §7 (`api_tokens`, `oauth_clients`, `oauth_codes`), §8, §9, §10 (API only), §11.5,
§12, §13 (MCP tests), §14 phase 4, §16 (verified below).
**Binding inputs:** `scratchpad/p345/contracts.md` (cross-phase contracts),
`scratchpad/p345/phase4-analysis.md` (D1–D20), `scratchpad/p345/p4-rules.md`.

**Working directory:** worktree `/Users/ashikbabu/Projects/ygg-atlas/.claude/worktrees/p4-mcp-auth`,
branch `feature/auth-mcp`, based on `origin/main` @ `ac8ba38`. Backend commands run from `backend/`
with `uv run …`; frontend commands from `frontend/` with `COREPACK_INTEGRITY_KEYS=0 corepack pnpm …`.

**Gate (every task, once, before its commit):**

```bash
cd backend && uv run ruff check . ../evals && uv run ruff format --check . ../evals \
  && uv run pyright && uv run lint-imports && uv run pytest -n auto -q
# frontend tasks (10, 12) also:
cd frontend && COREPACK_INTEGRITY_KEYS=0 corepack pnpm -s check
```

Iterate with targeted tests (`uv run pytest tests/identity/test_x.py -q`); run the full gate once.
Stage only the task's own paths (never `git add -A`). Commit messages end with a blank line and
`Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Commits are signed; on a
signing failure retry 2–3 times, never bypass, and report `SIGNING_FAILED`.

---

## As built: deviations recorded during implementation

The orchestrator's rulings and review outcomes (`scratchpad/p345/p4-rules.md`) supersede this plan
where they differ:

- **C5 (ruled):** `access/admin.py` has no `import re` and no helpers. Slug and email derivation
  live in `app.identity.service_account_email(name) -> str | None` (None → `InvalidChangeError`);
  `admin.py` only extends its existing identity import line, adds `create_service_account` and the
  one revoke-all line in `update_user`. The `re.sub` snippet in Task 3 is superseded.
- **C8 (ruled):** RFC behaviour kept: a reused code revokes the whole family, including the
  winner's tokens.
- **C4 (ruled):** `App.tsx` gets the import, a small composition wrapper and the route.
- **Task 2:** `CredentialRepository.live_family_counts(now)` takes `now`; `RegisteredClient` ends
  with `secret_hash` (`repr=False`); `list_events(tenant=…)` without `user_id` also returns user-less
  events; extra identity exports (`REVOKED_BY_*`, `CredentialVia`, `Credential{Rule,Limit,NotFound}Error`).
- **Tasks 3–5:** the bearer door runs on its own fresh DB session per call; redirect URIs are stored
  and compared as `str(AnyUrl)`; the RFC 7009 handler checks the token's `client_id` against the
  authenticated client before revoking. A refresh token presented to `/revoke` by a different
  client revokes its family (detected as cross-client reuse) and still answers 200: an intentional
  fail-safe.
- **E1 (ruled, Task 6/7; as built in `app/mcp/ratelimit.py`):** a loopback, private (RFC 1918,
  IPv6 ULA) or link-local peer is the source `"unknown"`, so behind nginx or the SSH tunnel (4a)
  the per-source limits for `/token`, `/authorize` and `/register` each share one global key, and
  the failed-bearer guard only logs (`ratelimit.bearer_failure_unattributed`), never blocks. It
  counts only bearers the verifier does not recognise, never expired-but-valid tokens. The limiter
  registry is keyed by the frozen policy.
- **Task 6 (from reviews):** identity `ForbiddenError` carries a machine `reason`
  (`user_disabled`, `not_company_account`, `service_account`); the consent route and the consent
  page switch on it, so **the consent page shows fixed Atlas copy and never a backend message**.
  `hash_secret` is exported from identity and reused by `app/mcp/auth.py`.
- **Task 6 (accepted deviation, C7/D31):** a `tools/call` from a caller without `mcp:use` is
  refused at the MCP layer and logged as `mcp.tool_denied` with its token and client ids, but it
  writes **no `atlas_audit_log` DENY row**: the audit write lives in `atlas/tools.py` (a shared
  hotspot phase 4 may not change beyond `_audit`). Follow-up: a DENY row with
  `deny_reason="capability:mcp:use"` through a public atlas API after integration (phase 5
  decisions view).
- **Task 4 (independent re-review after `d5aaae8`):**
  - Lock order for issuing transactions is client row → family advisory lock → user row
    `FOR SHARE` (`CredentialRepository.lock_user`, PostgreSQL only) → token or code rows. A user
    disable (`update_user`) therefore waits for an in-flight issue and its post-commit revoke-all
    sees the new pair; or the disable commits first and the issuer refuses. `update_user` takes
    no client or family lock, so there is no cycle.
  - `revoke_user_tokens` (admin or CLI revoke-all, and the disable hook) locks the user row
    `FOR NO KEY UPDATE` (PostgreSQL) before the token rows. An issuer holding the row `FOR SHARE`
    commits its pair first and the revoke sees it; a later issuer waits, then finds its refresh
    token revoked (reuse path) and mints nothing. The order is user row → token rows on both
    sides, so there is no cycle.
  - Multi-row token writes (revokes by family, client or user, and the GC delete of OAuth token
    rows) are single statements, `WHERE id IN (SELECT id … ORDER BY id FOR UPDATE)`, so they
    lock in id order and overlapping writes queue instead of deadlocking. PostgreSQL keeps the
    locking subquery unflattened (checked with EXPLAIN).
  - The per-issue user status check re-reads the row (`populate_existing`) after `lock_user`.
  - Eligibility has three outcomes: True; False (`no_mcp_use`: the code is spent, or the family
    is revoked on refresh); or `EligibilityUnavailableError` (could not check).
  - Transient grant failures (any `SQLAlchemyError` in load, exchange or rotate, or an
    eligibility check that could not be made) raise `GrantUnavailableError` (exported from
    `app.identity`; not an `OAuthGrantError`). The provider lets it propagate and the
    `oauth_routes` guard answers a fixed 500 `server_error` (no-store; only the exception type is
    logged). Nothing is issued, spent or revoked, so the client's code or refresh token stays
    usable. `invalid_grant` is reserved for definite refusals.
  - Revoking an OAuth token by id (`DELETE /admin/tokens/{id}`, `DELETE /me/tokens/{id}`, CLI
    `revoke-token`) revokes its whole family under the family lock and writes
    `oauth.family_revoked`; revoking only the access row would let the live refresh token mint a
    new pair.
  - Revoke-all (admin, CLI, disable hook) and client revoke also delete outstanding unused,
    unexpired authorization codes (id-ordered, after the user or client row), so a code consented
    to before the revoke cannot mint a pair after it. They are deleted rather than marked used, so
    a later exchange is a plain dead code, not a false `oauth.reuse_detected`. The events carry a
    `codes` count: `tokens.revoked_all` {count, codes, reason}, `client.revoked` {tokens, codes}.
  - Client revoke revokes and counts only live rows (unrevoked and unexpired), so its lock set
    never overlaps GC's (rows expired or revoked over 30 days ago, then client rows).
  - A refresh token revoked for any reason other than rotation (admin, disable, client revoke,
    family cut) is a plain dead token on its next use: `invalid_grant`, no `oauth.reuse_detected`
    alarm and no second family revoke. A rotated token outside the grace and a missing row are
    still reuse.
  - Accepted residual: consent `approve` takes no user lock, so a consent approved at the same
    instant as a revoke-all can insert a code after `spend_user_codes` and still mint a pair. The
    window is tiny and needs the user's own live Firebase session.
  - `oauth.database_error` carries `op`. A failed revoke on a reuse path logs `oauth.reuse_revoke_failed`;
    `oauth.reuse_detected` logs `presented_by_client_id` for cross-client reuse.
- **Task 11:** nginx redacts the txn from access logs with a log-format map instead of
  `access_log off` (Task 11 section). The discovery location is narrowed to
  `location ^~ /.well-known/oauth-` (every backend discovery path starts with it), so an outer TLS
  proxy can keep other `/.well-known/` paths such as ACME. `CLAUDE.md` is not edited by the
  implementer (out of bounds for agents); the guardrail-4 sentence below is left to the user.
  `backend/tests/test_deploy_config.py` was written in the Task 11 completion pass (after Task 6);
  the config was also checked with `nginx -t` and a header and log smoke test.
- **Task 12 (smoke script, from review):** `scripts/mcp_oauth_smoke.py` takes PATs from the
  environment (`ATLAS_PAT`, and `ATLAS_REVOKED_PAT` for the revoked-PAT → 401 check) instead of
  shelling out to `app.mcp.cli`, so it can run against the public URL; the consent bearer comes from
  `ATLAS_FIREBASE_TOKEN` (no secret flags). `--base-url` is required (no default: `localhost:8080`
  is the tunnel to the shared box) and plain http is refused for non-loopback hosts. Every OAuth
  endpoint is discovered (401 challenge → PRM → RFC 8414 AS metadata) and must live under
  `--base-url`. The `/register` limit check is opt-in (`--check-register-limit
  --allow-shared-impact`): in 4a it blocks DCR for all clients for an hour.

## 0. Contradictions found while verifying (read first)

Each item was checked against the installed SDK (`backend/.venv/lib/python3.12/site-packages/mcp`,
version 1.30.0) or the code at `ac8ba38`. The recommended resolution is what this plan implements.
Items marked **(coordinator)** touch a shared contract and need the coordinator's acknowledgement.

| # | Finding (evidence) | Contradicts | Resolution in this plan |
|---|---|---|---|
| C1 | FastMCP auto-enables DNS-rebinding protection when `host` is the default `127.0.0.1`: `allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"]` (`mcp/server/fastmcp/server.py:191-196`). `_validate_host` needs a port for the `:*` patterns (`mcp/server/transport_security.py`, `_validate_host`), and nginx sends `proxy_set_header Host $host` (no port, `frontend/nginx.conf:12`). Behind nginx every MCP request gets **421 Invalid Host header**; a public hostname (4b) gets 421 too. | Analysis §1.3 "4b is configuration only" | D26: build `TransportSecuritySettings` from `ATLAS_PUBLIC_URL` (its `host:port`, bare host, loopback patterns) and use `proxy_set_header Host $http_host` in the new nginx locations (Task 6, Task 11). With both, 4b stays configuration only. |
| C2 | `RevocationRequest.client_secret: str \| None` has no default (`mcp/server/auth/handlers/revoke.py:25`); in Pydantic v2 that field is required, so a public (`none`) client that omits `client_secret` gets **400** from `/revoke`. | D1 "use the SDK handlers" | D29: our own `AtlasRevocationHandler` (same logic, `client_secret` optional, our authenticator) in `oauth_routes.py` (Task 5). |
| C3 | `evals/run_evals.py:35,188` imports and calls `ensure_service_user`. Phase 4 may not touch `evals/*`. | D17 "delete `ensure_service_user`" | D32: keep `ensure_service_user` (it is generic). Delete only `service_principal`, `BearerTokenMiddleware`, `atlas_mcp_token`, `mcp_service_email` and the `MCP_SERVICE_*` constants (Task 6). |
| C4 | `frontend/eslint.config.*` forbids `@/features/*` imports inside a feature ("Compose them in App.tsx"). The consent page cannot import `useAuth` from `@/features/auth`. | Contract "App.tsx: one route" and the brief "reuse the auth feature's public interface" **(coordinator)** | `ConsentPage` takes a `session` prop (`email`, `isLoading`, `signIn`). App.tsx gains the import, a 5-line composition wrapper like the existing `Home`, and the one route line (Task 10). |
| C5 | `AccessAdmin` has no public DB session (`AccessRepository._db` is private, `app/access/repository.py:52-53`), so the "one appended line" cannot call a session-taking identity function; the import line and `re` also change. | Contract "ONE method + ONE appended line, nothing else" in `access/admin.py` **(coordinator)** | The line calls `revoke_user_tokens(user.id, reason=…, actor_user_id=…, via=…)`, which opens its own session after the status commit (same post-commit pattern as `_end_firebase_sessions`) and never raises. `admin.py` also extends its existing `from app.identity import …` line and adds `import re`. No other change. |
| C6 | The analysis puts the access hooks in Task 8, but Task 9 (CLI, parallel with 8) calls `AccessAdmin.create_service_account`; Task 5's rate limits and Task 8's consent limit need `ratelimit.py` from Task 7 (parallel). | Analysis §6 task contents | Access hooks move to **Task 3**; rate-limit wiring moves to **Task 6** (serialized). Task numbers are unchanged. |
| C7 | `RequireAuthMiddleware` can return 403 only as `insufficient_scope` (`mcp/server/auth/middleware/bearer_auth.py:133-139`). MCP 2025-11-25 clients treat that as a scope step-up trigger; we advertise no scopes (D10), so a 403 there would loop the client through re-authorization. | Analysis Task 6 "403 on calls without `mcp:use`" | D31: no HTTP 403. A caller without `mcp:use` gets an empty `tools/list` and a tool-level denial message on `tools/call` (HTTP 200), as phase 2 does today. |
| C8 | RFC 6749 §4.1.2: a code used twice must be refused and tokens issued from it SHOULD be revoked. With `UPDATE … WHERE used_at IS NULL` the loser of a concurrent exchange sees 0 rows. | "Concurrent code exchange: exactly one wins" (brief) | D30: exactly one exchange returns 200, the other `invalid_grant`, **and the family (the winner's tokens) is revoked** as reuse. The PG test asserts all three. If the coordinator prefers the winner to keep its tokens, only the loser branch in `exchange_code` changes. |
| C9 | `StreamableHTTPSessionManager.run()` can be called once per instance (`mcp/server/streamable_http_manager.py:141-159`), and FastMCP reads auth settings at construction. A module-level `mcp` built at import (today) cannot be re-run by tests and freezes `ATLAS_PUBLIC_URL`. | Analysis §4 exports `mcp` (an AtlasMCP) | D27: `build_mcp(settings) -> AtlasMCP` and `build_http_app(server, settings)`; `main.py` builds one at import, tests build a fresh one per test. |
| C10 | SDK `AccessToken.token`, `RefreshToken.token` and `AuthorizationCode.code` are plain Pydantic fields, so the raw secret would appear in every `repr()`. A grep of `mcp/server` shows the SDK never reads them back. | "Raw tokens never in reprs" | D28: our carriers put the 14-char display prefix in those fields; the raw value exists only in the request and the response body. |
| C11 | `authenticate_bearer` must give the verifier the token's expiry and audience, not just a `Principal`. | Analysis §4 signature `-> Principal` | Returns `AuthenticatedBearer(principal, expires_at, audience, display_prefix)` (Task 3). |
| C12 | Analysis lists both `OAuthService.verify_access_token` and `authenticate_bearer`. | — | One door: `authenticate_bearer` handles `atl_oat_` too (D20). `verify_access_token` is not built. |
| C13 | Status is part of the cached Policy (spec §3.2). Disabling `mcp-shared@atlas.internal` in migration 0005 without a version bump leaves a stale cached Policy on any long-lived worker. | Analysis §5 "Data: disable mcp-shared" | Migration 0005 also writes an `rbac_changes` row (`via="migration"`) and bumps `policy_state.policy_version`. |
| C14 | The SDK's `validate_issuer_url` accepts `http` only for `localhost` and `127.0.0.1` (`mcp/server/auth/routes.py:37-42`); `http://[::1]` fails. The SDK checks code and token expiry with `time.time()` (`handlers/token.py:145,209`, `bearer_auth.py:77`), not our clock. | — | `ATLAS_PUBLIC_URL` validation mirrors the SDK rule (Task 1). Expiry tests age rows in the DB instead of injecting a clock into SDK paths. |
| C15 | Uvicorn runs without `--proxy-headers` (`backend/Dockerfile` CMD), and all tunnel users arrive through one nginx container, so every per-source limit is effectively global in 4a. `/register` at 10/h could 429 a team onboarding at once. | D16 | Kept as analysed and documented (README, ARCHITECTURE §6 debt row). Listed in Risks with the fix for 4b (trusted proxy IP). |
| C16 | ARCHITECTURE.md §6 says `app/config.py` moves to `app/core` "when next modified". | — | Not moved: `config.py` is a cross-phase hotspot (contracts). The debt row stays. |

## Decisions this plan makes (read before starting)

D1–D20 come from the analysis (adjusted where §0 says so). D21–D36 come from the contracts, the
approved defaults and verification. Change them only with the user.

| # | Decision | Why |
|---|---|---|
| D1 | **SDK handlers, our routing.** `app/mcp/oauth_routes.py` builds the route table from the SDK's `AuthorizationHandler`, `TokenHandler`, `RegistrationHandler` and `MetadataHandler`, with our provider, our `HashedClientAuthenticator`, our `OAuthMetadata`, and our own revocation handler (D29). FastMCP gets `token_verifier=` and `AuthSettings(issuer_url, resource_server_url, validate_token_resource=True)`, never `auth_server_provider`. | The SDK handlers are spec-tested; everything stateful and security-critical is ours. |
| D2 | **One setting, `ATLAS_PUBLIC_URL`** (default `http://localhost:8080`, no path). Issuer `<url>/mcp-server`; resource `<url>/mcp-server/mcp`; endpoints `<issuer>/{authorize,token,register,revoke}`; AS metadata at `<url>/.well-known/oauth-authorization-server/mcp-server` and `<issuer>/.well-known/oauth-authorization-server`; PRM at `<url>/.well-known/oauth-protected-resource/mcp-server/mcp`; consent at `<url>/oauth/consent`. `http` only for `localhost`/`127.0.0.1`; a localhost URL in production logs `mcp.public_url_local` at startup. | Claude requires the PRM `resource` to equal the URL the user typed; one knob makes 4b a config change. |
| D3 | **Opaque 256-bit tokens, SHA-256 at rest.** `prefix + secrets.token_urlsafe(32)` with `atl_pat_`, `atl_svc_`, `atl_oat_`, `atl_ort_`; stored as a 64-char hex hash (unique index) plus a 14-char display prefix. An unknown prefix or a malformed body is rejected before any DB lookup. Lifetimes: access 60 min; refresh 30 d sliding; PAT and service 90 d default, 365 d max; code 60 s; pending authorization 10 min; idle DCR client GC after 90 d. `last_used_at` written at most every 5 min. At most 10 live PATs per user. | Revocable, leak-resistant; JWTs rejected (no revocation without extra machinery). |
| D4 | **Upstream identity is the existing Firebase web door.** `/authorize` stores the request and 302s to `/oauth/consent?txn=…` (outside `ProtectedRoute`). Approve is `POST /api/v1/oauth/consent` with the Firebase bearer, which runs `get_principal`, requires `mcp:use`, consumes the request atomically and returns the redirect. Ineligible users (non-company, disabled, no `mcp:use`) get a page, never a redirect. | No second sign-in system; scope comes from the token. |
| D5 | **Codes:** 256-bit, hashed, 60 s, bound to client, redirect, PKCE challenge, user, audience and a new `family_id`; single use by `UPDATE … WHERE used_at IS NULL`; any reuse revokes the family. | RFC 6749 §4.1.2, §10.5. |
| D6 | **Refresh rotation with reuse detection.** Each refresh revokes the presented token (`rotated`) and issues a new pair in the same family. A rotated token presented again by the **same client within 30 s while the family still has a live token** gets a fresh pair (logged `oauth.refresh_grace`); anything else (later, cross-client, superseded, family revoked) revokes the family and returns `invalid_grant`. Every refresh re-checks: user active and human, `mcp:use`, client not revoked, audience equals the current resource URL. | Approved default 6; public clients must rotate (MCP 2025-11-25). |
| D7 | **Audience.** `authorize()` rejects a `resource` whose canonical form (`str(AnyHttpUrl(u)).removesuffix("/")`, the SDK's own comparison) differs from the configured resource; a missing `resource` is bound to it anyway. OAuth tokens store their audience and `validate_token_resource=True` enforces it per request. PATs and service tokens report the current resource URL, so they survive a domain switch. | RFC 8707; one canonicalisation for issue and check. |
| D8 | **DCR on, allowlisted.** Every `redirect_uri` must be loopback `http` (`localhost`, `127.0.0.1`, `[::1]`; any port, any path, no userinfo, no fragment) or exactly one of `OAUTH_HOSTED_REDIRECT_URIS` (default `https://claude.ai/api/mcp/auth_callback`). Parsing uses Pydantic `AnyUrl` (WHATWG, the browser's parser) so there is no parser differential. Public clients are expected; confidential clients are accepted with the secret hashed. ≤ 5 redirect URIs, `client_name` ≤ 100 chars (else "Unnamed client" in the UI). `get_client` drops any stored URI that is no longer allowed and returns `None` when none remain. | Spec §4.3; Desktop uses `http://localhost:35535/oauth/callback`. |
| D9 | **CIMD deferred** and not advertised (`client_id_metadata_document_supported` omitted), so Claude Code uses DCR. | CIMD needs port-agnostic loopback matching and an SSRF-safe fetch. |
| D10 | **No scopes, no narrowing.** `scopes_supported` omitted, tokens carry `scopes=[]`, rights come only from the Policy. The spec §7 `scope_narrowing` column is not created. | Approved default 7 (accepted spec deviation). |
| D11 | **PATs open the MCP door only.** REST `get_principal` stays Firebase-only. | Smaller blast radius. |
| D12 | `Principal` and `AtlasCaller` gain `token_id: UUID \| None = None` and `client_id: str \| None = None` (appended, defaulted). `atlas_audit_log` gains `token_id`, `client_id` (appended, no FKs). MCP `auth_method` is `oauth`, `pat` or `service`. | Spec §9; contracts. |
| D13 | **Service accounts:** `users(kind=service, owner_user_id=actor, role)` with email `svc-<slug>@atlas.internal`, created by `AccessAdmin.create_service_account(actor, name, role)` (needs `admin:users`, D10 role check, `rbac_changes` + version bump). Service tokens need `admin:tokens`; clients need `admin:clients`. | Contracts cross-phase links. |
| D14 | **Placement.** Identity: `api_tokens.py` (pure), `credentials.py` (TokenService, the bearer door), `oauth.py` (OAuthService), plus models, `CredentialRepository`, errors. MCP: `auth.py`, `oauth_provider.py`, `oauth_routes.py`, `router.py`, `schemas.py`, `dependencies.py`, `ratelimit.py`, `cli.py`, `server.py`. Coverage omits only `migrations/*`; `app/mcp` is pyright-strict. | ARCHITECTURE §2.2. |
| D15 | **`credential_events`** (identity-owned, append-only): token created/revoked, revoke-all, client registered/revoked, consent approved/denied, tokens issued/refreshed/graced, reuse detected, family revoked, gc. `rbac_changes` is used only for service-account creation (and the migration's status change). | Approved default 7; identity cannot write the access model. |
| D16 | **In-process sliding-window limits** returning 429 + `Retry-After`: MCP calls 120/min per token; `/token` 30/min; `/authorize` 30/min; `/register` 10/h; failed bearer 20/min per source; consent 10/min per user. Per-source keys use the ASGI client address (degrades to global behind nginx, C15). | One uvicorn worker. |
| D17 | **The shared token is retired:** remove `atlas_mcp_token`, `mcp_service_email`, `BearerTokenMiddleware`, `service_principal` and the `MCP_SERVICE_*` constants; migration 0005 disables `mcp-shared@atlas.internal`. `ensure_service_user` stays (C3). | Spec §11.5. |
| D18 | **Disabling a user revokes their tokens:** one appended statement in `AccessAdmin.update_user` after `_end_firebase_sessions` (C5). The bearer door also refuses disabled users, so a failed revocation never opens access. | Spec §3.2. |
| D19 | **`tools/list` filtering:** `AtlasMCP(FastMCP).list_tools()` resolves the caller and Policy and applies `TOOL_REQUIREMENTS` (`list_metrics`, `search_atlas`, `describe_entity`: `mcp:use`; `query_metric`, `metric_breakdown`, `compare_periods`: `mcp:use` + a visible metric; `funnel_analyze`: `mcp:use` + a visible funnel). A tool missing from the table is never listed; any failure lists nothing. `stateless_http=True` stays. | Spec §6 point 1. |
| D20 | **Per-request flow:** bearer → `AtlasTokenVerifier.verify_token` → `identity.authenticate_bearer` (prefix, kind, hash, not revoked/expired, user active and kind-consistent, OAuth client live) → `AtlasAccessToken` → SDK expiry + audience check → `run_tool` reads the contextvar, `policy_for`, requires `mcp:use` → `AtlasCaller(surface="mcp", token_id, client_id)` → `AtlasTools`, audited. Any exception collapses to "unavailable". | Fail closed. |
| D21 | **Migration `0005`**, `down_revision = "0003"  # chain: set to predecessor at integration`. Appended columns go at the end of the model and the migration. | Contracts (Alembic chain). |
| D22 | **`GET /api/v1/meta/auth-methods`** (any authenticated user) → `{pat:{enabled, default_days, max_days}, oauth:{enabled, hosted_connectors}}`; `hosted_connectors` is true only when `ATLAS_PUBLIC_URL` is https. Lives in `app/mcp/router.py` (Task 8). | Contract addition for phase 5. |
| D23 | **Approved defaults 5, 6, 7:** admins mint PATs on the box with the CLI until phase 5 (audited `via=cli`, shown once); 30 s refresh grace for the same client only; no token scope narrowing. | User decisions 2026-10-09. |
| D24 | **Token and client revocations go to `credential_events`**, never `rbac_changes`. Phase 5's audit "Credentials" tab reads `/admin/credential-events`. | Contracts. |
| D25 | **Appended audit columns:** `atlas_audit_log.token_id` (uuid) then `client_id` (varchar 255), after phase 3's `scope`, `masking` at integration. | Contracts. |
| D26 | **Transport security from `ATLAS_PUBLIC_URL`** (C1): `allowed_hosts = [<host:port>, <host>, "localhost:*", "127.0.0.1:*", "[::1]:*", "localhost", "127.0.0.1"]`, `allowed_origins = [<origin>, "http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*"]`. | DNS-rebinding protection stays on and works behind nginx and at 4b. |
| D27 | **Factories, not a module singleton** (C9): `build_mcp(settings)`, `build_http_app(server, settings)`. | Testability; settings are not frozen at import. |
| D28 | **Carriers never hold secrets** (C10): `AtlasAccessToken.token`, `AtlasRefreshToken.token`, `AtlasAuthorizationCode.code` hold the display prefix; ids travel in extra fields. | No raw token in any repr or log. |
| D29 | **Own revocation handler** (C2): RFC 7009 semantics, `client_secret` optional, always 200 for unknown tokens, revokes the whole family. | Public clients can revoke. |
| D30 | **Concurrent code exchange** (C8): exactly one 200; the other `invalid_grant`; the family is revoked. | RFC 6749 §4.1.2. |
| D31 | **No HTTP 403 for missing `mcp:use`** (C7): empty `tools/list`, tool-level denial. | Avoids step-up loops. |
| D32 | **`ensure_service_user` stays** (C3). | evals depend on it. |
| D33 | **The MCP door ignores `AUTH_DISABLED`.** MCP always needs a real token; only the consent API (a REST route) uses the dev principal under `AUTH_DISABLED`. | No anonymous data path, even locally. |
| D34 | **Minting a service token** needs `admin:tokens`, an active service account in the actor's tenant, and the account's effective capabilities ⊆ the actor's (D10 parity, phase 2). | No escalation through a stronger service account. |
| D35 | **Interface first.** Task 2 lands the identity public API as typed skeletons (`raise NotImplementedError`) and its exports, so Tasks 3–4 fill bodies in disjoint files and Tasks 5, 8, 9 code against stable imports. | Parallel groups stay file-disjoint. |
| D36 | **Authorization-request ids (`txn`) are 256-bit and stored hashed**; consent POST bodies carry only `{transaction_id, decision}`; the code is bound to the authenticated principal, never to anything in the body. | Consent CSRF / fixation. |

## File map

| File | Task | Responsibility |
|---|---|---|
| `backend/app/config.py` (modify) | 1, 6 | `atlas_public_url`, `oauth_hosted_redirect_uris`, `pat_default_days`, `pat_max_days` + derived URLs and validation (1); remove `atlas_mcp_token`, `mcp_service_email` (6) |
| `backend/app/identity/principal.py` (modify) | 1 | `token_id`, `client_id` (appended, defaulted) |
| `backend/app/identity/api_tokens.py` (new) | 1 | Pure: `TokenKind`, `TOKEN_PREFIXES`, TTLs, revoke reasons, event names, `CredentialActor`, `mint`, `mint_secret`, `hash_secret`, `kind_of`, `display_prefix` |
| `backend/app/atlas/policy.py` (modify) | 1 | `AtlasCaller.token_id`, `AtlasCaller.client_id` |
| `backend/pyproject.toml` (modify) | 1, 2, 6 | Identity layers, `app/mcp` strict, coverage omit (1); `credentials \| oauth` layer (2); MCP layering contract (6) |
| `backend/app/mcp/server.py` (modify) | 1, 6 | `# pyright: basic` file pragma until the rewrite (1); per-principal server (6) |
| `backend/app/identity/models.py` (modify) | 2 | `ApiToken`, `OAuthClient`, `OAuthAuthorizationRequest`, `OAuthCode`, `CredentialEvent` |
| `backend/app/identity/repository.py` (modify) | 2 | `CredentialRepository`: every credential read and atomic write |
| `backend/app/identity/errors.py` (modify) | 2 | `CredentialRuleError`, `CredentialLimitError`, `CredentialNotFoundError` |
| `backend/app/identity/credentials.py` (new) | 2, 3 | `TokenService`, `authenticate_bearer`, `principal_for_user`, `revoke_user_tokens` (skeleton 2, bodies 3) |
| `backend/app/identity/oauth.py` (new) | 2, 4 | `OAuthService`, `OAuthConfig`, carriers, `redirect_allowed`, `canonical_resource` (skeleton 2, bodies 4) |
| `backend/app/identity/__init__.py` (modify) | 2, 6 | Exports (2); drop `service_principal` (6) |
| `backend/app/identity/service.py` (modify) | 6 | Remove `service_principal` |
| `backend/app/models/audit.py` (modify) | 2 | Append `token_id`, `client_id` |
| `backend/app/atlas/tools.py` (modify) | 2 | `_audit` writes `token_id`, `client_id` (2 lines) |
| `backend/migrations/versions/0005_mcp_auth.py` (new) | 2 | Tables, audit columns, disable `mcp-shared` |
| `backend/app/access/admin.py` (modify) | 3 | `create_service_account` (one method, at the end); one statement in `update_user`; import lines |
| `backend/app/access/__init__.py` (modify) | 3 | Export `AccessAdmin`, `Actor`, `get_access_admin`, `get_actor`, `TOKENS_CREATE`, `ADMIN_TOKENS`, `ADMIN_CLIENTS` |
| `backend/app/mcp/auth.py` (new) | 5 | `AtlasAccessToken`, `AtlasTokenVerifier` |
| `backend/app/mcp/oauth_provider.py` (new) | 5 | `AtlasOAuthProvider`, `HashedClientAuthenticator`, carriers |
| `backend/app/mcp/oauth_routes.py` (new) | 5, 6 | Sub-app OAuth routes, `build_oauth_metadata`, `AtlasRevocationHandler`, root `discovery_router` (5); rate-limit wrappers (6) |
| `backend/app/mcp/ratelimit.py` (new) | 7 | `SlidingWindowLimiter`, `RateLimitPolicy`, ASGI guards, FastAPI dependency |
| `backend/app/mcp/schemas.py` (new) | 8 | API shapes (analysis §4 + auth-methods + consent + service accounts) |
| `backend/app/mcp/dependencies.py` (new) | 8 | Service factories for the router |
| `backend/app/mcp/router.py` (new) | 8, 6 | `/me/tokens`, `/me/connected-apps`, `/oauth/consent`, `/admin/*` credentials, `/meta/auth-methods` (8); consent rate limit (6) |
| `backend/app/mcp/cli.py` (new) | 9 | `python -m app.mcp.cli` |
| `backend/app/mcp/__init__.py` (modify) | 6 | Public interface |
| `backend/app/main.py` (modify) | 6 | Mount, routers, startup, lifespan; shared-token code removed |
| `frontend/src/features/oauth-consent/*` (new) | 10 | `ConsentPage`, data hook, API calls, tests |
| `frontend/src/App.tsx` (modify) | 10 | Import, composition wrapper, route `/oauth/consent` outside `ProtectedRoute` |
| `frontend/vite.config.ts` (modify) | 10 | Dev proxy for `/mcp-server` and `/.well-known` |
| `DESIGN.md` (modify) | 10 | `consent-panel` component entry (own entry only) |
| `frontend/nginx.conf`, `backend/.env.example`, `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, spec | 11 | Deploy config and docs (own sections only) |
| `backend/scripts/mcp_oauth_smoke.py` (new) | 12 | Scripted PKCE client for manual verification (local now, 4b later) |
| Tests | each task | Listed per task; new files wherever possible (contracts) |

## Parallel execution and file ownership

```
1 ──▶ 2 ──▶ ┬─ 3 ─┬──▶ ┬─ 5 ─┬──▶ 6 ──▶ 11 ──▶ 12
            └─ 4 ─┘    ├─ 7 ─┤
                       ├─ 8 ─┤
                       ├─ 9 ─┤
                       └─ 10 ┘
```

Groups: **A** = {1}, **B** = {2}, **C** = {3, 4}, **D** = {5, 7, 8, 9, 10}, then 6, 11, 12 serially.
Inside a group, file sets are disjoint (checked below). A file touched by two tasks is always touched
in different groups, in dependency order. Shared hotspots: `pyproject.toml` (1, 2, 6),
`identity/__init__.py` (2, 6), `config.py` (1, 6), `server.py` (1, 6), `oauth_routes.py` (5, 6),
`router.py` (8, 6), `credentials.py` (2, 3), `oauth.py` (2, 4). `main.py` and
`mcp/__init__.py` are Task 6 only. No task in a parallel group edits `pyproject.toml`,
`identity/__init__.py`, `identity/service.py`, `mcp/__init__.py` or `main.py`.

Cross-task imports inside group D: none. Task 8 and Task 9 depend on `access` exports and
`create_service_account` from Task 3 (group C, already committed); Task 8's consent API depends on
`OAuthService` from Task 4; nothing in D imports another D task's module.

| Task | Group | Creates | Modifies | Tests (create / modify) |
|---|---|---|---|---|
| 1 | A | `identity/api_tokens.py` | `config.py`, `identity/principal.py`, `atlas/policy.py`, `mcp/server.py` (pragma line), `pyproject.toml` | `tests/identity/test_api_tokens.py`; modify `tests/test_config.py`, `tests/identity/test_types.py` |
| 2 | B | `identity/credentials.py` (skeleton), `identity/oauth.py` (skeleton), `migrations/versions/0005_mcp_auth.py` | `identity/models.py`, `identity/repository.py`, `identity/errors.py`, `identity/__init__.py`, `models/audit.py`, `atlas/tools.py` (`_audit`), `pyproject.toml` | `tests/test_alembic_mcp_auth.py`, `tests/identity/test_credential_repository.py`, `tests/identity/credential_helpers.py`, `tests/test_audit_credentials.py`, `tests/mcp/__init__.py` (empty) |
| 3 | C | — | `identity/credentials.py`, `access/admin.py`, `access/__init__.py` | `tests/identity/test_bearer_door.py`, `tests/identity/test_token_service.py`, `tests/access/test_admin_service_accounts.py`, `tests/access/test_disable_revokes_tokens.py` |
| 4 | C | — | `identity/oauth.py` | `tests/identity/oauth_helpers.py`, `tests/identity/test_oauth_redirects.py`, `tests/identity/test_oauth_service.py`, `tests/identity/test_oauth_refresh.py`, `tests/test_mcp_auth_postgres.py` |
| 5 | D | `mcp/auth.py`, `mcp/oauth_provider.py`, `mcp/oauth_routes.py` | — | `tests/mcp/oauth_client.py`, `tests/mcp/test_auth_verifier.py`, `tests/mcp/test_oauth_provider.py`, `tests/mcp/test_oauth_routes.py`, `tests/mcp/test_oauth_flow.py` |
| 7 | D | `mcp/ratelimit.py` | — | `tests/mcp/test_ratelimit.py` |
| 8 | D | `mcp/router.py`, `mcp/schemas.py`, `mcp/dependencies.py` | — | `tests/mcp/api_helpers.py`, `tests/mcp/test_tokens_api.py`, `tests/mcp/test_connected_apps_api.py`, `tests/mcp/test_consent_api.py`, `tests/mcp/test_admin_credentials_api.py`, `tests/mcp/test_auth_methods.py` |
| 9 | D | `mcp/cli.py` | — | `tests/mcp/test_cli.py` |
| 10 | D | `frontend/src/features/oauth-consent/{index.ts,consent-page.tsx,consent-api.ts,use-consent.ts,consent-page.test.tsx,use-consent.test.tsx}` | `frontend/src/App.tsx`, `frontend/vite.config.ts`, `DESIGN.md` | (in the feature folder) |
| 6 | — | — | `mcp/server.py`, `mcp/__init__.py`, `mcp/oauth_routes.py`, `mcp/router.py`, `main.py`, `config.py`, `identity/service.py`, `identity/__init__.py`, `pyproject.toml` | `tests/mcp/mcp_rpc.py`, `tests/mcp/test_server.py`, `tests/mcp/test_mcp_e2e.py`, `tests/mcp/test_rate_limited_routes.py`; delete `tests/test_mcp_access.py`; modify `tests/test_startup.py`, `tests/identity/test_service_users.py`, `tests/test_config.py` |
| 11 | — | — | `frontend/nginx.conf`, `backend/.env.example`, `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `docs/specs/2026-10-08-auth-rbac-design.md` | `tests/test_deploy_config.py` |
| 12 | — | `backend/scripts/mcp_oauth_smoke.py` | fixes found by verification (any file, serially) | — |

Verified disjointness: group C = {credentials, access/admin, access/__init__, 4 test files} ∩
{oauth, 5 test files} = ∅ (both only *read* `api_tokens.py`, finished in Task 1).
Group D: Task 5 {auth, oauth_provider, oauth_routes,
tests/mcp/{oauth_client,test_auth_verifier,test_oauth_provider,test_oauth_routes,test_oauth_flow}},
Task 7 {ratelimit, test_ratelimit}, Task 8 {router, schemas, dependencies, 6 test files}, Task 9
{cli, test_cli}, Task 10 {frontend files, `DESIGN.md`} — pairwise disjoint. `tests/mcp/__init__.py` is created
by Task 2 so no group-D task creates it. No group-D task adds a `tests/mcp/conftest.py`; each keeps
its fixtures in its own helper module.

## Conventions every task follows

- **Security invariants (assert them in tests, not just in code):**
  1. Only `hash_secret(raw)` is persisted; raw tokens, codes, txn ids and client secrets never go
     into a DB column, `credential_events.details`, `atlas_audit_log`, a log event, an exception
     message, an HTTP error body or a `repr`.
  2. Every identity rejection says only "invalid token" / `invalid_grant`; the reason goes to a
     structured log field (`reason="revoked"`) with at most the display prefix.
  3. Every credential write that changes state commits together with its `credential_events` row.
  4. Fail closed: an exception in the bearer door, the policy lookup or a tool collapses to 401
     (bearer), an empty `tools/list`, or the "unavailable" tool result.
  5. Never `logger.exception(...)` in a frame that holds a raw secret: in development structlog
     renders tracebacks with `rich` and `show_locals=True`, which would print it. Log
     `error=type(exc).__name__` with `logger.error` instead.
- **Clock:** identity services take `clock: Callable[[], datetime] = _utcnow`; SDK paths use
  `time.time()` (C14), so expiry tests age rows in the database.
- **Test helpers:** `tests/identity/credential_helpers.py` (Task 2) and
  `tests/identity/oauth_helpers.py` (Task 4) are the only shared helpers for identity;
  `tests/mcp/oauth_client.py` (Task 5) and `tests/mcp/api_helpers.py` (Task 8) for MCP. Reuse
  `tests/access_helpers.py` (`make_user`, `add_grant`) as is.
- **Leak assertion helper** (`credential_helpers.assert_no_secret(secret, *haystacks)`): checks
  that neither the full secret nor `secret[14:30]` (16 chars past the display prefix, which may be
  shown) occurs in any haystack (strings are searched as is; other objects are `json.dumps(...,
  default=str)` first).

---

### Task 1: Settings, token kinds and credential carriers

**Group A. Depends on:** nothing.

**Files:**
- Create: `backend/app/identity/api_tokens.py` (constants and the five pure functions)
- Modify: `backend/app/config.py`, `backend/app/identity/principal.py`, `backend/app/atlas/policy.py`,
  `backend/app/mcp/server.py` (one pragma line), `backend/pyproject.toml`
- Test: create `backend/tests/identity/test_api_tokens.py`; modify `backend/tests/test_config.py`,
  `backend/tests/identity/test_types.py`

**Interfaces**

```python
# app/config.py (added to Settings; atlas_mcp_token / mcp_service_email stay until Task 6)
atlas_public_url: str = "http://localhost:8080"
oauth_hosted_redirect_uris: str = "https://claude.ai/api/mcp/auth_callback"  # comma-separated
pat_default_days: int = 90
pat_max_days: int = 365

@property
def mcp_issuer_url(self) -> str: ...        # f"{atlas_public_url}/mcp-server"
@property
def mcp_resource_url(self) -> str: ...      # f"{atlas_public_url}/mcp-server/mcp"
@property
def oauth_consent_url(self) -> str: ...     # f"{atlas_public_url}/oauth/consent"
@property
def hosted_redirect_uri_list(self) -> list[str]: ...
@property
def hosted_connectors_enabled(self) -> bool: ...  # scheme == "https"
```

```python
# app/identity/principal.py — appended, defaulted (existing constructions keep working)
token_id: UUID | None = None
client_id: str | None = None

# app/atlas/policy.py — AtlasCaller, appended after session_id
token_id: UUID | None = None
client_id: str | None = None
```

```python
# app/identity/api_tokens.py — pure: no I/O, no models
class TokenKind(StrEnum):
    PAT = "pat"
    SERVICE = "service"
    OAUTH_ACCESS = "oauth_access"
    OAUTH_REFRESH = "oauth_refresh"

TOKEN_PREFIXES: Final[Mapping[TokenKind, str]]   # atl_pat_, atl_svc_, atl_oat_, atl_ort_
BEARER_KINDS: Final = frozenset({TokenKind.PAT, TokenKind.SERVICE, TokenKind.OAUTH_ACCESS})
# (no AuthMethod mapping here: `principal` is a sibling layer; credentials.py maps kinds to methods)
SECRET_BYTES: Final = 32                 # 256-bit; token_urlsafe(32) is 43 chars
DISPLAY_PREFIX_LENGTH: Final = 14
ACCESS_TOKEN_TTL: Final = timedelta(hours=1)
REFRESH_TOKEN_TTL: Final = timedelta(days=30)
CODE_TTL: Final = timedelta(seconds=60)
AUTHORIZATION_REQUEST_TTL: Final = timedelta(minutes=10)
REFRESH_REUSE_GRACE: Final = timedelta(seconds=30)
LAST_USED_INTERVAL: Final = timedelta(minutes=5)
CLIENT_IDLE_GC: Final = timedelta(days=90)
MAX_LIVE_PATS: Final = 10
MAX_TOKEN_DAYS: Final = 365
# revoked_reason values (varchar 32)
REVOKED_ROTATED, REVOKED_BY_USER, REVOKED_BY_ADMIN, REVOKED_USER_DISABLED, REVOKED_CLIENT,
REVOKED_APP_DISCONNECTED, REVOKED_CODE_REUSE, REVOKED_REFRESH_REUSE, REVOKED_CROSS_CLIENT,
REVOKED_AUDIENCE_CHANGED, REVOKED_NO_MCP_USE, REVOKED_OAUTH_REVOKE  # "rotated", "user_revoked", …
# credential_events.event values (varchar 48)
EVENT_TOKEN_CREATED = "token.created"; EVENT_TOKEN_REVOKED = "token.revoked"
EVENT_TOKENS_REVOKED_ALL = "tokens.revoked_all"; EVENT_CLIENT_REGISTERED = "client.registered"
EVENT_CLIENT_REVOKED = "client.revoked"; EVENT_CONSENT_APPROVED = "consent.approved"
EVENT_CONSENT_DENIED = "consent.denied"; EVENT_TOKENS_ISSUED = "oauth.tokens_issued"
EVENT_REFRESHED = "oauth.refreshed"; EVENT_REFRESH_GRACE = "oauth.refresh_grace"
EVENT_REUSE_DETECTED = "oauth.reuse_detected"; EVENT_FAMILY_REVOKED = "oauth.family_revoked"
EVENT_GC = "credentials.gc"

CredentialVia = Literal["api", "cli", "oauth", "system"]

@dataclass(frozen=True, slots=True)
class CredentialActor:
    """Who changed a credential, as recorded in credential_events."""
    user_id: UUID | None
    via: CredentialVia

_SECRET_BODY: Final = re.compile(r"[A-Za-z0-9_-]{43}")

def mint(kind: TokenKind) -> str:
    return TOKEN_PREFIXES[kind] + secrets.token_urlsafe(SECRET_BYTES)

def mint_secret() -> str:                      # codes and txn ids (no prefix)
    return secrets.token_urlsafe(SECRET_BYTES)

def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def kind_of(raw: str) -> TokenKind | None:
    """The kind a raw bearer claims, or None. Checked before any database lookup (D3)."""
    for kind, prefix in TOKEN_PREFIXES.items():
        if raw.startswith(prefix) and _SECRET_BODY.fullmatch(raw[len(prefix):]):
            return kind
    return None

def display_prefix(raw: str) -> str:          # shown in UIs and logs; never enough to use
    return raw[:DISPLAY_PREFIX_LENGTH] if kind_of(raw) else raw[:6]
```

**Behaviour.** `atlas_public_url` is normalised by a `field_validator` (strip, drop one trailing
`/`). The model validator rejects: a scheme other than `http`/`https`; any path, query, fragment or
userinfo; `http` with a host other than `localhost` or `127.0.0.1` (mirrors the SDK's
`validate_issuer_url`, C14), in every environment. It also rejects `pat_default_days` outside
`1..pat_max_days` and `pat_max_days` outside `1..365`, and any hosted redirect URI that is not
`https`.

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/test_config.py` (append):
    - `test_public_url_defaults_to_the_tunnel` — default is `http://localhost:8080`; issuer
      `…/mcp-server`, resource `…/mcp-server/mcp`, consent `…/oauth/consent`.
    - `test_public_url_trailing_slash_is_dropped` — `http://localhost:8080/` → no double slash.
    - `test_public_url_http_only_for_loopback` (parametrized) — `http://atlas.example.com`,
      `http://10.0.0.5:8080`, `http://[::1]:8080` raise; `http://127.0.0.1:8080` and
      `https://atlas.example.com` pass.
    - `test_public_url_rejects_path_query_fragment_userinfo` (parametrized).
    - `test_hosted_connectors_only_with_https` — false for localhost, true for https.
    - `test_hosted_redirects_must_be_https` and `test_hosted_redirect_list_splits_and_strips`.
    - `test_pat_day_bounds` (parametrized: default 0, default > max, max 366 raise).
  - `tests/identity/test_types.py` (append): `test_principal_credential_ids_default_to_none` and
    `test_atlas_caller_credential_ids_default_to_none`.
  - `tests/identity/test_api_tokens.py`: `test_every_kind_has_a_distinct_prefix`,
    `test_prefixes_fit_the_display_prefix` (each prefix shorter than 14),
    `test_refresh_tokens_are_never_bearers` (`OAUTH_REFRESH not in BEARER_KINDS`),
    `test_reason_and_event_names_fit_their_columns` (≤ 32 / ≤ 48 chars),
    `test_mint_has_prefix_and_256_bits` (43-char urlsafe body), `test_mint_is_unique` (1 000
    draws), `test_hash_is_sha256_hex`, `test_kind_of_accepts_only_well_formed_tokens`
    (parametrized: each prefix ✓; `atl_xyz_…`, 42- and 44-char bodies, `+`, `/`, `=`, empty,
    `Bearer atl_pat_…`, a Firebase JWT → None), `test_display_prefix_never_reveals_the_body`.
- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_config.py
  tests/identity/test_types.py tests/identity/test_api_tokens.py -q` → `AttributeError` /
  `ModuleNotFoundError`.
- [ ] **Step 3: Implement** the settings, the carriers and `api_tokens.py`.
- [ ] **Step 4: `pyproject.toml`**
  - Identity layering: bottom layer becomes `"principal | tokens | errors | api_tokens"`.
  - `[tool.pyright].strict` gains `"app/mcp"`.
  - `[tool.coverage.run].omit = ["migrations/*"]` (drop `app/mcp/*`).
  - Add `# pyright: basic` as the first line of `app/mcp/server.py` with a comment
    `# strict after the Task 6 rewrite` (today it has 14 strict errors, all bare `-> dict`
    returns). Task 6 removes the pragma. New files in `app/mcp` are strict from their first commit.
- [ ] **Step 5: Run the gate.** Expect all green; coverage still ≥ 80 % (`app/mcp/server.py` is
  mostly covered by `tests/test_mcp_access.py`).
- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/identity/principal.py backend/app/identity/api_tokens.py \
  backend/app/atlas/policy.py backend/app/mcp/server.py backend/pyproject.toml \
  backend/tests/test_config.py backend/tests/identity/test_types.py \
  backend/tests/identity/test_api_tokens.py
git commit -m "feat(identity): MCP auth settings, token kinds and credential carriers"
```

---

### Task 2: Credential tables, migration 0005, repository and interface skeletons

**Group B. Depends on:** Task 1.

**Files:**
- Create: `backend/migrations/versions/0005_mcp_auth.py`, `backend/app/identity/credentials.py`
  (skeleton), `backend/app/identity/oauth.py` (skeleton)
- Modify: `backend/app/identity/models.py`, `backend/app/identity/repository.py`,
  `backend/app/identity/errors.py`, `backend/app/identity/__init__.py`,
  `backend/app/models/audit.py`, `backend/app/atlas/tools.py` (`_audit` only),
  `backend/pyproject.toml`
- Test: `backend/tests/test_alembic_mcp_auth.py`, `backend/tests/identity/test_credential_repository.py`,
  `backend/tests/identity/credential_helpers.py`, `backend/tests/test_audit_credentials.py`,
  `backend/tests/mcp/__init__.py` (empty; the group-D tasks put their tests in `tests/mcp/`)

**Models** (`app/identity/models.py`, appended after `User`; every datetime is
`sa_type=TIMESTAMP(timezone=True)`):

```python
class OAuthClient(SQLModel, table=True):
    __tablename__ = "oauth_clients"
    client_id: str = Field(primary_key=True, max_length=255)
    client_name: str | None = Field(default=None, max_length=100)
    redirect_uris: list[str] = Field(sa_column=Column(JSON, nullable=False))
    token_endpoint_auth_method: str = Field(max_length=32)   # none | client_secret_post | client_secret_basic
    client_secret_hash: str | None = Field(default=None, max_length=64)
    grant_types: list[str] = Field(sa_column=Column(JSON, nullable=False))
    response_types: list[str] = Field(sa_column=Column(JSON, nullable=False))
    software_id: str | None = Field(default=None, max_length=200)
    registered_at: datetime = Field(default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True))
    last_used_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    revoked_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))


class ApiToken(SQLModel, table=True):
    __tablename__ = "api_tokens"
    __table_args__ = (
        Index("ix_api_tokens_user_id_kind", "user_id", "kind"),
        CheckConstraint(
            "kind IN ('pat', 'service', 'oauth_access', 'oauth_refresh')",
            name="ck_api_tokens_kind",
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    kind: str = Field(max_length=16)
    token_hash: str = Field(max_length=64, unique=True, index=True)
    prefix: str = Field(max_length=16)
    name: str = Field(default="", max_length=100)
    client_id: str | None = Field(default=None, foreign_key="oauth_clients.client_id",
                                  index=True, max_length=255)
    family_id: UUID | None = Field(default=None, index=True)
    audience: str | None = Field(default=None, max_length=500)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True))
    expires_at: datetime = Field(sa_type=TIMESTAMP(timezone=True))
    last_used_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    revoked_at: datetime | None = Field(default=None, sa_type=TIMESTAMP(timezone=True))
    revoked_reason: str | None = Field(default=None, max_length=32)


class OAuthAuthorizationRequest(SQLModel, table=True):
    __tablename__ = "oauth_authorization_requests"
    id: str = Field(primary_key=True, max_length=64)            # hash_secret(txn), D36
    client_id: str = Field(foreign_key="oauth_clients.client_id", index=True, max_length=255)
    redirect_uri: str = Field(max_length=2000)
    redirect_uri_provided_explicitly: bool
    code_challenge: str = Field(max_length=128)
    state: str | None = Field(default=None, max_length=500)
    scopes: list[str] = Field(sa_column=Column(JSON, nullable=False))
    resource: str = Field(max_length=500)                       # bound audience (D7)
    created_at: datetime = …; expires_at: datetime = …; consumed_at: datetime | None = …


class OAuthCode(SQLModel, table=True):
    __tablename__ = "oauth_codes"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code_hash: str = Field(max_length=64, unique=True, index=True)
    client_id: str = Field(foreign_key="oauth_clients.client_id", index=True, max_length=255)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    family_id: UUID
    code_challenge: str = Field(max_length=128)
    redirect_uri: str = Field(max_length=2000)
    redirect_uri_provided_explicitly: bool
    resource: str = Field(max_length=500)
    scopes: list[str] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = …; expires_at: datetime = …; used_at: datetime | None = …


class CredentialEvent(SQLModel, table=True):
    """Append-only (D15). token_id/client_id are plain columns: the log outlives GC'd rows."""
    __tablename__ = "credential_events"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    at: datetime = Field(default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True), index=True)
    event: str = Field(max_length=48)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    actor_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    via: str = Field(max_length=16)
    token_id: UUID | None = None
    client_id: str | None = Field(default=None, max_length=255)
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
```

`app/models/audit.py` — appended **after `created_at`**:

```python
    token_id: UUID | None = None                         # credential that ran the call (D12)
    client_id: str | None = Field(default=None, max_length=255)
```

`app/atlas/tools.py` `_audit` — two arguments appended after `deny_reason=…`:
`token_id=self.caller.token_id, client_id=self.caller.client_id`. Nothing else in `tools.py`.

**Migration `0005_mcp_auth.py`** (mirror the models exactly; the SQLite and PG drift tests compare
them):

```python
revision = "0005"
down_revision = "0003"  # chain: set to predecessor at integration
TS = sa.TIMESTAMP(timezone=True)
SHARED_MCP_EMAIL = "mcp-shared@atlas.internal"

def upgrade() -> None:
    _create_clients(); _create_tokens(); _create_requests_and_codes(); _create_events()
    with op.batch_alter_table("atlas_audit_log") as batch:      # APPEND (D25)
        batch.add_column(sa.Column("token_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("client_id", sa.String(255), nullable=True))
    _retire_shared_mcp_user()

def _retire_shared_mcp_user() -> None:
    """D17 + C13: disable the shared identity, audited and versioned like any status change."""
    conn = op.get_bind()
    row = conn.execute(sa.select(_users.c.id).where(_users.c.email == SHARED_MCP_EMAIL)
                       .where(_users.c.status == "active")).first()
    if row is None:
        return
    now = datetime.now(UTC)
    conn.execute(_users.update().where(_users.c.id == row.id).values(status="disabled"))
    conn.execute(_rbac_changes.insert().values(
        id=uuid4(), actor_user_id=None, via="migration", tenant="ygg", action="user.status",
        object_type="user", object_id=str(row.id), before={"status": "active"},
        after={"status": "disabled"}, at=now))
    conn.execute(_policy_state.update().where(_policy_state.c.id == 1).values(
        policy_version=_policy_state.c.policy_version + 1, updated_at=now))

def downgrade() -> None:
    # re-enable the shared user (same audit + bump), drop the two audit columns, then the tables
    # in FK order: credential_events, oauth_codes, oauth_authorization_requests, api_tokens,
    # oauth_clients.
```

Indexes created by name exactly as SQLModel names them (`ix_api_tokens_token_hash` unique,
`ix_api_tokens_user_id`, `ix_api_tokens_client_id`, `ix_api_tokens_family_id`,
`ix_api_tokens_user_id_kind`, `ix_oauth_codes_code_hash` unique, `ix_oauth_codes_client_id`,
`ix_oauth_codes_user_id`, `ix_oauth_authorization_requests_client_id`, `ix_credential_events_at`,
`ix_credential_events_user_id`).

**Repository** (`app/identity/repository.py`, new class `CredentialRepository(db)`; reads return
rows, writes are staged; the calling service commits once):

```python
class CredentialRepository:
    def add(self, row: SQLModel) -> None
    async def commit(self) -> None
    async def rollback(self) -> None
    # tokens
    async def token(self, token_id: UUID, *, fresh: bool = False) -> ApiToken | None
    async def token_by_hash(self, token_hash: str) -> ApiToken | None
    async def list_tokens(self, *, tenant: str, kinds: Collection[str], user_id: UUID | None = None,
                          include_revoked: bool = False, limit: int = 200) -> list[ApiToken]
    async def count_live(self, user_id: UUID, kind: str, now: datetime) -> int
    async def revoke_token(self, token_id: UUID, reason: str, now: datetime) -> bool
    async def mark_rotated(self, token_id: UUID, now: datetime) -> bool
    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int
    async def revoke_user_tokens(self, user_id: UUID, reason: str, now: datetime) -> int
    async def revoke_client_tokens(self, client_id: str, reason: str, now: datetime) -> int
    async def family_has_live_token(self, family_id: UUID, now: datetime) -> bool
    async def touch_token(self, token_id: UUID, now: datetime) -> None
    async def connected_apps(self, user_id: UUID, now: datetime) -> list[ConnectedAppRow]
    async def live_family_counts(self) -> dict[str, int]          # client_id -> live families
    # clients
    async def client(self, client_id: str) -> OAuthClient | None
    async def list_clients(self, limit: int = 200) -> list[OAuthClient]
    async def revoke_client(self, client_id: str, now: datetime) -> bool
    async def touch_client(self, client_id: str, now: datetime) -> None
    # authorization requests and codes
    async def pending_request(self, request_hash: str, now: datetime) -> OAuthAuthorizationRequest | None
    async def consume_request(self, request_hash: str, now: datetime) -> OAuthAuthorizationRequest | None
    async def code_by_hash(self, code_hash: str) -> OAuthCode | None
    async def code(self, code_id: UUID, *, fresh: bool = False) -> OAuthCode | None
    async def mark_code_used(self, code_id: UUID, now: datetime) -> bool
    # events and GC
    async def list_events(self, *, tenant: str, user_id: UUID | None = None, limit: int = 100) -> list[CredentialEvent]
    async def delete_stale(self, now: datetime) -> GcCounts
```

Every "only once" write is one conditional `UPDATE` whose `rowcount` decides (the access repository
already uses `cast(CursorResult[Any], result).rowcount`):

```python
async def mark_code_used(self, code_id: UUID, now: datetime) -> bool:
    """Single use (D5): exactly one caller ever sees True, on SQLite and on PG READ COMMITTED
    (the loser's UPDATE waits for the winner's row lock, re-checks used_at, matches 0 rows)."""
    result = await self._db.execute(
        update(OAuthCode)
        .where(col(OAuthCode.id) == code_id, col(OAuthCode.used_at).is_(None),
               col(OAuthCode.expires_at) > now)
        .values(used_at=now)
    )
    return cast(CursorResult[Any], result).rowcount == 1

async def mark_rotated(self, token_id: UUID, now: datetime) -> bool:
    result = await self._db.execute(
        update(ApiToken)
        .where(col(ApiToken.id) == token_id, col(ApiToken.revoked_at).is_(None))
        .values(revoked_at=now, revoked_reason=REVOKED_ROTATED)
    )
    return cast(CursorResult[Any], result).rowcount == 1

async def consume_request(self, request_hash: str, now: datetime) -> OAuthAuthorizationRequest | None:
    result = await self._db.execute(
        update(OAuthAuthorizationRequest)
        .where(col(OAuthAuthorizationRequest.id) == request_hash,
               col(OAuthAuthorizationRequest.consumed_at).is_(None),
               col(OAuthAuthorizationRequest.expires_at) > now)
        .values(consumed_at=now)
    )
    if cast(CursorResult[Any], result).rowcount != 1:
        return None
    return await self._db.get(OAuthAuthorizationRequest, request_hash, populate_existing=True)
```

`revoke_family`, `revoke_user_tokens` and `revoke_client_tokens` are one `UPDATE … SET revoked_at,
revoked_reason WHERE <key> AND revoked_at IS NULL` each (they never overwrite an earlier reason, so
`rotated` survives a family revoke; D6's grace therefore also requires `family_has_live_token`).
`list_tokens` and `list_events` join `users` and filter by `tenant`. `delete_stale` removes codes
and authorization requests older than one day, OAuth token rows expired or revoked more than 30 days
ago, then clients that are revoked or idle (`coalesce(last_used_at, registered_at)` older than 90
days) and have no remaining token rows. PAT and service rows are never deleted.

**Errors** (`app/identity/errors.py`, appended): `CredentialRuleError` (400: bad name, days out of
range, wrong user kind), `CredentialLimitError` (409: too many live PATs),
`CredentialNotFoundError` (404: no such token/family/service account, or not yours).

**Skeletons (D35).** `credentials.py` and `oauth.py` contain the full public surface of Tasks 3 and
4 — every dataclass, error class, constant and method signature with its docstring — with bodies
`raise NotImplementedError`. The exact signatures are in Task 3 and Task 4 below; copy them
verbatim. `identity/__init__.py` exports all of them plus the models and `TokenKind`,
`TOKEN_PREFIXES`, `CredentialActor`, `InvalidTokenError` (from `tokens.py`). The identity layering
contract gains the middle layer (above `"service | firebase"`, below `"dependencies | bootstrap"`):

```toml
layers = [
    "router",
    "dependencies | bootstrap",
    "credentials | oauth",
    "service | firebase",
    "repository",
    "models",
    "schemas",
    "principal | tokens | errors | api_tokens",
]
```

(`credentials` imports `service.to_principal`; `credentials` and `oauth` never import each other.)

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/test_alembic_mcp_auth.py` (SQLite; reuse `_config`/`_tables` patterns from
    `tests/test_alembic.py` by copying the two tiny helpers, do not edit that file):
    - `test_0005_creates_credential_tables` — the five tables exist at head.
    - `test_0005_appends_audit_credential_columns` — `token_id`, `client_id` are the last two
      columns of `atlas_audit_log`.
    - `test_0005_disables_the_shared_mcp_user_and_bumps_the_version` — seed an active
      `mcp-shared@atlas.internal` at `0003`, upgrade: status `disabled`, one `rbac_changes` row
      `via="migration"`, `policy_version` + 1.
    - `test_0005_without_the_shared_user_is_a_no_op` — no rbac row, no bump.
    - `test_0005_round_trips` — `upgrade head → downgrade 0003 → upgrade head`.
    - `test_0005_down_revision_is_marked_for_the_chain` — the source line contains
      `down_revision = "0003"  # chain: set to predecessor at integration`.
    - The existing `test_head_matches_model_columns` and the PG drift test cover model ≡ migration.
  - `tests/identity/test_credential_repository.py`:
    - `test_token_hash_is_unique` (IntegrityError on a duplicate hash).
    - `test_mark_code_used_succeeds_once` and `test_mark_code_used_refuses_an_expired_code`.
    - `test_mark_rotated_succeeds_once`.
    - `test_consume_request_succeeds_once_and_never_after_expiry`.
    - `test_revoke_family_keeps_earlier_reasons` (`rotated` stays `rotated`).
    - `test_family_has_live_token`.
    - `test_list_tokens_is_tenant_scoped`.
    - `test_delete_stale_removes_only_dead_oauth_rows` (PAT rows and live families survive).
  - `tests/test_audit_credentials.py`:
    `test_audit_rows_carry_the_callers_token_and_client` — `AtlasTools(AtlasCaller(…,
    token_id=t, client_id="c"), policy, db).execute("list_metrics", {})` writes both values.
  - `tests/identity/credential_helpers.py` (helpers, not tests): `make_client(db, *,
    redirect_uris=…, secret_hash=None, revoked=False)`, `insert_token(db, user, kind, *,
    expires_in, family_id=None, client_id=None, revoked_reason=None) -> tuple[ApiToken, str]`
    (returns the raw value it hashed), `assert_no_secret(secret, *haystacks)`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** models, audit columns, `_audit`, migration, repository, errors,
  skeletons, exports, the layering change. Create the empty `tests/mcp/__init__.py`.
- [ ] **Step 4: Run the gate.** `lint-imports` must pass with the new layer; pyright strict must
  pass on the skeletons.
- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/models.py backend/app/identity/repository.py \
  backend/app/identity/errors.py backend/app/identity/credentials.py backend/app/identity/oauth.py \
  backend/app/identity/__init__.py backend/app/models/audit.py backend/app/atlas/tools.py \
  backend/migrations/versions/0005_mcp_auth.py backend/pyproject.toml \
  backend/tests/test_alembic_mcp_auth.py backend/tests/identity/test_credential_repository.py \
  backend/tests/identity/credential_helpers.py backend/tests/test_audit_credentials.py \
  backend/tests/mcp/__init__.py
git commit -m "feat(identity): credential tables, migration 0005 and interface skeletons"
```

---

### Task 3: Personal and service tokens, the bearer door, access hooks

**Group C (parallel with Task 4). Depends on:** Task 2.

**Files:**
- Modify: `backend/app/identity/credentials.py` (bodies), `backend/app/access/admin.py` (one method + one statement + imports, C5),
  `backend/app/access/__init__.py` (exports)
- Test: `backend/tests/identity/test_bearer_door.py`, `backend/tests/identity/test_token_service.py`, `backend/tests/access/test_admin_service_accounts.py`,
  `backend/tests/access/test_disable_revokes_tokens.py`

**Interfaces**

```python
# app/identity/credentials.py
@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: ApiToken
    raw: str = field(repr=False)      # shown once (D3); never logged or stored

@dataclass(frozen=True, slots=True)
class AuthenticatedBearer:
    principal: Principal              # auth_method oauth|pat|service, token_id, client_id set
    expires_at: datetime
    audience: str | None              # OAuth: bound audience; PAT/service: None (verifier uses current)
    display_prefix: str

@dataclass(frozen=True, slots=True)
class ConnectedApp:
    family_id: UUID; client_id: str; client_name: str | None; redirect_host: str
    created_at: datetime; last_used_at: datetime | None; expires_at: datetime

async def authenticate_bearer(db: AsyncSession, raw: str, now: datetime | None = None) -> AuthenticatedBearer
    """Raises InvalidTokenError (unknown/expired/revoked/wrong kind/refresh token/revoked client)
    or ForbiddenError (user disabled). Never includes token material in the message."""

async def principal_for_user(db: AsyncSession, user_id: UUID) -> Principal | None
    """Active users only; auth_method 'service' for service accounts, 'pat' otherwise.
    Used by the MCP edge to evaluate a user's Policy (eligibility, D34)."""

async def revoke_user_tokens(user_id: UUID, *, reason: str, actor_user_id: UUID | None,
                             via: CredentialVia) -> None
    """Post-commit hook for AccessAdmin.update_user (D18, C5): opens its own session from
    get_session_factory(), revokes every token of every kind, writes tokens.revoked_all, and never
    raises (logs identity.revoke_all_failed). The bearer door refuses disabled users regardless."""

class TokenService:
    def __init__(self, db: AsyncSession, clock: Callable[[], datetime] = _utcnow) -> None
    async def create_pat(self, user_id: UUID, *, name: str, expires_in_days: int | None,
                         actor: CredentialActor, default_days: int, max_days: int) -> IssuedToken
    async def create_service_token(self, service_user_id: UUID, *, name: str,
                                   expires_in_days: int | None, actor: CredentialActor,
                                   default_days: int, max_days: int) -> IssuedToken
    async def list_tokens(self, *, tenant: str, user_id: UUID | None = None,
                          kinds: Collection[TokenKind] = (TokenKind.PAT, TokenKind.SERVICE),
                          include_revoked: bool = False) -> list[ApiToken]
    async def revoke_token(self, token_id: UUID, *, reason: str, actor: CredentialActor,
                           owner_id: UUID | None = None, tenant: str | None = None) -> None
    async def revoke_all_tokens(self, user_id: UUID, *, reason: str, actor: CredentialActor) -> int
    async def list_connected_apps(self, user_id: UUID) -> list[ConnectedApp]
    async def revoke_family(self, family_id: UUID, *, reason: str, actor: CredentialActor,
                            owner_id: UUID | None = None) -> None
    async def list_events(self, *, tenant: str, user_id: UUID | None = None,
                          limit: int = 100) -> list[CredentialEvent]
```

**Behaviour**
- `create_pat`: user exists, active, `kind=human`, else `CredentialRuleError`; name stripped,
  1–100 chars; days default `default_days`, allowed `1..max_days`; `count_live(PAT) >=
  MAX_LIVE_PATS` → `CredentialLimitError`. Stores hash + display prefix + `created_by=actor.user_id`,
  writes `token.created` (`details={"kind","name","prefix","via"}`) in the same commit.
- `create_service_token`: target `kind=service` and active; same day rules; no live cap.
- `revoke_token`: with `owner_id`, a token of another user is `CredentialNotFoundError` (no
  existence probing); with `tenant`, a token of another tenant is not found; an already revoked
  token is a no-op (idempotent 204). Writes `token.revoked`.
- `revoke_family`: same owner rule; revokes every live row of the family (`app_disconnected`),
  writes `oauth.family_revoked`.
- `revoke_all_tokens`: all kinds, one `tokens.revoked_all` event with `details={"count", "reason"}`.
- `list_connected_apps`: one entry per family with a live refresh token.

**Security-critical code**

```python
async def authenticate_bearer(
    db: AsyncSession, raw: str, now: datetime | None = None
) -> AuthenticatedBearer:
    moment = now or _utcnow()
    candidate = raw.strip()
    kind = kind_of(candidate)                      # rejected before any DB work (D3)
    if kind is None or kind not in BEARER_KINDS:  # refresh tokens are never bearers
        raise InvalidTokenError(_INVALID)
    creds = CredentialRepository(db)
    row = await creds.token_by_hash(hash_secret(candidate))
    if (
        row is None
        or row.kind != kind
        or row.revoked_at is not None
        or as_utc(row.expires_at) <= moment
    ):
        raise InvalidTokenError(_INVALID)
    user = await UserRepository(db).get(row.user_id)
    _require_active_owner(user, kind)              # ForbiddenError / InvalidTokenError
    if kind is TokenKind.OAUTH_ACCESS:
        await _require_live_client(creds, row)     # revoked or missing client -> InvalidTokenError
    await _touch(creds, row, moment)               # last_used_at, at most every 5 min
    principal = replace(
        to_principal(user, _AUTH_METHOD[kind]),   # {PAT: "pat", SERVICE: "service", OAUTH_ACCESS: "oauth"}
        token_id=row.id,
        client_id=row.client_id,
    )
    return AuthenticatedBearer(principal, as_utc(row.expires_at), row.audience, row.prefix)
```

`_require_active_owner`: `None` → `InvalidTokenError`; `status != active` → `ForbiddenError`;
`SERVICE` tokens need `kind=service`, `PAT` and `OAUTH_ACCESS` need `kind=human` (else
`InvalidTokenError`). `_INVALID = "invalid token"` is the only message.

**Access hooks (C5, C6).** `access/admin.py`:

```python
# existing import line, extended:
from app.identity import TokenVerifier, User, UserKind, UserStatus, revoke_user_tokens
# + `import re` with the stdlib imports

# in update_user, the one appended statement inside the existing DISABLED branch:
        if after.get("status") == UserStatus.DISABLED:
            await self._end_firebase_sessions(user)
            await revoke_user_tokens(
                user.id, reason="user_disabled", actor_user_id=actor.user_id, via=actor.via
            )

# the one new method, at the end of AccessAdmin (after the helpers):
    async def create_service_account(self, actor: Actor, name: str, role: str) -> User:
        """D13: a service identity owned by the actor; audited and versioned."""
        actor.require(ADMIN_USERS)
        if role not in ROLES:
            msg = f"Unknown role '{role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _check_role_escalation(actor, role)
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        if not 3 <= len(slug) <= 40:
            msg = "Use 3-40 letters, digits or dashes for the service account name."
            raise InvalidChangeError(msg)
        email = f"svc-{slug}@atlas.internal"
        async with self._write(actor):
            if await self._repo.user_by_email(email) is not None:
                msg = f"A service account named '{slug}' already exists."
                raise ConflictError(msg)
            user = User(email=email, display_name=name.strip(), kind=UserKind.SERVICE,
                        role=role, owner_user_id=actor.user_id, tenant=actor.tenant)
            self._repo.add(user)
            await self._commit(
                _change(actor, "service_account.create", ("user", user.id), None, _snapshot(user))
            )
        return user
```

`access/__init__.py` adds exactly: `AccessAdmin`, `Actor`, `get_access_admin`, `get_actor`,
`TOKENS_CREATE`, `ADMIN_TOKENS`, `ADMIN_CLIENTS` (phase 5 adds the same four admin lines; identical
text keeps the rebase clean).

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/identity/test_bearer_door.py`:
    - `test_pat_authenticates_as_pat` (principal auth_method `pat`, token_id set, client_id None,
      audience None).
    - `test_service_token_requires_a_service_user` / `test_pat_refuses_a_service_user`.
    - `test_oauth_access_token_carries_client_and_audience`.
    - `test_refresh_token_is_never_a_bearer`.
    - `test_unknown_prefix_is_rejected_without_a_query` (patch `CredentialRepository.token_by_hash`
      to fail the test if called).
    - `test_expired_token_is_rejected`, `test_revoked_token_is_rejected`,
      `test_kind_mismatch_is_rejected` (a PAT hash stored with kind `service`).
    - `test_disabled_user_is_forbidden`.
    - `test_revoked_client_kills_its_access_tokens`.
    - `test_last_used_is_written_at_most_every_five_minutes`.
    - `test_whitespace_around_the_token_is_ignored`.
    - `test_rejections_never_echo_the_token` — every raised message equals `"invalid token"` or the
      disabled-user text; `assert_no_secret(raw, str(exc), captured_logs)`.
  - `tests/identity/test_token_service.py`:
    - `test_create_pat_stores_only_the_hash` (DB row has hash + prefix; raw not in any column;
      `repr(issued)` lacks the raw value; `credential_events.details` lacks it).
    - `test_create_pat_defaults_to_90_days_and_caps_at_365`, `test_pat_days_out_of_range`.
    - `test_eleventh_live_pat_is_refused` (revoked/expired ones do not count).
    - `test_pat_needs_an_active_human`.
    - `test_service_token_needs_an_active_service_account`.
    - `test_revoke_own_token_only` (another user's id → `CredentialNotFoundError`).
    - `test_revoke_is_idempotent`.
    - `test_revoke_all_covers_every_kind_and_writes_one_event`.
    - `test_connected_apps_lists_live_families_and_revoke_family_kills_them`.
    - `test_revoke_user_tokens_never_raises` (patch the repository to raise; it logs
      `identity.revoke_all_failed`).
  - `tests/access/test_admin_service_accounts.py`: `test_admin_creates_a_service_account`
    (kind service, `svc-<slug>@atlas.internal`, owner = actor, `rbac_changes` row
    `service_account.create`, version bumped), `test_service_account_needs_admin_users`,
    `test_service_account_role_cannot_exceed_the_actor`, `test_duplicate_service_account_conflicts`,
    `test_bad_service_account_names` (parametrized), `test_cli_actor_may_create_one`.
  - `tests/access/test_disable_revokes_tokens.py`: `test_disabling_a_user_revokes_all_their_tokens`
    (PAT + OAuth pair revoked with `user_disabled`; one `tokens.revoked_all` event with
    `actor_user_id` = admin, `via="api"`); `test_role_change_does_not_revoke_tokens`;
    `test_disabled_user_is_refused_even_if_revocation_failed` (patch revocation to fail; the bearer
    door still raises `ForbiddenError`).
- [ ] **Step 2: Run to verify they fail** (`NotImplementedError` from the skeletons).
- [ ] **Step 3: Implement.** Keep functions within the ruff limits (complexity ≤ 10, ≤ 6 args):
  `create_pat` and `create_service_token` share a private `_issue(...)` taking a small
  `_TokenRequest` dataclass.
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/credentials.py \
  backend/app/access/admin.py backend/app/access/__init__.py \
  backend/tests/identity/test_bearer_door.py \
  backend/tests/identity/test_token_service.py backend/tests/access/test_admin_service_accounts.py \
  backend/tests/access/test_disable_revokes_tokens.py
git commit -m "feat(identity): personal and service tokens with the hashed bearer door"
```

---

### Task 4: OAuth authorization service

**Group C (parallel with Task 3). Depends on:** Task 2.

**Files:**
- Modify: `backend/app/identity/oauth.py` (bodies)
- Test: `backend/tests/identity/oauth_helpers.py`, `backend/tests/identity/test_oauth_redirects.py`,
  `backend/tests/identity/test_oauth_service.py`, `backend/tests/identity/test_oauth_refresh.py`,
  `backend/tests/test_mcp_auth_postgres.py` (opt-in, real Postgres)

Task 4 uses `CredentialRepository`, `UserRepository`, the models and the pure functions in
`api_tokens.py` (finished in Task 1). It must not import `credentials.py` (sibling layer).

**Interfaces**

```python
@dataclass(frozen=True, slots=True)
class OAuthConfig:
    issuer: str
    resource: str
    consent_url: str
    hosted_redirect_uris: frozenset[str]
    access_ttl: timedelta = ACCESS_TOKEN_TTL
    refresh_ttl: timedelta = REFRESH_TOKEN_TTL
    code_ttl: timedelta = CODE_TTL
    request_ttl: timedelta = AUTHORIZATION_REQUEST_TTL
    refresh_grace: timedelta = REFRESH_REUSE_GRACE

    @classmethod
    def from_settings(cls, settings: Settings) -> Self

Eligibility = Callable[[UUID], Awaitable[bool]]   # supplied by app/mcp: active + mcp:use

@dataclass(frozen=True, slots=True)
class ClientRegistration:      # what DCR hands us (mapped from the SDK model by app/mcp)
    client_id: str; client_secret: str | None = field(repr=False); client_name: str | None
    redirect_uris: tuple[str, ...]; token_endpoint_auth_method: str
    grant_types: tuple[str, ...]; response_types: tuple[str, ...]; software_id: str | None

@dataclass(frozen=True, slots=True)
class RegisteredClient:        # never carries the secret hash outside identity except for auth
    client_id: str; client_name: str | None; redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str; grant_types: tuple[str, ...]; response_types: tuple[str, ...]
    registered_at: datetime
    def secret_matches(self, presented: str | None) -> bool   # hmac.compare_digest on hashes

@dataclass(frozen=True, slots=True)
class AuthorizationRequestData:
    redirect_uri: str; redirect_uri_provided_explicitly: bool; code_challenge: str
    state: str | None; scopes: tuple[str, ...]; resource: str | None

@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    client_id: str; client_name: str | None; redirect_uri: str; redirect_host: str
    loopback: bool; expires_at: datetime

@dataclass(frozen=True, slots=True)
class CodeGrant:
    code_id: UUID; family_id: UUID; client_id: str; user_id: UUID; code_challenge: str
    redirect_uri: str; redirect_uri_provided_explicitly: bool; resource: str
    scopes: tuple[str, ...]; expires_at: datetime; display: str

@dataclass(frozen=True, slots=True)
class RefreshGrant:
    token_id: UUID; family_id: UUID; client_id: str; user_id: UUID; resource: str
    expires_at: datetime; display: str

@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str = field(repr=False); refresh_token: str = field(repr=False)
    expires_in: int; family_id: UUID; user_id: UUID

@dataclass(frozen=True, slots=True)
class ClientSummary:  # for /admin/clients
    client_id: str; client_name: str | None; redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str; registered_at: datetime; revoked_at: datetime | None
    active_families: int

@dataclass(frozen=True, slots=True)
class GcReport:
    codes: int; requests: int; tokens: int; clients: int

class OAuthRegistrationError(Exception):  # .error: "invalid_redirect_uri" | "invalid_client_metadata"
class OAuthRequestError(Exception):       # .error: "invalid_request"; safe .description
class OAuthGrantError(Exception):         # .error: "invalid_grant"; safe .description
class AuthorizationRequestNotFoundError(Exception):   # unknown, expired or consumed txn -> 404

def canonical_resource(url: str) -> str | None
def redirect_allowed(uri: str, hosted: Collection[str]) -> bool
def is_loopback_redirect(uri: str) -> bool
def with_query(uri: str, **params: str | None) -> str     # keeps existing query; skips None

class OAuthService:
    def __init__(self, db: AsyncSession, config: OAuthConfig,
                 clock: Callable[[], datetime] = _utcnow) -> None
    async def register_client(self, registration: ClientRegistration) -> None
    async def get_client(self, client_id: str) -> RegisteredClient | None
    async def begin_authorization(self, client_id: str, request: AuthorizationRequestData) -> str
    async def pending_request(self, txn: str) -> PendingAuthorization | None
    async def approve(self, txn: str, user_id: UUID) -> str
    async def deny(self, txn: str, user_id: UUID) -> str
    async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None
    async def exchange_code(self, client_id: str, grant: CodeGrant, eligible: Eligibility) -> TokenPair
    async def load_refresh(self, client_id: str, raw_refresh: str) -> RefreshGrant | None
    async def rotate_refresh(self, client_id: str, grant: RefreshGrant, eligible: Eligibility) -> TokenPair
    async def revoke_by_token_id(self, token_id: UUID) -> None        # RFC 7009: the whole family
    async def revoke_client(self, client_id: str, *, actor: CredentialActor) -> bool
    async def list_clients(self) -> list[ClientSummary]
    async def gc(self) -> GcReport
```

**Security-critical code**

```python
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "[::1]"})
_CHALLENGE: Final = re.compile(r"[A-Za-z0-9_-]{43}")   # base64url(SHA-256), RFC 7636 §4.2


def canonical_resource(url: str) -> str | None:
    """The SDK's own comparison (BearerAuthBackend._issued_for_this_resource): case and
    default port do not matter, one trailing slash aside."""
    try:
        return str(AnyHttpUrl(url)).removesuffix("/")
    except ValidationError:
        return None


def redirect_allowed(uri: str, hosted: Collection[str]) -> bool:
    """D8. Parsed with Pydantic AnyUrl (WHATWG, as the browser parses it): no parser
    differential. Loopback http on any port and path, or an exact approved https callback."""
    try:
        url = AnyUrl(uri)
    except ValidationError:
        return False
    if url.username is not None or url.password is not None or url.fragment is not None:
        return False
    if str(url) in {str(AnyUrl(h)) for h in hosted}:
        return url.scheme == "https"
    return url.scheme == "http" and url.host in _LOOPBACK_HOSTS
```

`register_client` rejects (as `OAuthRegistrationError`): any redirect not `redirect_allowed`
(`invalid_redirect_uri`), more than 5 redirects, a `token_endpoint_auth_method` outside `none |
client_secret_post | client_secret_basic`, grant types other than exactly the two we support,
response types other than `["code"]`, a `client_name` over 100 chars (`invalid_client_metadata`).
It stores `hash_secret(client_secret)` when a secret was issued and writes `client.registered`
(`via="oauth"`, details: name, redirect hosts, auth method).

`get_client` returns `None` for unknown or revoked clients, filters stored redirects through
`redirect_allowed` (allowlist narrowed since registration) and returns `None` when none remain.

`begin_authorization` (D7, D36):

```python
async def begin_authorization(self, client_id: str, request: AuthorizationRequestData) -> str:
    client = await self.get_client(client_id)
    if client is None or request.redirect_uri not in client.redirect_uris:
        raise OAuthRequestError("This client or redirect is not registered.")
    audience = self._bind_audience(request.resource)          # mismatch -> OAuthRequestError
    if not _CHALLENGE.fullmatch(request.code_challenge):
        raise OAuthRequestError("code_challenge must be an S256 challenge.")
    if request.state is not None and len(request.state) > 500:
        raise OAuthRequestError("state is too long.")
    txn = mint_secret()
    now = self._clock()
    self._creds.add(OAuthAuthorizationRequest(
        id=hash_secret(txn), client_id=client_id, redirect_uri=request.redirect_uri,
        redirect_uri_provided_explicitly=request.redirect_uri_provided_explicitly,
        code_challenge=request.code_challenge, state=request.state,
        scopes=list(request.scopes), resource=audience,
        created_at=now, expires_at=now + self._config.request_ttl))
    await self._creds.commit()
    return with_query(self._config.consent_url, txn=txn)

def _bind_audience(self, requested: str | None) -> str:
    if requested is None:
        return self._config.resource                         # bound anyway (D7)
    if canonical_resource(requested) != canonical_resource(self._config.resource):
        raise OAuthRequestError(f"Tokens here are only for {self._config.resource}.")
    return self._config.resource
```

`approve` (consent; the caller has already checked eligibility):

```python
async def approve(self, txn: str, user_id: UUID) -> str:
    now = self._clock()
    request = await self._creds.consume_request(hash_secret(txn), now)   # single use
    if request is None:
        raise AuthorizationRequestNotFoundError
    client = await self.get_client(request.client_id)
    if client is None or request.redirect_uri not in client.redirect_uris:
        await self._creds.rollback()          # client revoked meanwhile: nothing issued
        raise AuthorizationRequestNotFoundError
    raw = mint_secret()
    family_id = uuid4()
    self._creds.add(OAuthCode(
        code_hash=hash_secret(raw), client_id=request.client_id, user_id=user_id,
        family_id=family_id, code_challenge=request.code_challenge,
        redirect_uri=request.redirect_uri,
        redirect_uri_provided_explicitly=request.redirect_uri_provided_explicitly,
        resource=request.resource, scopes=request.scopes,
        created_at=now, expires_at=now + self._config.code_ttl))
    self._creds.add(_event(EVENT_CONSENT_APPROVED, user_id=user_id, client_id=request.client_id,
                           details={"family_id": str(family_id)}))
    await self._creds.commit()
    return with_query(request.redirect_uri, code=raw, state=request.state)
```

`deny` consumes the same way and returns `with_query(redirect_uri, error="access_denied",
state=…)`; writes `consent.denied`.

Codes (D5, D30):

```python
async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
    row = await self._creds.code_by_hash(hash_secret(raw_code))
    if row is None or row.client_id != client_id:
        return None                                   # SDK answers invalid_grant
    if row.used_at is not None:
        await self._revoke_family(row.family_id, REVOKED_CODE_REUSE, row.user_id,
                                  row.client_id, kind="code")
        return None
    return _code_grant(row)                           # expiry checked by the SDK (C14)

async def exchange_code(self, client_id: str, grant: CodeGrant, eligible: Eligibility) -> TokenPair:
    now = self._clock()
    if not await self._creds.mark_code_used(grant.code_id, now):
        await self._creds.rollback()
        fresh = await self._creds.code(grant.code_id, fresh=True)
        if fresh is not None and fresh.used_at is not None:          # reuse or lost race
            await self._revoke_family(grant.family_id, REVOKED_CODE_REUSE, grant.user_id,
                                      client_id, kind="code")
        raise OAuthGrantError("The authorization code is no longer valid.")
    if not await self._may_issue(client_id, grant.user_id, grant.resource, eligible):
        await self._creds.commit()                    # the code stays used; nothing issued
        raise OAuthGrantError("Authorization is no longer valid. Sign in again.")
    return await self._issue_pair(client_id, grant.user_id, grant.family_id, now,
                                  EVENT_TOKENS_ISSUED)   # adds rows + event, commits
```

`_may_issue` = user exists, active, `kind=human`; client live; `canonical_resource(resource) ==
canonical_resource(config.resource)`; `await eligible(user_id)` (any exception → False).
`_issue_pair` mints `atl_oat_` (access, `expires_at = now + access_ttl`) and `atl_ort_` (refresh,
`now + refresh_ttl`), both with `family_id`, `client_id`, `audience=config.resource`, stores hashes,
adds the event and commits. `expires_in = int(access_ttl.total_seconds())`.

Refresh (D6, approved default 6):

```python
async def load_refresh(self, client_id: str, raw_refresh: str) -> RefreshGrant | None:
    if kind_of(raw_refresh) is not TokenKind.OAUTH_REFRESH:
        return None
    row = await self._creds.token_by_hash(hash_secret(raw_refresh))
    if row is None or row.kind != TokenKind.OAUTH_REFRESH or row.family_id is None:
        return None
    if row.client_id != client_id:                     # stolen and replayed by another client
        await self._revoke_family(row.family_id, REVOKED_CROSS_CLIENT, row.user_id,
                                  client_id, kind="refresh")
        return None                                     # no grace across clients
    return _refresh_grant(row)                          # revoked rows too: rotate decides

async def rotate_refresh(self, client_id: str, grant: RefreshGrant, eligible: Eligibility) -> TokenPair:
    now = self._clock()
    row = await self._creds.token(grant.token_id, fresh=True)
    if row is None or row.client_id != client_id or row.family_id is None:
        raise OAuthGrantError(_DEAD)
    if row.revoked_at is not None or not await self._creds.mark_rotated(row.id, now):
        await self._creds.rollback()
        row = await self._creds.token(grant.token_id, fresh=True)
        if row is not None and await self._in_grace(row, now):
            await self._require_may_issue(row, eligible, now)
            return await self._issue_pair(client_id, row.user_id, row.family_id, now,
                                          EVENT_REFRESH_GRACE)
        await self._revoke_family(grant.family_id, REVOKED_REFRESH_REUSE, grant.user_id,
                                  client_id, kind="refresh")
        raise OAuthGrantError(_DEAD)
    if as_utc(row.expires_at) <= now:
        await self._creds.rollback()
        raise OAuthGrantError(_DEAD)
    await self._require_may_issue(row, eligible, now)   # on failure: revoke family, commit, raise
    return await self._issue_pair(client_id, row.user_id, row.family_id, now, EVENT_REFRESHED)

async def _in_grace(self, row: ApiToken, now: datetime) -> bool:
    """A concurrent retry by the same client (already checked) within 30 s, while the family is
    still alive. A family revoke never overwrites 'rotated', hence the live-token check."""
    return (
        row.revoked_reason == REVOKED_ROTATED
        and row.revoked_at is not None
        and now - as_utc(row.revoked_at) <= self._config.refresh_grace
        and row.family_id is not None
        and await self._creds.family_has_live_token(row.family_id, now)
    )
```

`_require_may_issue` failure reasons map to the revoke reason: user disabled → `user_disabled`;
no `mcp:use` → `no_mcp_use`; audience differs (4b switch) → `audience_changed`; client revoked →
`client_revoked`. `_DEAD = "The refresh token is no longer valid."` `_revoke_family` revokes every
live row of the family, writes `oauth.reuse_detected` (`details={"family_id", "kind"}`) or
`oauth.family_revoked`, logs `oauth.reuse_detected` with `family_id` only, and commits.

`revoke_client` revokes the client (`revoked_at`) and all its tokens (`client_revoked`), writes
`client.revoked`. `gc` calls `delete_stale` and writes `credentials.gc` with the counts.

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/identity/oauth_helpers.py` (helpers): `pkce_pair() -> (verifier, challenge)`,
    `oauth_config(**overrides)`, `register_public_client(service, redirect=…)`,
    `approved_code(db, user, client) -> (raw_code, CodeGrant)`,
    `issued_pair(db, user, client) -> TokenPair`, `always_eligible`, `never_eligible`.
  - `tests/identity/test_oauth_redirects.py` (pure, parametrized):
    - `test_loopback_redirects_are_allowed`: `http://localhost:35535/oauth/callback`,
      `http://localhost:8765/callback`, `http://127.0.0.1:33418/`, `http://[::1]:9000/cb`,
      `http://localhost/cb` (no port), `http://LOCALHOST:7777/x` (case).
    - `test_the_hosted_callback_is_allowed`: `https://claude.ai/api/mcp/auth_callback`.
    - `test_other_redirects_are_rejected`: `http://atlas.example.com/cb` (http non-loopback),
      `https://localhost/cb` (https loopback), `http://localhost.evil.com/cb`,
      `http://localhost@evil.com/` (userinfo, host evil.com), `http://evil.com@localhost/cb`
      (userinfo), `http://127.0.0.1.nip.io/cb`, `http://127.0.0.2/cb`, `http://0.0.0.0/cb`,
      `http://localhost:8080/cb#frag`, `https://claude.ai/api/mcp/auth_callback/extra`,
      `https://claude.ai.evil.com/api/mcp/auth_callback`, `https://evil.com/?https://claude.ai/…`,
      `javascript:alert(1)`, `custom-scheme://cb`, `""`, `not a url`.
    - `test_backslash_is_parsed_like_a_browser` — `http://localhost\@evil.com/cb` normalises to
      host `localhost` (allowed, harmless) — documents the WHATWG choice.
    - `test_canonical_resource` (parametrized): `http://LOCALHOST:8080/mcp-server/mcp/` equals the
      configured URL; `http://localhost:80/x` ≡ `http://localhost/x`; `…/mcp-server`,
      `…/mcp-server/mcp?x=1`, `https://…` differ; garbage → None.
  - `tests/identity/test_oauth_service.py`:
    - Registration: `test_registration_stores_only_the_secret_hash`,
      `test_registration_rejects_a_disallowed_redirect` (`invalid_redirect_uri`),
      `test_registration_rejects_too_many_redirects`, `test_registration_rejects_private_key_jwt`,
      `test_registration_rejects_extra_grant_types`, `test_registration_writes_an_event`,
      `test_get_client_hides_revoked_clients`,
      `test_get_client_drops_redirects_the_allowlist_no_longer_allows`.
    - Authorization: `test_begin_returns_the_consent_url_with_a_txn_and_stores_its_hash`
      (raw txn not in the row), `test_missing_resource_is_bound_to_the_mcp_url`,
      `test_foreign_resource_is_rejected`, `test_resource_is_compared_canonically`,
      `test_plain_or_malformed_challenge_is_rejected`, `test_unregistered_redirect_is_rejected`,
      `test_pending_request_expires_after_ten_minutes`, `test_pending_request_shows_the_redirect_host_and_loopback_flag`.
    - Consent: `test_approve_issues_a_code_bound_to_the_approver`,
      `test_approve_is_single_use` (second approve → `AuthorizationRequestNotFoundError`),
      `test_cannot_approve_someone_elses_txn_after_consumption`,
      `test_approve_after_expiry_is_not_found`, `test_approve_for_a_revoked_client_issues_nothing`,
      `test_deny_redirects_with_access_denied_and_state`, `test_redirect_is_the_registered_uri`
      (the returned URL's scheme/host/port/path equal the stored redirect).
    - Codes: `test_exchange_issues_a_pair_in_the_codes_family`,
      `test_code_is_single_use_and_reuse_revokes_the_family` (first exchange OK; second `load_code`
      returns None, the pair from the first exchange is revoked with `code_reuse`, one
      `oauth.reuse_detected` event),
      `test_code_from_another_client_is_not_found`, `test_expired_code_cannot_be_marked_used`,
      `test_exchange_refuses_an_ineligible_user` (`never_eligible`; code stays used, no tokens),
      `test_exchange_refuses_a_disabled_user`.
    - Revocation and GC: `test_revoke_by_token_id_revokes_the_family`,
      `test_revoke_client_cascades_to_its_tokens`, `test_gc_removes_idle_clients_and_dead_rows_only`.
    - Leaks: `test_no_secret_reaches_events_or_logs` — run register → begin → approve → exchange →
      rotate under `structlog.testing.capture_logs()`; `assert_no_secret` for the client secret,
      txn, code, access and refresh tokens against all `credential_events` rows, all `api_tokens` /
      `oauth_codes` / `oauth_authorization_requests` rows and the captured logs.
  - `tests/identity/test_oauth_refresh.py`:
    - `test_refresh_rotates_and_revokes_the_old_token` (`rotated`; new pair same family).
    - `test_refresh_is_sliding` (new refresh expiry = now + 30 d).
    - `test_same_client_retry_within_30s_gets_a_fresh_pair` (grace; `oauth.refresh_grace` event;
      the sibling from the first rotation stays live).
    - `test_same_client_reuse_after_30s_revokes_the_family` (clock + 31 s → `OAuthGrantError`,
      every family row revoked, `oauth.reuse_detected`).
    - `test_cross_client_reuse_revokes_the_family_without_grace` (within 1 s, other client id).
    - `test_grace_never_revives_a_revoked_family` (family revoked, then the rotated token within
      30 s → error).
    - `test_superseded_or_admin_revoked_token_is_reuse`.
    - `test_refresh_rechecks_the_user` (disabled → `user_disabled` family revoke),
      `test_refresh_rechecks_mcp_use` (`never_eligible` → `no_mcp_use`),
      `test_refresh_rechecks_the_audience` (config resource changed → `audience_changed`),
      `test_refresh_for_a_revoked_client_fails`.
    - `test_expired_refresh_token_fails`.
    - `test_access_token_is_never_accepted_as_refresh` (`load_refresh` with an `atl_oat_` → None).
  - `tests/test_mcp_auth_postgres.py` (opt-in like `tests/test_access_postgres.py`: `TEST_PG_URL`,
    `pg_guard.is_disposable`, `pytest.mark.xdist_group(PG_XDIST_GROUP)`, schema reset via Alembic
    `upgrade head`):
    - `test_concurrent_code_exchange_exactly_one_wins` — two `OAuthService` instances on two
      sessions run `exchange_code` for the same grant under `asyncio.gather`; exactly one returns a
      `TokenPair`, the other raises `OAuthGrantError`; afterwards every row of the family is revoked
      (`code_reuse`) and there is one `oauth.reuse_detected` event (D30).
    - `test_concurrent_refresh_same_client_both_succeed_within_grace` — two rotations of the same
      refresh token: both return pairs (one `oauth.refreshed`, one `oauth.refresh_grace`).
    - `test_concurrent_consent_approve_exactly_one_code` — two approves of one txn: one URL, one
      `AuthorizationRequestNotFoundError`, one `oauth_codes` row.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Split helpers to stay within complexity 10 and 50 statements.
- [ ] **Step 4: Run the gate**, then the opt-in PG module once:
  `TEST_PG_URL=… uv run pytest tests/test_mcp_auth_postgres.py -p no:xdist -q` (see Task 12 for
  the throwaway container).
- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/oauth.py backend/tests/identity/oauth_helpers.py \
  backend/tests/identity/test_oauth_redirects.py backend/tests/identity/test_oauth_service.py \
  backend/tests/identity/test_oauth_refresh.py backend/tests/test_mcp_auth_postgres.py
git commit -m "feat(identity): OAuth 2.1 authorization service with rotation and reuse detection"
```

---
### Task 5: SDK adapters, OAuth routes and discovery documents

**Group D (parallel with 7, 8, 9, 10). Depends on:** Tasks 3 and 4.

**Files:**
- Create: `backend/app/mcp/auth.py`, `backend/app/mcp/oauth_provider.py`, `backend/app/mcp/oauth_routes.py`
- Test: `backend/tests/mcp/oauth_client.py` (helpers), `backend/tests/mcp/test_auth_verifier.py`,
  `backend/tests/mcp/test_oauth_provider.py`, `backend/tests/mcp/test_oauth_routes.py`,
  `backend/tests/mcp/test_oauth_flow.py`

Verified SDK surface (mcp 1.30.0) this task uses: `mcp.server.auth.provider.{AccessToken,
AuthorizationCode, RefreshToken, AuthorizationParams, OAuthAuthorizationServerProvider,
RegistrationError, AuthorizeError, TokenError}`; `mcp.server.auth.handlers.authorize.AuthorizationHandler(provider)`;
`mcp.server.auth.handlers.token.TokenHandler(provider, client_authenticator)`;
`mcp.server.auth.handlers.register.RegistrationHandler(provider, options)`;
`mcp.server.auth.handlers.metadata.MetadataHandler(metadata)`;
`mcp.server.auth.middleware.client_auth.{ClientAuthenticator, AuthenticationError}`;
`mcp.server.auth.routes.{validate_issuer_url, cors_middleware}`;
`mcp.server.auth.settings.ClientRegistrationOptions`; `mcp.server.auth.json_response.PydanticJSONResponse`;
`mcp.server.transport_security.{RequestBodyLimitMiddleware, DEFAULT_MAX_REQUEST_BODY_SIZE}`;
`mcp.server.streamable_http.MCP_PROTOCOL_VERSION_HEADER`; `mcp.shared.auth.{OAuthMetadata,
ProtectedResourceMetadata, OAuthClientInformationFull, OAuthToken}`. Do **not** import the SDK's
private `_cors` / `_body_limited` (pyright strict `reportPrivateUsage`); wrap with Starlette's
`CORSMiddleware` and `RequestBodyLimitMiddleware` directly, as the SDK does.

**Interfaces**

```python
# app/mcp/auth.py
class AtlasAccessToken(AccessToken):
    """SDK carrier. `token` holds the display prefix only (D28)."""
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    principal: Principal
    token_id: UUID

class AtlasTokenVerifier:                       # satisfies mcp TokenVerifier structurally
    def __init__(self, resource_url: str,
                 sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory) -> None
    async def verify_token(self, token: str) -> AtlasAccessToken | None
```

```python
# app/mcp/oauth_provider.py
class AtlasAuthorizationCode(AuthorizationCode):   # .code = display prefix (D28)
    code_id: UUID; family_id: UUID; user_id: UUID
class AtlasRefreshToken(RefreshToken):             # .token = display prefix (D28)
    token_id: UUID; family_id: UUID; user_id: UUID

class AtlasOAuthProvider(
    OAuthAuthorizationServerProvider[AtlasAuthorizationCode, AtlasRefreshToken, AtlasAccessToken]
):
    def __init__(self, config: OAuthConfig, verifier: AtlasTokenVerifier, *,
                 sessions: Callable[[], async_sessionmaker[AsyncSession]] = get_session_factory) -> None
    async def client_record(self, client_id: str) -> RegisteredClient | None
    # the nine protocol methods: get_client, register_client, authorize, load_authorization_code,
    # exchange_authorization_code, load_refresh_token, exchange_refresh_token, load_access_token,
    # revoke_token — each opens one session and builds OAuthService(db, config)
    async def eligible(self, user_id: UUID) -> bool     # active + mcp:use; any error -> False

class HashedClientAuthenticator(ClientAuthenticator):
    def __init__(self, provider: AtlasOAuthProvider) -> None
    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull
```

```python
# app/mcp/oauth_routes.py
def build_oauth_metadata(config: OAuthConfig) -> OAuthMetadata
def build_oauth_routes(provider: AtlasOAuthProvider, config: OAuthConfig) -> list[Route]
    # sub-app relative: /.well-known/oauth-authorization-server, /authorize, /token, /register, /revoke
@dataclass
class AtlasRevocationHandler:                    # D29
    provider: AtlasOAuthProvider
    authenticator: HashedClientAuthenticator
    async def handle(self, request: Request) -> Response
discovery_router: APIRouter                       # root, unauthenticated:
    # GET /.well-known/oauth-protected-resource/mcp-server/mcp   (RFC 9728)
    # GET /.well-known/oauth-authorization-server/mcp-server     (RFC 8414 path-inserted)
```

**Behaviour and security-critical code**

Verifier (D20, D28, fail closed):

```python
async def verify_token(self, token: str) -> AtlasAccessToken | None:
    try:
        async with self._sessions()() as db:
            bearer = await authenticate_bearer(db, token)
    except (InvalidTokenError, ForbiddenError) as exc:
        logger.info("mcp.bearer_rejected", reason=type(exc).__name__)   # no token material
        return None
    except Exception as exc:  # fail closed: 401, never 500 with a traceback holding the token
        logger.error("mcp.bearer_check_failed", error=type(exc).__name__)
        return None
    principal = bearer.principal
    return AtlasAccessToken(
        token=bearer.display_prefix,
        client_id=principal.client_id or principal.auth_method,
        scopes=[],
        expires_at=int(bearer.expires_at.timestamp()),
        resource=bearer.audience or self._resource_url,   # PAT/service: current URL (D7)
        subject=str(principal.user_id),
        principal=principal,
        token_id=bearer.principal.token_id,
    )
```

Use `logger.error(..., error=type(exc).__name__)`, never `logger.exception`, in any frame that holds
a raw secret: in development structlog renders tracebacks with `rich` and `show_locals=True`
(`structlog.dev.RichTracebackFormatter` default), which would print the token. (`rich` is a dev-only
dependency via import-linter, so production has plain tracebacks, but the rule holds everywhere.)

Client authentication with hashed secrets (the SDK's `ClientAuthenticator` compares the plaintext
`client.client_secret`, `client_auth.py:102-110`; our `get_client` never returns a secret, so the
SDK class would skip the check — it must never be used):

```python
class HashedClientAuthenticator(ClientAuthenticator):
    def __init__(self, provider: AtlasOAuthProvider) -> None:
        super().__init__(provider)
        self._atlas = provider

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        form = await request.form()
        client_id = form.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthenticationError("Missing client_id")
        record = await self._atlas.client_record(client_id)   # None if unknown or revoked
        if record is None:
            raise AuthenticationError("Invalid client")
        presented = _presented_secret(request, form, record, client_id)  # basic | post | none
        if not record.secret_matches(presented):   # public: True; confidential: compare_digest
            raise AuthenticationError("Invalid client credentials")
        info = await self._atlas.get_client(client_id)
        if info is None:
            raise AuthenticationError("Invalid client")
        return info
```

`_presented_secret`: for `client_secret_basic` decode `Authorization: Basic`, URL-unquote both
halves (RFC 6749 §2.3.1) and require the id to equal the form `client_id`; for
`client_secret_post` read the `client_secret` form field; for `none` return `None`. Malformed
headers raise `AuthenticationError("Invalid client credentials")`. `RegisteredClient.secret_matches`
(Task 4) does `hmac.compare_digest(stored_hash, hash_secret(presented))`, and for a public client
returns `True` (a presented secret is ignored).

Metadata with `none` (the SDK's `build_metadata` hard-codes only `client_secret_post` and
`client_secret_basic`, `routes.py:169,186`):

```python
_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]

def build_oauth_metadata(config: OAuthConfig) -> OAuthMetadata:
    issuer = config.issuer
    return OAuthMetadata(
        issuer=AnyHttpUrl(issuer),
        authorization_endpoint=AnyHttpUrl(f"{issuer}/authorize"),
        token_endpoint=AnyHttpUrl(f"{issuer}/token"),
        registration_endpoint=AnyHttpUrl(f"{issuer}/register"),
        revocation_endpoint=AnyHttpUrl(f"{issuer}/revoke"),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=_AUTH_METHODS,
        revocation_endpoint_auth_methods_supported=_AUTH_METHODS,
        code_challenge_methods_supported=["S256"],
        # scopes_supported omitted (D10); client_id_metadata_document_supported omitted (D9)
    )
```

Route table (relative to the `/mcp-server` mount; `build_oauth_routes` calls
`validate_issuer_url(AnyHttpUrl(config.issuer))` first):

| Path | Methods | Endpoint | Wrappers |
|---|---|---|---|
| `/.well-known/oauth-authorization-server` | GET, OPTIONS | `MetadataHandler(metadata).handle` | `cors_middleware` |
| `/authorize` | GET, POST | `AuthorizationHandler(provider).handle` | body limit, no CORS |
| `/token` | POST, OPTIONS | `TokenHandler(provider, authenticator).handle` | body limit + CORS `*` |
| `/register` | POST, OPTIONS | `RegistrationHandler(provider, ClientRegistrationOptions(enabled=True))` | body limit + CORS `*` |
| `/revoke` | POST, OPTIONS | `AtlasRevocationHandler(provider, authenticator).handle` | body limit + CORS `*` |

Provider mapping rules:
- `register_client(info)`: map `OAuthClientInformationFull` → `ClientRegistration` (redirects as
  `str(AnyUrl)`), call `OAuthService.register_client`; `OAuthRegistrationError(e)` →
  `RegistrationError(e.error, e.description)`. The SDK returns the raw `client_secret` in the 201
  body (shown once) — that is the only place it ever appears.
- `get_client(id)`: `RegisteredClient` → `OAuthClientInformationFull(client_secret=None, …)`.
- `authorize(client, params)`: build `AuthorizationRequestData` (`redirect_uri=str(params.redirect_uri)`,
  `scopes=tuple(params.scopes or ())`, `resource=params.resource`) → `begin_authorization` → consent
  URL. `OAuthRequestError` → `AuthorizeError("invalid_request", description)` (the SDK then
  redirects the error to the registered, validated redirect with `state`).
- `load_authorization_code` / `exchange_authorization_code` → `load_code` / `exchange_code(…,
  eligible=self.eligible)`; `OAuthGrantError` → `TokenError("invalid_grant", description)`. The
  SDK checks client match, expiry (`time.time()`), redirect equality and PKCE S256 between the two
  calls (`handlers/token.py:133-185`).
- `load_refresh_token` / `exchange_refresh_token` → `load_refresh` / `rotate_refresh`. The
  `scopes` argument is ignored (D10). Return `OAuthToken(access_token=…, token_type="Bearer",
  expires_in=3600, refresh_token=…)`.
- `load_access_token(raw)` → `self._verifier.verify_token(raw)`.
- `revoke_token(token)` → `OAuthService.revoke_by_token_id(token.token_id |
  token.principal.token_id)`.
- `eligible(user_id)`: `principal_for_user` + `access.policy_for(...).has(MCP_USE)`; any exception
  logs `mcp.eligibility_check_failed` and returns `False`.

Revocation handler (C2): same flow as the SDK's (`revoke.py:42-91`) but the form model has
`client_secret: str | None = None`, it uses `HashedClientAuthenticator`, tries
`load_access_token` then `load_refresh_token` (reversed for `token_type_hint=refresh_token`),
revokes only when `token.client_id == client.client_id`, and always answers 200 with
`Cache-Control: no-store`.

Discovery (served by FastAPI at the root, because the sub-app's own PRM route lands at
`/mcp-server/.well-known/…`, analysis §1.1):

```python
discovery_router = APIRouter(tags=["mcp-discovery"])
_DISCOVERY_HEADERS = {"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"}

@discovery_router.get("/.well-known/oauth-protected-resource/mcp-server/mcp")
async def protected_resource(settings: Settings = Depends(get_settings)) -> JSONResponse:
    metadata = ProtectedResourceMetadata(
        resource=AnyHttpUrl(settings.mcp_resource_url),          # exactly what users type
        authorization_servers=[AnyHttpUrl(settings.mcp_issuer_url)],
        resource_name="ygg-atlas",
    )
    return JSONResponse(metadata.model_dump(mode="json", exclude_none=True),
                        headers=_DISCOVERY_HEADERS)

@discovery_router.get("/.well-known/oauth-authorization-server/mcp-server")
async def authorization_server(settings: Settings = Depends(get_settings)) -> JSONResponse:
    metadata = build_oauth_metadata(OAuthConfig.from_settings(settings))
    return JSONResponse(metadata.model_dump(mode="json", exclude_none=True),
                        headers=_DISCOVERY_HEADERS)
```

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/mcp/oauth_client.py` (helpers): `pkce()`, `oauth_test_app(settings) -> FastAPI` (the
    discovery router + `Mount("/mcp-server", Starlette(routes=build_oauth_routes(...)))`),
    `BASE = "http://localhost:8080"`, `register(client, redirect=…, auth_method="none")`,
    `authorize(client, client_id, challenge, *, state, resource) -> txn`,
    `approve_directly(db, txn, user) -> (code, state)` (calls `OAuthService.approve`; the HTTP
    consent route is Task 8), `exchange(client, …)`, `refresh(client, …)`,
    `age_rotation(db, token_id, seconds)` (moves `revoked_at` back; SDK expiry uses wall time).
  - `tests/mcp/test_auth_verifier.py`: `test_pat_becomes_an_atlas_access_token` (resource = current
    URL, client_id `"pat"`, `token` == display prefix, subject = user id),
    `test_oauth_token_reports_its_bound_audience`,
    `test_invalid_disabled_unknown_tokens_are_none` (parametrized),
    `test_verifier_fails_closed_on_unexpected_errors` (patch `authenticate_bearer` to raise
    `RuntimeError`; returns None; log `mcp.bearer_check_failed`; `assert_no_secret`),
    `test_access_token_repr_and_json_hold_no_secret`.
  - `tests/mcp/test_oauth_provider.py`: `test_get_client_never_returns_a_secret`,
    `test_register_maps_allowlist_failures_to_invalid_redirect_uri`,
    `test_authorize_maps_a_foreign_resource_to_invalid_request`,
    `test_code_carrier_holds_only_the_display_prefix`,
    `test_exchange_requires_mcp_use` (viewer → `TokenError("invalid_grant")`),
    `test_refresh_requires_mcp_use`, `test_eligibility_fails_closed` (patch `policy_for` to raise),
    `test_revoke_token_revokes_the_family`.
    Authenticator: `test_public_client_needs_no_secret`, `test_confidential_post_secret_ok`,
    `test_confidential_basic_secret_ok`, `test_wrong_secret_is_rejected`,
    `test_missing_secret_is_rejected`, `test_basic_client_id_mismatch_is_rejected`,
    `test_unknown_or_revoked_client_is_rejected`, `test_only_the_secret_hash_is_stored`.
  - `tests/mcp/test_oauth_routes.py`:
    - `test_as_metadata_advertises_none_s256_and_no_scopes` (`none` in both auth-method lists;
      `code_challenge_methods_supported == ["S256"]`; no `scopes_supported`; no
      `client_id_metadata_document_supported`; issuer exactly `http://localhost:8080/mcp-server`).
    - `test_as_metadata_is_served_at_both_paths` (root path-inserted and issuer-relative, same body).
    - `test_protected_resource_metadata` (`resource` exactly `http://localhost:8080/mcp-server/mcp`,
      `authorization_servers == ["http://localhost:8080/mcp-server"]`, `bearer_methods_supported
      == ["header"]`).
    - `test_discovery_follows_atlas_public_url` (`https://atlas.example.com`).
    - `test_register_public_client_gets_no_secret`,
      `test_register_confidential_client_sees_its_secret_once` (201 body has it; DB has only the
      hash), `test_register_accepts_the_desktop_loopback_callback`
      (`http://localhost:35535/oauth/callback`), `test_register_accepts_the_claude_ai_callback`,
      `test_register_rejects_a_non_allowlisted_redirect` (400 `invalid_redirect_uri`).
    - `test_authorize_redirects_to_consent` (302, `Location` starts with
      `http://localhost:8080/oauth/consent?txn=`, `Cache-Control: no-store`, request row stores only
      the txn hash).
    - `test_authorize_refuses_plain_pkce` (`code_challenge_method=plain`: error, no request row),
      `test_authorize_refuses_a_missing_challenge`,
      `test_authorize_refuses_an_unregistered_redirect_without_redirecting` (400 JSON, not 302),
      `test_authorize_foreign_resource_redirects_invalid_request_with_state`.
    - `test_token_endpoint_requires_form_encoding` (JSON body → 400 `invalid_request`).
    - `test_wrong_pkce_verifier_is_invalid_grant`, `test_token_redirect_uri_must_match`.
    - `test_public_client_can_revoke_without_a_secret` (C2 regression: 200 and family revoked).
    - `test_revoking_an_unknown_token_is_200`.
  - `tests/mcp/test_oauth_flow.py` (full ASGI flow with real PKCE, consent via `OAuthService`):
    - `test_register_authorize_consent_token_refresh_reuse_revoke` — discovery → register →
      authorize (302 to consent) → approve → code + state → token (200; `token_type` Bearer,
      `expires_in` 3600, both tokens prefixed) → `verify_token(access)` ok → refresh (new pair, old
      refresh `rotated`) → present the old refresh again after `age_rotation(…, 31)` → 400
      `invalid_grant` and every family token dead → a fresh authorization works → `/revoke` the new
      refresh → its access token no longer verifies.
    - `test_code_replay_over_http_revokes_the_tokens` (second `/token` with the same code →
      `invalid_grant`; the first pair no longer verifies).
    - `test_refresh_retry_within_grace_over_http` (same refresh twice back-to-back → two 200s).
    - `test_refresh_from_another_client_is_invalid_grant_and_revokes`.
    - `test_no_secret_in_logs_or_error_bodies` (`capture_logs` across the whole flow;
      `assert_no_secret` for client secret, txn, code, access, refresh against logs and every
      non-200 body).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Pyright strict applies (`app/mcp` joined strict in Task 1).
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/auth.py backend/app/mcp/oauth_provider.py backend/app/mcp/oauth_routes.py \
  backend/tests/mcp/oauth_client.py backend/tests/mcp/test_auth_verifier.py \
  backend/tests/mcp/test_oauth_provider.py backend/tests/mcp/test_oauth_routes.py \
  backend/tests/mcp/test_oauth_flow.py
git commit -m "feat(mcp): OAuth provider, hashed client auth and discovery routes"
```

---

### Task 6: Per-principal MCP server, wiring, shared token retired

**Serialized after group D. Depends on:** Tasks 5, 7, 8, 9 (and 10 for the end-to-end consent page
check in Task 12, not for this task's tests).

**Files:**
- Modify: `backend/app/mcp/server.py` (rewrite), `backend/app/mcp/__init__.py`,
  `backend/app/mcp/oauth_routes.py` (rate-limit wrappers), `backend/app/mcp/router.py` (consent
  limit), `backend/app/main.py`, `backend/app/config.py` (remove `atlas_mcp_token`,
  `mcp_service_email`), `backend/app/identity/service.py` (remove `service_principal`),
  `backend/app/identity/__init__.py` (drop its export), `backend/pyproject.toml`
- Test: create `backend/tests/mcp/mcp_rpc.py` (helper), `backend/tests/mcp/test_server.py`,
  `backend/tests/mcp/test_mcp_e2e.py`, `backend/tests/mcp/test_rate_limited_routes.py`;
  delete `backend/tests/test_mcp_access.py` (it tests the removed shared token; every behaviour it
  covered that still exists is re-tested in `test_server.py`); modify `backend/tests/test_startup.py`,
  `backend/tests/identity/test_service_users.py` (drop the `service_principal` tests, keep the
  `ensure_service_user` ones), `backend/tests/test_config.py`

**Interfaces** (`app/mcp/__init__.py` public surface)

```python
from app.mcp.oauth_routes import discovery_router
from app.mcp.router import mcp_router
from app.mcp.server import (AtlasMCP, TOOL_REQUIREMENTS, build_http_app, build_mcp,
                            prepare_mcp_auth)

ToolNeed = Literal["mcp", "metrics", "funnels"]
TOOL_REQUIREMENTS: Final[Mapping[str, ToolNeed]] = MappingProxyType({
    "list_metrics": "mcp", "search_atlas": "mcp", "describe_entity": "mcp",
    "query_metric": "metrics", "metric_breakdown": "metrics", "compare_periods": "metrics",
    "funnel_analyze": "funnels",
})

class AtlasMCP(FastMCP[Any]):
    atlas_verifier: AtlasTokenVerifier
    async def list_tools(self) -> list[MCPTool]

def build_mcp(settings: Settings) -> AtlasMCP
def build_http_app(server: AtlasMCP, settings: Settings) -> Starlette
def transport_security_for(public_url: str) -> TransportSecuritySettings
async def prepare_mcp_auth(db: AsyncSession, settings: Settings) -> None
async def run_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]
```

**Security-critical code**

```python
NO_MCP_ACCESS: Final = {"error": "This account doesn't include MCP access (mcp:use). "
                                 "Ask an atlas admin, or request access in atlas."}
UNAVAILABLE: Final = {"error": "Atlas is unavailable right now. Try again shortly."}


def _caller_token() -> AtlasAccessToken | None:
    token = get_access_token()                 # SDK contextvar set by AuthContextMiddleware
    return token if isinstance(token, AtlasAccessToken) else None


async def run_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One atlas tool as the calling principal (D20). Every failure is 'unavailable'."""
    token = _caller_token()
    if token is None:                          # cannot happen behind RequireAuthMiddleware
        logger.error("mcp.no_principal")
        return dict(UNAVAILABLE)
    principal = token.principal
    try:
        async with get_session_factory()() as db:
            policy = await policy_for(db, principal)
            if not policy.has(MCP_USE):
                return dict(NO_MCP_ACCESS)
            caller = AtlasCaller(user_id=principal.user_id, auth_method=principal.auth_method,
                                 surface="mcp", token_id=principal.token_id,
                                 client_id=principal.client_id)
            return await AtlasTools(caller, policy, db=db).execute(tool, arguments)
    except Exception as exc:                   # PolicyUnavailableError included: fail closed
        logger.error("mcp.tool_unavailable", tool=tool, error=type(exc).__name__)
        return dict(UNAVAILABLE)


class AtlasMCP(FastMCP[Any]):
    async def list_tools(self) -> list[MCPTool]:
        """Spec §6 point 1 (D19). Registered by FastMCP._setup_handlers as the bound method
        (fastmcp/server.py:318-320), so this override is what tools/list calls."""
        tools = await super().list_tools()
        allowed = await _allowed_tool_names()
        return [tool for tool in tools if tool.name in allowed]


async def _allowed_tool_names() -> frozenset[str]:
    token = _caller_token()
    if token is None:
        return frozenset()
    try:
        async with get_session_factory()() as db:
            policy = await policy_for(db, token.principal)
            if not policy.has(MCP_USE):
                return frozenset()
            atlas = AtlasTools(_caller(token), policy, db=None)
            visible: set[ToolNeed] = {"mcp"}
            if atlas.visible_metrics():
                visible.add("metrics")
            if atlas.visible_funnels():
                visible.add("funnels")
    except Exception as exc:
        logger.error("mcp.list_tools_failed", error=type(exc).__name__)
        return frozenset()
    return frozenset(name for name, need in TOOL_REQUIREMENTS.items() if need in visible)
```

Tools keep today's names, signatures and descriptions byte-for-byte; they are module-level
functions registered by `_register_tools(server)` with `server.add_tool(fn, name=…,
description=…)`, each returning `dict[str, Any]`.

```python
def transport_security_for(public_url: str) -> TransportSecuritySettings:
    """D26 / C1: keep DNS-rebinding protection on, but allow our own public host (with and without
    the port, because nginx `$host` drops it) and loopback."""
    parts = urlsplit(public_url)
    host, netloc = parts.hostname or "localhost", parts.netloc
    hosts = {netloc, host, "localhost", "127.0.0.1", "localhost:*", "127.0.0.1:*", "[::1]:*"}
    origins = {f"{parts.scheme}://{netloc}", "http://localhost:*", "http://127.0.0.1:*",
               "http://[::1]:*"}
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=sorted(hosts), allowed_origins=sorted(origins))


def build_mcp(settings: Settings) -> AtlasMCP:
    verifier = AtlasTokenVerifier(settings.mcp_resource_url)
    server = AtlasMCP(
        "ygg-atlas",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.mcp_issuer_url),
            resource_server_url=AnyHttpUrl(settings.mcp_resource_url),
            validate_token_resource=True,      # audience enforced per request (D7)
        ),
        stateless_http=True,
        transport_security=transport_security_for(settings.atlas_public_url),
    )
    server.atlas_verifier = verifier
    _register_tools(server)
    return server


def build_http_app(server: AtlasMCP, settings: Settings) -> Starlette:
    config = OAuthConfig.from_settings(settings)
    provider = AtlasOAuthProvider(config, server.atlas_verifier)
    app = server.streamable_http_app()          # /mcp behind RequireAuthMiddleware + PRM (unused)
    app.router.routes.extend(build_oauth_routes(provider, config))
    # outermost: refuse sources with too many failed bearers; innermost: per-token call budget
    app.user_middleware.insert(0, Middleware(FailedBearerGuard, policy=BEARER_FAILURES))
    app.user_middleware.append(Middleware(PrincipalRateLimit, policy=MCP_CALLS, key=_token_key))
    app.middleware_stack = app.build_middleware_stack()
    return app
```

`_token_key(scope)` returns `str(access_token.token_id)` when `scope["user"]` is an
`AuthenticatedUser` holding an `AtlasAccessToken`, else `None` (skip). The 401 from
`RequireAuthMiddleware` already carries `WWW-Authenticate: Bearer error="invalid_token",
error_description="Authentication required", resource_metadata="<url>/.well-known/oauth-protected-resource/mcp-server/mcp"`
(built by `build_resource_metadata_url(resource_server_url)`, `routes.py:191-207`).

Rate-limit wiring (`oauth_routes.py`): wrap the `/authorize`, `/token` and `/register` endpoints
with `RateLimitedEndpoint(app, AUTHORIZE | TOKEN | REGISTER)` (keyed by source).
`router.py`: the consent `GET` and `POST` get `Depends(rate_limit(CONSENT, key=_consent_user_key))`
where the key is the principal's `user_id`.

`main.py`:
- `from app.mcp import build_http_app, build_mcp, discovery_router, mcp_router, prepare_mcp_auth`;
  build once at import inside the existing `try` (`_mcp = build_mcp(settings)`, `_mcp_app =
  build_http_app(_mcp, settings)`); on failure log `mcp.load_failed` and keep the chat API up.
- `apply_startup()`: drop `ensure_service_user` and the `MCP_SERVICE_*` constants; after
  `prepare_access(...)` call `await prepare_mcp_auth(db, settings)` (logs `mcp.auth_ready` with
  issuer, resource and `hosted_connectors`; logs `mcp.public_url_local` in production when the URL
  is not https; runs `OAuthService.gc()` and logs failures without raising).
- `app.include_router(mcp_router)`, `app.include_router(discovery_router)`; mount stays
  `/mcp-server`; the lifespan runs `_mcp.session_manager.run()`.

`pyproject.toml`: remove the `# pyright: basic` pragma from `server.py` (file is rewritten) and add:

```toml
[[tool.importlinter.contracts]]
name = "MCP module layering"
type = "layers"
containers = ["app.mcp"]
exhaustive = true
layers = [
    "server | cli",
    "router",
    "oauth_routes | dependencies",
    "oauth_provider",
    "auth | ratelimit | schemas",
]
```

**Steps**

- [ ] **Step 1: Write the failing tests**
  - `tests/mcp/mcp_rpc.py` (helper): `full_app(settings) -> (FastAPI, AtlasMCP)` (all routers +
    fresh `build_mcp` mounted at `/mcp-server`), `rpc(client, token, method, params) -> dict`
    (POST `/mcp-server/mcp` with `Accept: application/json, text/event-stream`,
    `Content-Type: application/json`; parses the SSE `data:` line). Tests wrap requests in
    `async with server.session_manager.run():` (fresh server per test, C9).
  - `tests/mcp/test_server.py`:
    - `test_tool_requirements_cover_every_registered_tool` (keys == registered names).
    - `test_tool_names_and_descriptions_are_unchanged` (the seven names and their published
      descriptions, as on main).
    - `test_list_tools_without_a_token_is_empty`, `test_list_tools_without_mcp_use_is_empty`.
    - `test_list_tools_hides_metric_tools_without_visible_metrics` and
      `test_list_tools_hides_the_funnel_tool_without_visible_funnels` (grants on `demo/checkout/*`
      vs `demo/order/*`).
    - `test_list_tools_fails_closed_on_policy_errors`.
    - `test_a_tool_missing_from_the_table_is_never_listed` (register an extra tool on a fresh
      server).
    - `test_run_tool_without_mcp_use_is_denied`.
    - `test_run_tool_collapses_failures_to_unavailable` (parametrized: `policy_for` raises
      `PolicyUnavailableError`; raises `RuntimeError`; `AtlasTools.execute` raises) — result equals
      `UNAVAILABLE`, nothing internal in it.
    - `test_run_tool_audits_the_credential` (audit row `surface="mcp"`, `auth_method`,
      `token_id`, `client_id`).
    - `test_transport_security_from_public_url` (localhost and https host sets).
    - `test_build_mcp_uses_the_configured_urls`.
    - `test_standalone_mode_serves_on_loopback` (ported from the deleted file).
  - `tests/mcp/test_mcp_e2e.py`:
    - `test_unauthenticated_call_is_401_with_resource_metadata` (exact `WWW-Authenticate` value;
      body `{"error":"invalid_token",…}`).
    - `test_oauth_flow_end_to_end` — discovery from the 401 header → PRM → AS metadata → register
      → authorize → **HTTP** `POST /api/v1/oauth/consent` as the signed-in user (override
      `get_principal`) → token → `initialize` → `tools/list` (filtered) → `tools/call
      list_metrics` (data) → audit row has `auth_method="oauth"`, `token_id`, `client_id` →
      refresh → reuse after grace → `invalid_grant` and the new access token now 401 → re-auth.
    - `test_pat_via_header_calls_tools` (audit `auth_method="pat"`, `client_id` None).
    - `test_service_token_calls_tools_as_the_service_account`.
    - `test_revoked_pat_is_401_on_the_next_request`.
    - `test_user_disabled_mid_session_is_401` (disable with `AccessAdmin.update_user`; next
      request 401; tokens revoked `user_disabled`).
    - `test_user_without_mcp_use_sees_no_tools_and_a_denial` (HTTP 200 both, D31).
    - `test_token_for_another_audience_is_401` (set the row's audience to
      `https://other.example/mcp`).
    - `test_disconnected_app_is_401_then_reauth_works` (`DELETE /api/v1/me/connected-apps/{id}`).
    - `test_the_shared_token_is_gone` (`ATLAS_MCP_TOKEN=s3cret` in env; `Bearer s3cret` → 401;
      `Settings` has no `atlas_mcp_token`).
    - `test_host_header_without_port_is_accepted_and_foreign_host_is_421`.
    - `test_no_secret_in_logs_audit_or_bodies_end_to_end`.
  - `tests/mcp/test_rate_limited_routes.py` (call `reset_limiters()` in a fixture):
    `test_token_endpoint_429_after_30_per_minute`, `test_authorize_429_after_30_per_minute`,
    `test_register_429_after_10_per_hour`, `test_mcp_calls_429_after_120_per_token` (a second
    token is unaffected), `test_failed_bearers_429_after_20_per_source`,
    `test_consent_429_after_10_per_user`, `test_429_has_retry_after_and_no_secret`.
  - `tests/test_startup.py`: the shared MCP user is no longer created;
    `test_startup_prepares_mcp_auth` (gc ran; `mcp.auth_ready` logged).
  - `tests/test_config.py`: `test_shared_mcp_token_settings_are_gone`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** server, wiring, removals, contract.
- [ ] **Step 4: Run the gate.** `lint-imports` must pass the new MCP contract; pyright strict on
  all of `app/mcp`; coverage of `app/mcp` > 80 %.
- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/server.py backend/app/mcp/__init__.py backend/app/mcp/oauth_routes.py \
  backend/app/mcp/router.py backend/app/main.py backend/app/config.py \
  backend/app/identity/service.py backend/app/identity/__init__.py backend/pyproject.toml \
  backend/tests/mcp/mcp_rpc.py backend/tests/mcp/test_server.py backend/tests/mcp/test_mcp_e2e.py \
  backend/tests/mcp/test_rate_limited_routes.py backend/tests/test_startup.py \
  backend/tests/identity/test_service_users.py backend/tests/test_config.py
git rm backend/tests/test_mcp_access.py
git commit -m "feat(mcp): per-principal MCP server; retire the shared token

The shared-token tests in tests/test_mcp_access.py are removed with the
feature they tested; the per-principal behaviour is covered by
tests/mcp/test_server.py and tests/mcp/test_mcp_e2e.py."
```

---

### Task 7: Rate limiting

**Group D. Depends on:** Task 2 (nothing from 3–5; it is generic).

**Files:**
- Create: `backend/app/mcp/ratelimit.py`
- Test: `backend/tests/mcp/test_ratelimit.py`

**Interfaces**

```python
@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int

MCP_CALLS = RateLimitPolicy("mcp_calls", 120, 60)
TOKEN = RateLimitPolicy("oauth_token", 30, 60)
AUTHORIZE = RateLimitPolicy("oauth_authorize", 30, 60)
REGISTER = RateLimitPolicy("oauth_register", 10, 3600)
BEARER_FAILURES = RateLimitPolicy("bearer_failures", 20, 60)
CONSENT = RateLimitPolicy("oauth_consent", 10, 60)

@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    retry_after: int          # whole seconds, >= 1 when refused, 0 when allowed

class SlidingWindowLimiter:
    def __init__(self, policy: RateLimitPolicy, clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 10_000) -> None
    def hit(self, key: str) -> RateDecision      # record + decide (a refused hit is not recorded)
    def peek(self, key: str) -> RateDecision     # decide without recording
    def record(self, key: str) -> None           # record without deciding (failed bearers)

def limiter(policy: RateLimitPolicy) -> SlidingWindowLimiter   # process-wide, one per policy
def reset_limiters() -> None                                   # tests
def source_key(scope: Scope) -> str                            # ASGI client host or "unknown"
def too_many_requests(decision: RateDecision) -> JSONResponse  # 429 + Retry-After

class RateLimitedEndpoint:            # ASGI wrapper around one route endpoint, keyed by source
    def __init__(self, app: ASGIApp, policy: RateLimitPolicy,
                 key: Callable[[Scope], str] = source_key) -> None
class FailedBearerGuard:              # ASGI middleware
    def __init__(self, app: ASGIApp, policy: RateLimitPolicy = BEARER_FAILURES) -> None
class PrincipalRateLimit:             # ASGI middleware, after authentication
    def __init__(self, app: ASGIApp, policy: RateLimitPolicy,
                 key: Callable[[Scope], str | None]) -> None
def rate_limit(policy: RateLimitPolicy,
               key: Callable[[Request], Awaitable[str]]) -> Callable[..., Awaitable[None]]
    # FastAPI dependency: HTTPException(429, headers={"Retry-After": "<n>"})
```

**Behaviour.** Per-key `deque[float]` of hit times; entries older than the window are dropped on
every call; `retry_after = ceil(oldest + window - now)`, at least 1. Keys live in an `OrderedDict`
used as an LRU; beyond `max_keys` the least recently used key is evicted (bounded memory). No
`await` inside `hit`, so it is atomic on the single event loop. `FailedBearerGuard`: if the request
carries `Authorization: Bearer …` and `peek(source)` is refused → 429 before authentication;
otherwise run the app and, when the response status is 401 and a bearer was sent, `record(source)`.
Requests without a bearer are never counted (the first 401 of the OAuth handshake is free).
`PrincipalRateLimit` skips when `key(scope)` is `None`. The 429 body is
`{"error": "rate_limited", "error_description": "Too many requests. Try again in N seconds."}` —
never echoing keys or tokens.

**Steps**

- [ ] **Step 1: Write the failing tests** (`tests/mcp/test_ratelimit.py`, fake clock):
  `test_allows_up_to_the_limit_then_refuses`, `test_the_window_slides`,
  `test_retry_after_counts_down_to_the_oldest_hit`, `test_refused_hits_are_not_recorded`,
  `test_keys_are_independent`, `test_memory_is_bounded`, `test_policies_match_the_design` (D16
  values), `test_429_response_shape` (status, `Retry-After`, body has no key),
  `test_rate_limited_endpoint_wraps_an_asgi_route`,
  `test_failed_bearer_guard_blocks_after_20_failures_and_recovers`,
  `test_failed_bearer_guard_ignores_requests_without_a_bearer_and_successes`,
  `test_principal_rate_limit_keys_by_principal_and_skips_anonymous`,
  `test_fastapi_dependency_raises_429_with_retry_after`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/ratelimit.py backend/tests/mcp/test_ratelimit.py
git commit -m "feat(mcp): in-process sliding-window rate limits"
```

---

### Task 8: Self-service, consent, admin credential and auth-methods APIs

**Group D. Depends on:** Tasks 3 and 4.

**Files:**
- Create: `backend/app/mcp/router.py`, `backend/app/mcp/schemas.py`, `backend/app/mcp/dependencies.py`
- Test: `backend/tests/mcp/api_helpers.py`, `backend/tests/mcp/test_tokens_api.py`,
  `backend/tests/mcp/test_connected_apps_api.py`, `backend/tests/mcp/test_consent_api.py`,
  `backend/tests/mcp/test_admin_credentials_api.py`, `backend/tests/mcp/test_auth_methods.py`

(The access hooks the analysis put here are in Task 3, C6. The consent rate limit is wired in
Task 6.)

**Schemas** (`app/mcp/schemas.py`; analysis §4 shapes, binding for phase 5):

```python
class TokenOut(BaseModel):              # from_attributes
    id: UUID; kind: str; name: str; prefix: str; user_id: UUID; client_id: str | None
    created_at: datetime; expires_at: datetime; last_used_at: datetime | None
    revoked_at: datetime | None; revoked_reason: str | None
class TokenCreatedOut(TokenOut):
    token: str                          # shown once; never in any list response
class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
class ConnectedAppOut(BaseModel):
    family_id: UUID; client_id: str; client_name: str; redirect_host: str
    created_at: datetime; last_used_at: datetime | None; expires_at: datetime
class ClientOut(BaseModel):
    client_id: str; client_name: str; redirect_uris: list[str]; token_endpoint_auth_method: str
    registered_at: datetime; revoked_at: datetime | None; active_families: int
class ConsentPromptOut(BaseModel):
    transaction_id: str; client_name: str; redirect_uri: str; redirect_host: str; loopback: bool
    user_email: str; eligible: bool; ineligible_reason: Literal["no_mcp_use"] | None
    expires_at: datetime
class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")     # nothing else in the body can steer the grant
    transaction_id: str = Field(min_length=20, max_length=100)
    decision: Literal["approve", "deny"]
class ConsentOut(BaseModel):
    redirect_to: str
class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=60); role: str
class ServiceAccountOut(BaseModel):     # access UserOut fields + owner_user_id (phase-5 compatible)
    id: UUID; email: str; display_name: str; kind: str; role: str; status: str
    last_seen_at: datetime | None; owner_user_id: UUID | None
class RevokedOut(BaseModel):
    revoked: int
class CredentialEventOut(BaseModel):
    id: UUID; at: datetime; event: str; user_id: UUID | None; actor_user_id: UUID | None
    via: str; token_id: UUID | None; client_id: str | None; details: dict[str, Any]
class PatMethodOut(BaseModel):
    enabled: bool; default_days: int; max_days: int
class OAuthMethodOut(BaseModel):
    enabled: bool; hosted_connectors: bool
class AuthMethodsOut(BaseModel):
    pat: PatMethodOut; oauth: OAuthMethodOut
```

`client_name` falls back to `"Unnamed client"` in every response.

**Routes** (`mcp_router = APIRouter(prefix="/api/v1", tags=["mcp-auth"])`; all thin — parse, call
an identity service or `AccessAdmin`, map errors, return a schema):

| Route | Gate | Behaviour |
|---|---|---|
| `GET /me/tokens` | `get_principal` | own PATs (`kinds=(PAT,)`), newest first |
| `POST /me/tokens` | `require_capability(TOKENS_CREATE)` | 201 `TokenCreatedOut`; 400 rule, 409 limit; actor `via="api"` |
| `DELETE /me/tokens/{token_id}` | `get_principal` | 204; another user's id → 404 |
| `GET /me/connected-apps` | `get_principal` | live OAuth families |
| `DELETE /me/connected-apps/{family_id}` | `get_principal` | 204; not yours → 404 |
| `GET /oauth/consent/{txn}` | `get_principal` + `get_policy` | `ConsentPromptOut`; 404 unknown/expired/consumed |
| `POST /oauth/consent` | `get_principal` + `get_policy` | approve: no `mcp:use` → 403 `{"detail": {"reason": "no_mcp_use", "message": …}}` (txn untouched); else `ConsentOut`; deny → `ConsentOut` with `error=access_denied`; 404 unknown/expired/consumed |
| `GET /admin/tokens?user_id&kind` | `require_capability(ADMIN_TOKENS)` | tenant-scoped; `kind` ∈ `pat`, `service`, `oauth` (both OAuth kinds) |
| `DELETE /admin/tokens/{token_id}` | `ADMIN_TOKENS` | 204; other tenant → 404; reason `admin_revoked` |
| `POST /admin/users/{user_id}/tokens/revoke-all` | `ADMIN_TOKENS` | `RevokedOut` |
| `POST /admin/service-accounts` | `get_actor` + `get_access_admin` | 201 `ServiceAccountOut` via `AccessAdmin.create_service_account` (it checks `admin:users`) |
| `POST /admin/service-accounts/{user_id}/tokens` | `ADMIN_TOKENS` | 201 `TokenCreatedOut`; D34 check |
| `GET /admin/clients` | `ADMIN_CLIENTS` | `[ClientOut]` |
| `DELETE /admin/clients/{client_id}` | `ADMIN_CLIENTS` | 204 (cascade); unknown → 404 |
| `GET /admin/credential-events?user_id&limit` | `ADMIN_AUDIT` (`access` export) | tenant-scoped, `limit` 1–500, default 100 |
| `GET /meta/auth-methods` | `get_principal` | D22 |

Consent POST (D4, D36; CSRF: the Firebase bearer is required and never sent automatically by a
browser, so a cross-site form cannot approve):

```python
@mcp_router.post("/oauth/consent", response_model=ConsentOut)
async def decide_consent(
    payload: ConsentDecision,
    principal: Principal = Depends(get_principal),
    policy: Policy = Depends(get_policy),
    oauth: OAuthService = Depends(get_oauth_service),
) -> ConsentOut:
    with consent_errors():                       # AuthorizationRequestNotFoundError -> 404
        if payload.decision == "deny":
            return ConsentOut(redirect_to=await oauth.deny(payload.transaction_id, principal.user_id))
        if not policy.has(MCP_USE):
            raise HTTPException(403, {"reason": "no_mcp_use",
                                      "message": "Your role doesn't include MCP access yet."})
        return ConsentOut(redirect_to=await oauth.approve(payload.transaction_id, principal.user_id))
```

The code is bound to `principal.user_id` (from the token), the client, redirect, PKCE and audience
come from the stored request; nothing in the body can change them (`extra="forbid"`). A consumed
txn is 404 for everyone, so nobody can approve someone else's transaction after it was used.

D34 service-token mint (in `dependencies.py` helper `mint_service_token(...)`, called by the route):
target = `principal_for_user(db, user_id)`; it must exist, be `kind=service`, active, and in the
actor's tenant (else 404/400); `target_policy = await policy_for(db, target)`; if
`not target_policy.capabilities <= actor_policy.capabilities` → 403 "You can't mint a token for an
account with more access than your own."

`dependencies.py`: `get_token_service(db)`, `get_oauth_service(db, settings)`, `credential_errors()`
context manager (`CredentialRuleError`→400, `CredentialLimitError`→409,
`CredentialNotFoundError`→404), `consent_errors()`.

**Steps**

- [ ] **Step 1: Write the failing tests** (`tests/mcp/api_helpers.py`: `api_app()` = FastAPI +
  `mcp_router` + the access error handler; `as_user(app, user)` overrides `get_principal`;
  `with_auth_enabled(monkeypatch)` sets `AUTH_DISABLED=false` for 401 tests):
  - `test_tokens_api.py`: `test_create_pat_returns_the_token_once` (POST body has `token`; GET list
    and DB never do), `test_create_pat_needs_tokens_create` (viewer → 403),
    `test_eleventh_pat_is_409`, `test_days_out_of_range_are_rejected`,
    `test_list_shows_only_my_pats`, `test_revoke_my_token`, `test_revoke_someone_elses_token_is_404`,
    `test_extra_fields_are_rejected`, `test_token_never_logged` (`capture_logs`).
  - `test_connected_apps_api.py`: `test_lists_my_live_families_with_redirect_host`,
    `test_disconnect_revokes_the_family` (its access token then fails `authenticate_bearer`),
    `test_cannot_disconnect_someone_elses_family`.
  - `test_consent_api.py`:
    - `test_prompt_shows_client_redirect_host_loopback_and_email`,
      `test_prompt_for_a_hosted_redirect_is_not_loopback`, `test_unnamed_client_is_labelled`.
    - `test_prompt_for_unknown_expired_or_consumed_txn_is_404`.
    - `test_prompt_marks_a_user_without_mcp_use_ineligible`.
    - `test_approve_returns_the_registered_redirect_with_code_and_state` (scheme, host, port, path
      equal the registered URI; `state` echoed; code exchangeable).
    - `test_approve_without_mcp_use_is_403_with_reason_and_keeps_the_txn` (a later approve, after
      the role changes, still works).
    - `test_approve_twice_is_404`.
    - `test_cannot_approve_someone_elses_txn_after_consumption` (A approves; B's POST → 404; no
      second code row).
    - `test_deny_redirects_with_access_denied_and_state`.
    - `test_consent_needs_a_bearer` (auth enabled, no header → 401) and
      `test_consent_ignores_cookies` (cookie only → 401).
    - `test_body_cannot_choose_client_redirect_or_user` (extra fields → 422).
    - `test_disabled_user_and_non_company_account_get_403` (from `get_principal`).
  - `test_admin_credentials_api.py`: `test_admin_lists_tokens_by_user_and_kind`,
    `test_admin_token_routes_need_admin_tokens`, `test_admin_revokes_any_token_in_the_tenant`,
    `test_admin_cannot_see_or_revoke_another_tenants_tokens`, `test_revoke_all_for_a_user`,
    `test_create_service_account_needs_admin_users`, `test_mint_service_token_needs_admin_tokens`,
    `test_mint_refused_for_a_human_or_disabled_account`,
    `test_mint_refused_when_the_account_outranks_the_actor` (D34),
    `test_list_and_revoke_clients_cascades_to_tokens`, `test_client_routes_need_admin_clients`,
    `test_credential_events_need_admin_audit_and_are_tenant_scoped`,
    `test_revocations_land_in_credential_events_not_rbac_changes` (D24).
  - `test_auth_methods.py`: `test_auth_methods_defaults` (`pat` enabled 90/365, `oauth` enabled,
    `hosted_connectors` false), `test_hosted_connectors_with_an_https_public_url`,
    `test_auth_methods_needs_authentication`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/router.py backend/app/mcp/schemas.py backend/app/mcp/dependencies.py \
  backend/tests/mcp/api_helpers.py backend/tests/mcp/test_tokens_api.py \
  backend/tests/mcp/test_connected_apps_api.py backend/tests/mcp/test_consent_api.py \
  backend/tests/mcp/test_admin_credentials_api.py backend/tests/mcp/test_auth_methods.py
git commit -m "feat(mcp): token, connected-app, consent and admin credential APIs"
```

---

### Task 9: Credentials CLI

**Group D. Depends on:** Tasks 3 and 4.

**Files:**
- Create: `backend/app/mcp/cli.py`
- Test: `backend/tests/mcp/test_cli.py`

**Interface.** `python -m app.mcp.cli <command>` (same shape as `app/access/cli.py`: `async def
run(argv: Sequence[str]) -> int`, `main()`, output through `sys.stdout.write`, never `print`; every
write uses `CredentialActor(None, "cli")` or `Actor.cli()`):

| Command | Does |
|---|---|
| `create-pat <email> [--name N] [--days D]` | mint a PAT for an active human (approved default 5); prints `id`, `prefix`, `expires_at`, then the token on its own line, once |
| `create-service-account <name> --role R` | `AccessAdmin.create_service_account(Actor.cli(), …)`; prints the email |
| `create-service-token <service-email> [--name N] [--days D]` | mint `atl_svc_`; printed once |
| `list-tokens [--email E] [--kind pat\|service\|oauth]` | id, kind, name, prefix, owner, expiry, last used, revoked — never secrets |
| `revoke-token <token-id> [--reason R]` | `admin_revoked` by default |
| `revoke-all <email>` | every token of the user |
| `list-clients` / `revoke-client <client-id>` | OAuth clients; revoke cascades |
| `gc` | `OAuthService.gc()`; prints the counts |

Exit codes: 0 ok, 1 domain error (message on stderr, no traceback), 2 usage.

**Steps**

- [ ] **Step 1: Write the failing tests** (`tests/mcp/test_cli.py`, `capsys`):
  `test_create_pat_prints_the_token_once_and_stores_its_hash`,
  `test_create_pat_is_audited_via_cli` (`credential_events.via == "cli"`, `actor_user_id` None),
  `test_create_pat_refuses_unknown_disabled_or_service_users` (exit 1, no token printed),
  `test_create_service_account_then_token`, `test_list_tokens_never_prints_secrets`,
  `test_revoke_token`, `test_revoke_all`, `test_list_and_revoke_clients`, `test_gc_prints_counts`,
  `test_usage_errors_exit_2`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the gate.**
- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp/cli.py backend/tests/mcp/test_cli.py
git commit -m "feat(mcp): credentials CLI"
```

---

### Task 10: OAuth consent page

**Group D. Depends on:** the Task 8 API shapes (fixed in this plan; the page is tested against
mocks, so it does not need Task 8 on disk).

**Files:**
- Create: `frontend/src/features/oauth-consent/index.ts`, `consent-page.tsx`, `consent-api.ts`,
  `use-consent.ts`, `consent-page.test.tsx`, `use-consent.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/vite.config.ts`, `DESIGN.md` (one new
  `consent-panel` component entry next to `sign-in-panel`; CLAUDE.md requires new components in
  DESIGN.md first; run `npx @google/design.md lint DESIGN.md`)

**Interface**

```ts
// index.ts
export { ConsentPage, type ConsentSession } from './consent-page';

// consent-page.tsx
export interface ConsentSession {
  email: string | null;          // null = not signed in
  isLoading: boolean;
  signIn: () => Promise<void>;   // the auth feature's signInWithGoogle, passed in by App.tsx (C4)
}
export function ConsentPage({ session }: { session: ConsentSession }): JSX.Element;

// consent-api.ts (uses `api` from '@/api/axios-instance', which attaches the Firebase token)
export interface ConsentPrompt { transaction_id: string; client_name: string; redirect_uri: string;
  redirect_host: string; loopback: boolean; user_email: string; eligible: boolean;
  ineligible_reason: 'no_mcp_use' | null; expires_at: string; }
export function getConsentPrompt(txn: string): Promise<ConsentPrompt>;
export function submitConsent(txn: string, decision: 'approve' | 'deny'): Promise<{ redirect_to: string }>;

// use-consent.ts
export type ConsentState =
  | { kind: 'missing-txn' } | { kind: 'sign-in' } | { kind: 'loading' }
  | { kind: 'expired' } | { kind: 'blocked'; message: string }       // 403; fixed copy chosen by detail.reason
  | { kind: 'ineligible'; prompt: ConsentPrompt } | { kind: 'ready'; prompt: ConsentPrompt }
  | { kind: 'done' } | { kind: 'error'; message: string };
export function useConsent(txn: string | null, session: ConsentSession): {
  state: ConsentState; decide: (d: 'approve' | 'deny') => Promise<void>; submitting: boolean };
```

**App.tsx (C4)** — the import, a composition wrapper like `Home`, and the route, placed before the
`ProtectedRoute` layout route so the query string survives:

```tsx
import { ConsentPage } from '@/features/oauth-consent';

/** /oauth/consent sits outside ProtectedRoute: it signs in itself and keeps ?txn=. */
function OAuthConsent() {
  const { user, isLoading, signInWithGoogle } = useAuth();
  return <ConsentPage session={{ email: user?.email ?? null, isLoading, signIn: signInWithGoogle }} />;
}
// in <Routes>, right after /login:
<Route path="/oauth/consent" element={<OAuthConsent />} />
```

**vite.config.ts** — dev proxy so the local consent flow is same-origin like nginx:
`'/mcp-server'` and `'/.well-known'` → `process.env.VITE_PROXY_TARGET ?? 'http://localhost:8081'`
(also used for `/api`), `changeOrigin: true`.

**Behaviour** (DESIGN.md tokens and existing `@/ui` primitives only — `Glass`, `BrandMark`,
`Button`, `materialize`, `springDefault`, `withReducedMotion`; no new libraries):
- `txn` from `useSearchParams()`. Missing → "This sign-in link is incomplete. Start again from your
  MCP client."
- Not signed in → the sign-in panel pattern with "Continue with Google" calling `session.signIn`.
- 404 → "This request expired or was already used. Start again from your MCP client."
- 403 from the GET (non-company or disabled) → fixed Atlas copy chosen by the machine
  `detail.reason` (`user_disabled` → "Your Atlas access is disabled. Contact an Atlas admin.",
  `not_company_account` → "Atlas only accepts @yougotagift.com Google accounts.", anything else →
  "This account can't approve MCP access. Contact an Atlas admin."), no buttons. The page never
  renders a backend message.
- Ineligible (`no_mcp_use`) → "Your role doesn't include MCP access yet." and a plain link
  **Request access** to `/account/requests/new?kind=role` (phase 5's route; 404s until then).
- Ready → serif title "**{client_name}** wants to access Atlas", "as {user_email}", the redirect host
  in mono, what approving means (spec §4.1: query data you're permitted to see; under your current
  role and groups; you can disconnect it any time). Loopback redirect → caution notice (`warning`
  token): "This app runs on your computer. Approve only if you just started this from Claude Code
  or another app on this machine." Hosted redirect → "Atlas will send the approval to {host}."
  Buttons **Approve** (primary) and **Deny** (secondary), both disabled while submitting (no double
  submit).
- After approve/deny: navigate with `window.location.assign(redirect_to)` **only if** the
  `redirect_to` origin and path equal the prompt's `redirect_uri` (defence in depth; otherwise show
  an error). Approve shows "Authentication successful. Return to Claude Code." while redirecting.
- No numbers or data on the page; works in light, dark, reduced motion, reduced transparency.

**Steps**

- [ ] **Step 1: Write the failing tests** (Vitest + Testing Library; mock `./consent-api`;
  `window.location.assign` stubbed):
  - `consent-page.test.tsx`: `shows client name, user email and redirect host`,
    `warns for a loopback redirect`, `names the host for a hosted redirect`,
    `approve submits and navigates to the redirect`, `deny navigates with access_denied`,
    `refuses to navigate when redirect_to is not the registered redirect`,
    `disables both buttons while submitting`,
    `ineligible user sees Request access linking to /account/requests/new?kind=role`,
    `expired or used request shows the start-again message`,
    `blocked account shows fixed copy (never the backend message) and no buttons`,
    `signed-out visitor sees Continue with Google and it calls signIn`,
    `missing txn shows the incomplete-link message`, `renders on glass` (`[data-glass]`).
  - `use-consent.test.tsx`: state transitions for 401 → `sign-in`, 403 → `blocked`, 404 →
    `expired`, eligible → `ready`, `no_mcp_use` → `ineligible`, approve 403 → `ineligible`.
- [ ] **Step 2: Run to verify they fail** (`corepack pnpm test -- oauth-consent`).
- [ ] **Step 3: Implement**; add the DESIGN.md `consent-panel` entry; lint DESIGN.md.
- [ ] **Step 4: Gate** — `cd frontend && COREPACK_INTEGRITY_KEYS=0 corepack pnpm -s check`
  (format, lint incl. the feature-import rule, typecheck, tests, build). The backend gate is
  unaffected but run it once if any backend file changed.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/oauth-consent frontend/src/App.tsx frontend/vite.config.ts DESIGN.md
git commit -m "feat(frontend): OAuth consent page"
```

---

### Task 11: Deploy configuration and documentation

**Serialized after Task 6. Depends on:** Task 6.

**Files:**
- Modify: `frontend/nginx.conf`, `backend/.env.example`, `README.md`, `ARCHITECTURE.md`,
  `CLAUDE.md`, `docs/specs/2026-10-08-auth-rbac-design.md` (own sections only, contracts)
- Test: `backend/tests/test_deploy_config.py`

**nginx** (as built; validated with `nginx -t` and a header and log smoke test in `nginx:alpine`):
- `location /mcp-server/` and `location ^~ /.well-known/oauth-` proxy to `backend:8081` with
  `proxy_set_header Host $http_host` (keeps the port for the DNS-rebinding check, C1/D26),
  `proxy_buffering off` and `proxy_cache off`; `/mcp-server/` keeps the 3600 s timeouts for SSE.
- `location ~ ^/oauth/consent/?$` (with or without a trailing slash) serves `index.html` with
  `X-Frame-Options: DENY`,
  `Content-Security-Policy: frame-ancestors 'none'`, `Referrer-Policy: no-referrer` and
  `Cache-Control: no-store`. `location /` (the SPA shell) also sends `X-Frame-Options: DENY` and
  `frame-ancestors 'none'` (headers are set per location, because a location with its own
  `add_header` drops the server-level ones).
- The txn never reaches nginx logs: an `atlas` `log_format` logs a mapped URI (`/oauth/consent`
  without its query or trailing slash, via `~^/oauth/consent(/|[?#]|$)`;
  `/api/v1/oauth/consent/-` instead of the txn path) and a mapped Referer (`-` for any
  consent-page referer, and `"" -` for an empty one), so the SPA route keeps its access log. `location ^~
  /api/v1/oauth/consent` (no trailing slash: a prefix ending in `/` would 301 the POST) sets
  `error_log … crit`, because upstream error lines echo the raw request line.

**`.env.example`:** add `ATLAS_PUBLIC_URL=http://localhost:8080` (with the 4b note),
`OAUTH_HOSTED_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback`, `PAT_DEFAULT_DAYS=90`,
`PAT_MAX_DAYS=365`; remove `ATLAS_MCP_TOKEN` and `MCP_SERVICE_EMAIL` (leftover values on the box are
ignored: `extra="ignore"`).

**README (MCP section):**
- Claude Code through the tunnel: `claude mcp add --transport http atlas
  http://localhost:8080/mcp-server/mcp`, then `/mcp` → Authenticate → approve in the browser.
  `claude mcp login atlas` re-authenticates.
- Scripts and CI: an admin mints a token on the box: `docker compose exec backend uv run python -m
  app.mcp.cli create-pat <email> --name ci` (or `create-service-account` + `create-service-token`);
  use it with `claude mcp add --transport http atlas http://localhost:8080/mcp-server/mcp --header
  "Authorization: Bearer ${ATLAS_PAT}"`.
- Who can connect: `mcp:use` (analyst and above); revoking: `/me/connected-apps`, `/me/tokens`,
  admin routes, CLI; disabling a user revokes everything.
- 4b checklist (configuration only): DNS + TLS, `ATLAS_PUBLIC_URL=https://<host>`, Firebase
  authorized domain, `CORS_ORIGINS`, firewall for `160.79.104.0/21` and the office, uvicorn
  `--proxy-headers --forwarded-allow-ips=<nginx>` for per-source limits; existing OAuth clients
  re-authenticate once, PATs survive.
- Deploy notes for this PR: shared-token users must switch (announce; mint PATs first), migration
  0005 disables `mcp-shared@atlas.internal`.

**ARCHITECTURE.md:** §2.1 table gains "MCP follows its layering" → "MCP module layering"; §6 removes
the "MCP uses one shared token" row and the `[tool.pyright].strict` row lists `mcp`; adds debt rows:
"Per-source rate limits are global behind nginx (no trusted proxy headers)" → "Trust the nginx IP
at 4b", and "Consent is not bound to the initiating browser" → "Add an HttpOnly txn cookie before
hosted connectors (4b)".

**CLAUDE.md:** guardrail 4 adds: "MCP callers use atlas-issued tokens (OAuth, PAT or service),
stored only as hashes; the MCP door never honours `AUTH_DISABLED`."

**Spec:** a "Phase 4 deltas" note under §14 recording D8–D15 and D22–D24: no `scope_narrowing`
column, token/client revocations in `credential_events` (not `rbac_changes`),
`/me/connected-apps` (not `/me/clients`), CIMD deferred, consent route `/oauth/consent`, PATs open
the MCP door only, service accounts `svc-<slug>@atlas.internal`, §16 answers (SDK 1.30.0 provides
handlers; redirect URIs; Claude Code DCR).

**Steps**

- [ ] **Step 1: Write the failing test** (`tests/test_deploy_config.py`, text checks):
  `test_nginx_proxies_mcp_and_discovery_with_the_port` (both locations, `$http_host`, buffering off
  for `/mcp-server/`), `test_discovery_location_covers_every_backend_discovery_path`,
  `test_consent_page_is_not_frameable_or_logged`,
  `test_env_example_has_the_public_url_and_no_shared_token`.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Edit the config and docs.**
- [ ] **Step 4: Run the gate**; also `timeout 60 docker run --rm --add-host backend:127.0.0.1 -v
  "$PWD/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t`.
- [ ] **Step 5: Commit**

```bash
git add frontend/nginx.conf backend/.env.example README.md ARCHITECTURE.md CLAUDE.md \
  docs/specs/2026-10-08-auth-rbac-design.md backend/tests/test_deploy_config.py
git commit -m "chore(deploy): nginx MCP locations and MCP authentication docs"
```

---

### Task 12: Full gate and manual verification

**Serialized last. Depends on:** Tasks 1–11.

**Files:**
- Create: `backend/scripts/mcp_oauth_smoke.py` (kept: it re-verifies 4b against the public URL)
- Modify: only files whose bugs the verification finds, each fix with its failing test first and its
  own commit.

**Local environment** (never touches the shared DB, EC2 or a source DB):

```bash
# 1. Throwaway Postgres on a free port (check first)
lsof -iTCP:5437 -sTCP:LISTEN || echo free
docker run -d --name atlas-p4-pg -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \
  -e POSTGRES_DB=ygg_atlas_p4 -p 5437:5432 postgres:16-alpine
docker exec atlas-p4-pg createdb -U atlas ygg_atlas_p4_test   # separate DB for the DROP-SCHEMA tests

# 2. Backend env (shell exports; the worktree has no backend/.env)
export DATABASE_URL=postgresql+asyncpg://atlas:atlas@localhost:5437/ygg_atlas_p4
export APPDB_URL=$DATABASE_URL ENVIRONMENT=development AUTH_DISABLED=true
export ATLAS_PUBLIC_URL=http://localhost:5173 CORS_ORIGINS=http://localhost:5173
cd backend && uv run alembic upgrade head && uv run python scripts/seed_demo.py
uv run uvicorn app.main:app --port 8081 &          # VITE_PROXY_TARGET if 8081 is taken

# 3. Dev user with MCP access (AUTH_DISABLED's dev user is a viewer; no admin bypass)
curl -s localhost:8081/api/v1/me >/dev/null       # creates dev@yougotagift.com
uv run python -m app.access.cli set-role dev@yougotagift.com analyst
uv run python -m app.access.cli grant user:dev@yougotagift.com allow '*' --reason "local p4 check"

# 4. Frontend (same origin as ATLAS_PUBLIC_URL via the Vite proxy)
cd ../frontend && VITE_AUTH_DISABLED=true COREPACK_INTEGRITY_KEYS=0 corepack pnpm dev --port 5173 &
```

**How consent works locally:** with `AUTH_DISABLED=true` (allowed only with
`ENVIRONMENT=development|test`, `config.py` validator), `get_principal` returns the dev principal
without any bearer (`identity/dependencies.py:52-53`, `IdentityService.ensure_dev_user`), and the
SPA with `VITE_AUTH_DISABLED=true` shows `DEV_USER` and sends no token. So the consent GET/POST run
as `dev@yougotagift.com` and the whole OAuth flow is exercisable. **Not exercisable locally:** the
Google sign-in branch of the consent page and the "Firebase bearer required" property (under
`AUTH_DISABLED` the consent POST needs no bearer at all — development only; production refuses
`AUTH_DISABLED`). Those are covered by the Vitest sign-in test and `test_consent_needs_a_bearer`,
and get a manual look after the user-approved deploy. The MCP door itself never honours
`AUTH_DISABLED` (D33), so tokens are real everywhere.

**Steps**

- [ ] **Step 1: Smoke script.** `scripts/mcp_oauth_smoke.py --base-url http://localhost:5173` (httpx,
  `print` allowed in `scripts/`), each step asserting and printing `PASS <step>`; tokens printed
  only as display prefixes:
  1. `POST /mcp-server/mcp` without a bearer → 401; parse `resource_metadata` from
     `WWW-Authenticate`.
  2. GET the PRM → `resource == <base>/mcp-server/mcp`; GET AS metadata at
     `/.well-known/oauth-authorization-server/mcp-server` → `none` and `S256` advertised.
  3. `POST /register` (public client, redirect `http://localhost:<free port>/callback`) → 201.
  4. `GET /authorize` (S256 challenge, `state`, `resource`) → 302 to `/oauth/consent?txn=…`.
  5. `GET /api/v1/oauth/consent/<txn>` → prompt (dev user, loopback); `POST /api/v1/oauth/consent`
     approve → `redirect_to` with `code` and the same `state`.
  6. `POST /token` (form) → access + refresh.
  7. MCP `initialize`, `tools/list` (expect the 7 tools for the dev user), `tools/call
     list_metrics` → data.
  8. `POST /token` refresh → new pair; replay the old refresh after 31 s → `invalid_grant`; the
     new access token now → 401.
  9. Re-authorize (steps 3–6), then `POST /revoke` the refresh → 200; access → 401.
  10. Replay a used code → `invalid_grant`.
  11. PAT: mint one beforehand (`uv run python -m app.mcp.cli create-pat dev@yougotagift.com
      --name smoke`) and pass it as `ATLAS_PAT` → `tools/list` with `Authorization: Bearer <pat>`
      → 200; a second PAT revoked beforehand (`revoke-token`) passed as `ATLAS_REVOKED_PAT` →
      `initialize` and `tools/list` → 401.
  12. Rate limit (opt-in, `--check-register-limit --allow-shared-impact`): 11th `/register`
      within the hour → 429 with `Retry-After`.
- [ ] **Step 2: Claude Code, by hand** (this machine; OAuth to localhost is allowed):
  `claude mcp add --transport http atlas-p4 http://localhost:5173/mcp-server/mcp` → in Claude Code
  `/mcp` → atlas-p4 → Authenticate → browser shows the consent page (check client name, redirect
  host `localhost:<port>`, loopback warning, dev email) → Approve → "Authentication successful" →
  ask "list the atlas metrics" → answer with data. Check the audit row:
  `psql … -c "select auth_method, token_id, client_id from atlas_audit_log order by created_at
  desc limit 3"` (`oauth`, both ids set). `GET /api/v1/me/connected-apps` → `DELETE` it → the next
  tool call fails → Claude Code re-authenticates successfully. Then the PAT path:
  `claude mcp add --transport http atlas-p4-pat http://localhost:5173/mcp-server/mcp --header
  "Authorization: Bearer ${ATLAS_PAT}"` → a tool call works. Remove both servers afterwards
  (`claude mcp remove …`). Optional: MCP Inspector (`npx @modelcontextprotocol/inspector`) in proxy
  mode against the same URL.
- [ ] **Step 3: Visual check of the consent page** in light and dark (headless Chrome recipe in
  memory: `--screenshot`, `preferredColorScheme=0/1`) with a live `txn`; also the ineligible state
  (temporarily `set-role … viewer`).
- [ ] **Step 4: `make check`** from the repo root (backend gate with coverage + frontend check).
- [ ] **Step 5: Opt-in Postgres tests** on the separate test DB:
  `TEST_PG_URL=postgresql+asyncpg://atlas:atlas@localhost:5437/ygg_atlas_p4_test uv run pytest
  tests/test_alembic_postgres.py tests/test_access_postgres.py tests/test_mcp_auth_postgres.py
  -p no:xdist -q` — includes model ≡ migration drift on PG,
  `test_concurrent_code_exchange_exactly_one_wins`, the concurrent refresh grace and the concurrent
  consent tests.
- [ ] **Step 6: Evals regression** (no agent behaviour changed): `cd backend && uv run python
  ../evals/run_evals.py` with an LLM key taken from `backend/.env` of the main checkout into the
  environment (never printed) and the seeded DB URLs. Baseline 15/15 demo goldens; rerun once
  before acting on a single failure. If no key is available, report evals as **not run**.
- [ ] **Step 7: nginx syntax** (if not done in Task 11) and **cleanup**: stop uvicorn and Vite,
  `docker rm -f atlas-p4-pg`.
- [ ] **Step 8: Commit** the smoke script (and any fixes as separate `fix(...)` commits):

```bash
git add backend/scripts/mcp_oauth_smoke.py
git commit -m "test(mcp): OAuth smoke script for local and 4b verification"
```

Report: gate results, PG results, evals result, smoke output, Claude Code result, screenshots
taken, open issues.

---

## Security bar → tests

| Requirement | Tests (task) |
|---|---|
| PKCE S256 only | `test_plain_or_malformed_challenge_is_rejected` (4); `test_authorize_refuses_plain_pkce`, `test_authorize_refuses_a_missing_challenge`, `test_wrong_pkce_verifier_is_invalid_grant` (5); smoke step 4–6 (12) |
| Single-use codes; reuse revokes the family | `test_mark_code_used_succeeds_once` (2); `test_code_is_single_use_and_reuse_revokes_the_family` (4); `test_code_replay_over_http_revokes_the_tokens` (5); `test_concurrent_code_exchange_exactly_one_wins` (4, PG); smoke step 10 |
| Refresh rotation, 30 s same-client grace, cross-client no grace | `test_refresh_rotates_and_revokes_the_old_token`, `test_same_client_retry_within_30s_gets_a_fresh_pair`, `test_same_client_reuse_after_30s_revokes_the_family`, `test_cross_client_reuse_revokes_the_family_without_grace`, `test_grace_never_revives_a_revoked_family` (4); `test_refresh_retry_within_grace_over_http`, `test_refresh_from_another_client_is_invalid_grant_and_revokes` (5); `test_concurrent_refresh_same_client_both_succeed_within_grace` (4, PG) |
| Audience binding | `test_canonical_resource`, `test_missing_resource_is_bound_to_the_mcp_url`, `test_foreign_resource_is_rejected`, `test_refresh_rechecks_the_audience` (4); `test_authorize_foreign_resource_redirects_invalid_request_with_state` (5); `test_token_for_another_audience_is_401` (6) |
| Redirect allowlist (loopback any port/path incl. `http://localhost:35535/oauth/callback`, `[::1]`, `127.0.0.1`; `https://claude.ai/api/mcp/auth_callback`; reject http non-loopback, `localhost.evil.com`, userinfo) | `test_loopback_redirects_are_allowed`, `test_the_hosted_callback_is_allowed`, `test_other_redirects_are_rejected`, `test_get_client_drops_redirects_the_allowlist_no_longer_allows` (4); `test_register_accepts_the_desktop_loopback_callback`, `test_register_rejects_a_non_allowlisted_redirect` (5) |
| Hashed secrets only | `test_token_hash_is_unique` (2); `test_create_pat_stores_only_the_hash` (3); `test_registration_stores_only_the_secret_hash`, `test_begin_returns_the_consent_url_with_a_txn_and_stores_its_hash` (4); `test_only_the_secret_hash_is_stored`, `test_get_client_never_returns_a_secret` (5); `test_create_pat_prints_the_token_once_and_stores_its_hash` (9) |
| Raw tokens never in logs, audit rows, error bodies, reprs | `test_rejections_never_echo_the_token` (3); `test_no_secret_reaches_events_or_logs` (4); `test_access_token_repr_and_json_hold_no_secret`, `test_verifier_fails_closed_on_unexpected_errors`, `test_no_secret_in_logs_or_error_bodies` (5); `test_no_secret_in_logs_audit_or_bodies_end_to_end`, `test_429_has_retry_after_and_no_secret` (6); `test_token_never_logged` (8); `test_list_tokens_never_prints_secrets` (9) |
| Rate limits (429 + Retry-After) | Task 7 unit tests; `test_*_429_*` in `test_rate_limited_routes.py` (6); smoke step 12 |
| Consent CSRF / fixation | `test_consent_needs_a_bearer`, `test_consent_ignores_cookies`, `test_body_cannot_choose_client_redirect_or_user`, `test_approve_twice_is_404`, `test_cannot_approve_someone_elses_txn_after_consumption`, `test_approve_returns_the_registered_redirect_with_code_and_state` (8); `test_approve_is_single_use`, `test_redirect_is_the_registered_uri` (4); `test_concurrent_consent_approve_exactly_one_code` (4, PG); `refuses to navigate when redirect_to is not the registered redirect` (10); nginx `X-Frame-Options` (11) |
| Disabling a user revokes tokens | `test_disabling_a_user_revokes_all_their_tokens`, `test_disabled_user_is_refused_even_if_revocation_failed` (3); `test_user_disabled_mid_session_is_401` (6) |
| Failures collapse to "unavailable" | `test_verifier_fails_closed_on_unexpected_errors`, `test_eligibility_fails_closed` (5); `test_run_tool_collapses_failures_to_unavailable`, `test_list_tools_fails_closed_on_policy_errors` (6) |
| `tools/list` filtering | `test_list_tools_*`, `test_a_tool_missing_from_the_table_is_never_listed` (6) |
| 401 handshake with `resource_metadata` | `test_unauthenticated_call_is_401_with_resource_metadata` (6); smoke step 1 |
| Shared token retired | `test_the_shared_token_is_gone` (6); `test_0005_disables_the_shared_mcp_user_and_bumps_the_version` (2) |

## Risks

| Risk | Mitigation |
|---|---|
| Claude's DCR redirect rejected | Loopback any port/path; manual Claude Code run (Task 12) |
| Discovery path mismatch | Both AS metadata URLs; exact 401 header test; smoke script |
| 421 behind nginx or at 4b (C1) | D26 + `$http_host`; `test_host_header_without_port_is_accepted_and_foreign_host_is_421` |
| Concurrent refresh | 30 s same-client grace; PG test |
| Audience switch at 4b | `invalid_grant` → one re-auth; PATs survive (D7) |
| Token leakage | D28 carriers, hash-only storage, no `logger.exception` with secrets in scope, leak tests |
| Consent phishing once hosted callbacks exist (a victim approves an attacker-started txn that redirects to the attacker's claude.ai) | Consent shows client, host, email and a "did you start this" warning; txn 10 min and single use; **before 4b**: bind the txn to the initiating browser with an HttpOnly cookie set on `/authorize` (ARCHITECTURE §6 debt row) |
| `txn` in access logs (`GET /api/v1/oauth/consent/{txn}`, uvicorn) | 10-minute, single-use, approval binds the approver not the logger; nginx logs a redacted URI and Referer for the SPA route and the consent API, and `Referrer-Policy: no-referrer` on the consent page (Task 11); uvicorn's own access log still prints the path inside the backend container: acceptable for 4a |
| Per-source limits global behind nginx (C15, E1): private, loopback and link-local peers are "unknown", so `/token`, `/authorize` and `/register` share one global key each and the failed-bearer guard only logs; `/register` 10/h for a team | Documented (README, ARCHITECTURE §6); at 4b uvicorn `--proxy-headers --forwarded-allow-ips=<compose subnet>` keys by client IP |
| `error_log … crit` on `location ^~ /api/v1/oauth/consent` hides that location's upstream errors (502, 504, timeouts) from the nginx error log, because those lines echo the raw request line with the txn | Diagnose consent failures from the backend's structured logs (`mcp.consent_*`) and the access log status; lower the level only temporarily, on the box, while debugging |
| Shared-token users break at deploy | README deploy note; mint PATs before deploying; deploy only on the user's "deploy" |
| Rebase onto phase 3 (hotspots `audit.py`, `tools.py`, `models`, `admin.py`, `config.py`, `main.py`, `pyproject.toml`, migration chain) | Appended columns, one-method/one-statement edits, `down_revision` comment; coordinator re-runs alembic tests on SQLite and PG |
| Coverage | Every task carries tests; `app/mcp` no longer omitted; `fail_under=80` |

## Done when

- [ ] All 12 tasks committed (signed), each with its tests written first.
- [ ] `make check` green; opt-in PG tests green; evals at baseline (or reported not run).
- [ ] Claude Code connects through OAuth and through a PAT locally; revoke → 401 → re-auth works.
- [ ] No `ATLAS_MCP_TOKEN`, `BearerTokenMiddleware`, `service_principal`, `mcp_service_email` left
  (`grep -rn` in `backend/app`, `README.md`, `.env.example`).
- [ ] `production-code-review` verdict PASS (or PASS WITH WARNINGS with the warnings listed).

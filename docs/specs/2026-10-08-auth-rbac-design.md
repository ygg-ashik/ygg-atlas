# Authentication and fine-grained access control

**Date:** 2026-10-08 · **Status:** Approved in brainstorm, pending spec review · **Branch:** `feature/auth-rbac`
**Depends on:** MVP design, source-plugin architecture (both 2026-09-23)

## 1. Goal

Every person and service that uses atlas, in the web chat or over MCP from Claude Code, claude.ai,
Claude Desktop or another agent, is identified individually and can see and do only what an
administrator has granted. Access is controlled at four levels: **capability, catalog, row and
field**. Revocation takes effect on the next request on every surface. Every decision is audited.

### Decisions taken in the brainstorm

| Topic | Decision |
|---|---|
| Granularity | All four levels in v1: capability, catalog, row, field |
| Onboarding | Any `@yougotagift.com` Google account can sign in. The user row is created automatically with **no data access**; the user sees **Request access** |
| MCP clients | Interactive staff (Claude Code, claude.ai, Desktop, IDEs), internal services, and external clients later (the design must not block them) |
| MCP sign-in | **OAuth 2.1 browser flow for every interactive MCP client, Claude Code included.** Personal access tokens only as a fallback for clients without OAuth, scripts and CI |
| Engine | Atlas owns the policy (Postgres + one evaluator). No permissions in Firebase claims; no external authorization service in v1 |
| Structure | **Roles** (hierarchical capability bundles) answer *what can you do*. **Groups** (a tree with inheritance) answer *what can you see* |
| Overrides | Direct user grants are allowed (reason required, optional expiry). Grants can **allow or deny; deny always wins** |
| Field masking | Mode configurable per label class: pseudonymise, suppress or bucket |

### Reference and what we deliberately do differently

`atwork_agent_fe` was studied (2026-10-08). Kept: the `resource:action` capability vocabulary, the
`require_*` dependency helpers, fail-closed scope resolution, and scope injected server-side only.
Not copied:
- permissions in JWT claims (stale up to an hour, and the 1,000-byte claim limit);
- Firestore as the user store;
- invited users who cannot be pre-assigned;
- session expiry enforced only in the browser;
- no token revocation;
- no RBAC audit;
- superadmin bypasses scattered through the code;
- a frontend permission manifest duplicated by hand.

## 2. Concepts

| Concept | Meaning |
|---|---|
| **Principal** | The authenticated caller of one request: `{user_id, email, kind: human\|service, auth_method: web\|oauth\|pat\|service, token_id?, client_id?, tenant}` |
| **Role** | Exactly one per user. A cumulative bundle of capabilities: `viewer < analyst < builder < admin` |
| **Capability** | A code-defined action permission, e.g. `chat:use`, `mcp:use` |
| **Group** | A node in a tree. Holds data grants and inherits all of its ancestors' grants |
| **Grant** | `subject (group or user) × effect (allow or deny) × target (capability, resource path or clearance)`, with an optional row scope, expiry and reason |
| **Resource path** | `source/entity/item`, e.g. `deepsales/ds_task/ds_open_tasks`. Wildcards per segment: `deepsales/*`, `deepsales/ds_task/*` |
| **Policy** | The effective, evaluated access of one principal at one `policy_version`. The only object enforcement code consults |

**Resource paths and patterns** (`app/access/patterns.py`):

- A resource path is always 2 or 3 segments: `source/entity` (an entity) or `source/entity/item`
  (a metric, funnel or other item).
- A trailing `*` covers its own prefix and everything under it: `demo/order/*` matches `demo/order`
  and `demo/order/revenue`; `demo/*` matches every `demo` entity and every item under them;
  a lone `*` matches everything. A `*` elsewhere matches exactly one segment (`demo/*/revenue`).
- A literal pattern (no trailing `*`) must be a full 3-segment item path. `demo` or `demo/order`
  are rejected with a hint to use `demo/*` or `demo/order/*`, so a deny never leaves anything
  under the denied path reachable.
- Trade-off: there is no entity-only grant. An entity becomes visible through its items (any
  allowed item under it makes the entity discoverable); `demo/order/*` grants the entity and all
  of its items together.

## 3. Authentication

### 3.1 The doors

All doors produce a Principal through `identity.authenticate(request)`. Downstream code never sees
raw tokens.

| Door | Clients | Credential | Lifetime |
|---|---|---|---|
| Web | Atlas chat and admin UI | Firebase ID token from Google sign-in, verified each request | Session capped at **24h from `auth_time`**, enforced server-side |
| MCP OAuth 2.1 | Claude Code, claude.ai, Claude Desktop, other OAuth-capable MCP clients | Atlas-issued access token | Access 1h; refresh 30 days, rotating |
| MCP PAT (fallback) | Clients without OAuth, scripts, CI | Personal access token `atl_pat_…`, shown once | Default 90 days, maximum 365 |
| Service | Internal services and agents | Service token `atl_svc_…` belonging to a service user | Maximum 365 days, rotation required |

Token prefixes: `atl_oat_` (OAuth access), `atl_ort_` (OAuth refresh), `atl_pat_`, `atl_svc_`.
All tokens are 256-bit random values stored only as SHA-256 hashes.

### 3.2 Checks on every request (all doors)

1. Credential valid, not expired, not revoked.
2. Web only: the email domain is `yougotagift.com` and `auth_time` is under 24h old.
3. User exists and `status = active`. Status is part of the cached Policy, so a status change
   (which increments `policy_version`) takes effect on the next request on every worker.
4. The door's capability is present in the Policy: `chat:use` for web chat, `mcp:use` for MCP. A
   token never carries permissions. Exception: `/me`, `/me/requests` and the Request access page
   need only an authenticated, active user, so a user with no capabilities can still ask for access.
5. Effective rights = the user's current Policy ∩ the token's scope narrowing, if any.

Disabling a user revokes all of their atlas tokens and their Firebase refresh tokens.

### 3.3 Onboarding and bootstrap

- First Google sign-in on any door creates `users(status=active, role=viewer)` with no groups, then
  shows **Request access**.
- `ATLAS_BOOTSTRAP_ADMINS` (comma-separated emails) is applied idempotently at startup, by
  `app.access.prepare_access` under its startup advisory lock: a listed email with no user yet is
  created with `role=admin`, recorded in `rbac_changes` (`via="bootstrap"`, no actor) and committed
  with the `policy_version` bump. **An existing user's role is never changed** (a demoted admin
  stays demoted across restarts; a service identity is never elevated); the skip is logged as
  `identity.bootstrap_admin_skipped`. Promote an existing user with the audited CLI (`set-role`).
  This is the only way to create the first admin.
- **The app refuses to start when `AUTH_DISABLED=true` and `ENVIRONMENT=production`.**

## 4. Flows

### 4.1 MCP in Claude Code (also claude.ai and Desktop)

```
claude mcp add --transport http atlas https://<atlas-host>/mcp
/mcp → atlas: needs authentication → Authenticate → browser opens
  1. Atlas sign-in page: "Sign in with Google" (company accounts only; skipped if already signed in)
  2. Backend checks: domain · user exists (auto-create) · active · role includes mcp:use
  3. Approve screen: "<client name> wants to access atlas as <email>
                      · query data you are permitted to see · under your current role and groups"
                     [Approve] [Deny]
  4. Approve → authorization code → client exchanges it (PKCE) → tokens bound to the user
     Browser: "Authentication successful. Return to Claude Code."
  5. Every tool call: policy check (catalog, row scope, field masking) and audit
```

Denials at step 2 end the flow with a clear page and leave the client disconnected:

| Condition | Page |
|---|---|
| Non-company Google account | "Use your @yougotagift.com account." |
| User disabled | "Your atlas access is disabled. Contact an admin." |
| Role lacks `mcp:use` | "Your role doesn't include MCP access yet." with **Request access** (creates an access request) |

The same checks re-run on every refresh-token exchange.

### 4.2 Web chat

Google sign-in, then the §3.2 checks. With no groups the user sees Request access; otherwise the
chat. Every question is enforced exactly like MCP step 5.

### 4.3 OAuth 2.1 conformance (MCP authorization spec)

- Protected-resource metadata (RFC 9728) served for the MCP endpoint.
- Authorization-server metadata (RFC 8414) at `/.well-known/oauth-authorization-server`.
- Dynamic client registration (RFC 7591). Redirect URIs are restricted to an allowlist: the
  Anthropic callback hosts and loopback (`http://localhost:*`, `http://127.0.0.1:*`).
- Authorization code + **PKCE S256 only**. Resource indicators (RFC 8707): the audience is the atlas
  MCP URL.
- Refresh-token rotation with **reuse detection**: reuse of a rotated refresh token revokes the
  whole token family.
- Registered clients are listed in the admin UI and can be revoked; revoking a client revokes its
  tokens.

## 5. Authorization

### 5.1 Roles and capabilities

Capabilities are defined in code and synced to the database at startup (new ones added, removed ones
marked deprecated and ignored). The frontend reads the catalog from `/meta/capabilities`; nothing is
duplicated by hand.

| Role | Includes | Adds |
|---|---|---|
| viewer | — | `chat:use` |
| analyst | viewer | `mcp:use`, `tokens:create`, `export:data`, `sandbox:run` |
| builder | analyst | `alerts:manage`, `schedules:manage`, `analyses:save` |
| admin | builder | `admin:users`, `admin:groups`, `admin:audit`, `admin:tokens`, `admin:clients` |

Capabilities for features not built yet (sandbox, alerts, schedules, analyses, export) are defined
now and enforced when those features ship.

### 5.2 Groups

- A tree: each group has at most one parent. Cycles are rejected on write.
- A group holds data grants (resource paths with optional row scopes) and field clearances. **Groups
  do not grant capabilities**; capabilities come from the role plus user overrides.
- Members have `member` or `manager` standing. Managers can add and remove members of their group
  and its descendants, and approve **group** access requests for them. **Role** requests (e.g.
  viewer → analyst for MCP) are decided only by users with `admin:users`. Managing grants needs
  `admin:groups`.
- Groups are tenant-scoped. A group's grants never cross tenants.

### 5.3 Grants

| Field | Values |
|---|---|
| subject | group or user |
| effect | `allow` or `deny` |
| target_kind | `resource` (path pattern), `clearance` (label class), `capability` (user subjects only) |
| target | e.g. `deepsales/*`, `fields:people_names`, `export:data` |
| row_scope | JSON, resource allows only: `{dimension: [values or "$self"]}` |
| reason | free text; **mandatory for user-subject grants**, optional for group grants |
| expires_at | optional on any grant; expired grants are ignored by the evaluator |

Grants are unique per `(subject, effect, target_kind, target)` (`uq_grants_subject_target`). An
expired duplicate still occupies that slot: revoke it before granting the same target again.

**Admin write rules (decision D10).** These hold for every admin write through the API (the CLI is a
trusted operator on the box and skips them):

- No self-grants, and no lifting a deny on yourself.
- Grant or lift only capabilities you hold yourself.
- Assign only roles whose capabilities are within your own.
- You cannot change the role or status of a user whose effective capabilities exceed yours. A
  disabled target is judged by the capabilities it would have if it were active.
- You cannot change your own role or status (`_not_self` in `app/access/admin.py`, a 409).
- Managers cannot change their own membership: joining a group, changing your own standing or
  leaving a group yourself needs `admin:groups` (manager standing is not enough).
- Removing anyone from a group needs `admin:groups` when that group or any of its ancestors holds a
  live deny (or a malformed grant): membership carries those grants, so removal lifts them. Expiry is
  judged as the evaluator judges it.
- Adding a **service** user (the shared MCP identity) to a group needs `admin:groups`: whatever the
  group holds becomes reachable to every caller of that door.
- Revoking a deny on a group you belong to is allowed for an `admin:groups` holder: like the
  carve-out below, it is group-mediated, so it is not a self-grant.
- D10 covers **direct** grants. Widening access through a group (an `admin:groups` holder granting
  their own group, joining a group that already holds grants, or lifting a group deny) is reserved
  for `admin:groups` holders and is visible in, and relies on, the `rbac_changes` audit trail.
  Managers (D8) only add and remove plain members of their subtree, never themselves, never a
  service user, and never out from under a deny.

**Write discipline.** Every admin write (API and CLI) takes a row lock on `policy_state` first, so
writes serialize. The actor's authority is judged against the Policy resolved at request start; under
the lock, that Policy's `policy_version` must still be the current one. If any access change
committed in between (the actor may have been disabled or demoted meanwhile), the write is refused
with a 409 ("Access changed while this request was running; retry.") and nothing is written. The
trusted CLI actor has no Policy to go stale and skips this check. No-op writes take the same path.

### 5.4 Evaluation (the single function `access.policy_for(principal)`)

1. **Capabilities** = the role's bundle ∪ user capability allows − user capability denies.
2. **Applicable grants** = grants on the user's groups and all their ancestors, plus direct user
   grants, excluding expired grants.
3. **For a resource R:** if any applicable `deny` pattern matches R, R is denied. Otherwise R is
   allowed iff any applicable `allow` matches.
4. **Row scope for R:** if any matching allow has no `row_scope`, rows are unrestricted. Otherwise the
   scope is the OR of the matching allows' scopes; within one scope, dimensions are ANDed.
5. **Clearances** = union of clearance allows − any clearance denies.
6. The tenant is always an implicit row-scope dimension.

The admin role is an ordinary role. There is no bypass anywhere except through what the role and
grants say.

### 5.5 Row scopes

Declared per entity in plugin YAML:

```yaml
scope_dimensions:
  csm:     { column: "assignee_name", self: "csm_name" }   # $self → user_attributes.csm_name
  country: { column: "u.country_of_residence" }
metrics:
  - id: ds_open_tasks
    query: >
      SELECT COUNT(*) AS value FROM tasks
      WHERE status IN ('pending','in_progress','blocked') {{scope}}
```

- The kernel replaces `{{scope}}` with `AND TRUE` (unrestricted) or bound predicates, e.g.
  `AND ((assignee_name = ANY(:scope_1)))`. **Scope values are always bind parameters, never text.**
- **Load-time lint:** in an entity that declares `scope_dimensions`, every query (metric, breakdown,
  funnel step, freshness, records) must contain `{{scope}}`, or the plugin fails to load.
- **Grant-time validation:** a scope on a dimension the target entity doesn't declare is rejected.
  If such a grant exists anyway (e.g. a definition changed), it grants nothing.
- `$self` resolves from `user_attributes`. A missing attribute grants nothing.

### 5.6 Field masking

Each breakdown label and record column declares `label_class`: `category`, `business_name` or
`person_name`. Clearances are `fields:business_names` and `fields:people_names`; `category` is always
visible. Contact identifiers stay structurally excluded from every query, as today.

| Mode (set per label class by admins) | Result without clearance |
|---|---|
| pseudonymise | Stable keyed label, e.g. "Account 7f3a" (HMAC with `ATLAS_PSEUDONYM_KEY`) |
| suppress | Breakdown rows removed; totals only |
| bucket | Top N named as "Top 1..N" rank buckets plus "Others" |

Defaults: `person_name` = suppress, `business_name` = pseudonymise.

## 6. Enforcement points

| # | Where | What |
|---|---|---|
| 1 | Discovery | The agent's tool catalog and system prompt, `list_metrics`, `search_atlas` and `describe_entity` include only allowed resources. MCP `tools/list` omits tools the principal lacks capabilities for |
| 2 | `AtlasTools.execute` | Every metric, funnel and entity reference is checked against the Policy. A denial returns "That isn't available to you; request access from <managers>" in business language |
| 3 | Query compilation | `{{scope}}` is compiled from the Policy's row scope |
| 4 | Result shaping | Field masking applied before results reach the model or the MCP client |
| 5 | Audit | Every allow and deny recorded (§9) |

API routes use `require_capability(...)` dependencies built on the same Policy.

## 7. Data model (new tables)

| Table | Key columns |
|---|---|
| `users` | id uuid, email unique, firebase_uid unique null, display_name, status (active, disabled), kind (human, service), role, owner_user_id (services), tenant, created_at, last_seen_at |
| `user_attributes` | user_id, key, value; unique (user_id, key) |
| `groups` | id, name unique per tenant, description, parent_id null, tenant, created_by, created_at |
| `group_members` | group_id, user_id, standing (member, manager), added_by, added_at; pk (group_id, user_id) |
| `grants` | id, subject_type, subject_id, effect, target_kind, target, row_scope jsonb null, reason, expires_at null, created_by, created_at |
| `label_class_settings` | label_class, mode, bucket_size |
| `capabilities` | code, description, deprecated |
| `api_tokens` | id, user_id, kind (oauth_access, oauth_refresh, pat, service), token_hash unique, prefix, name, scope_narrowing jsonb null, client_id null, family_id null, expires_at, last_used_at, revoked_at |
| `oauth_clients` | client_id, name, redirect_uris, registered_at, revoked_at |
| `oauth_codes` | code_hash, client_id, user_id, code_challenge, redirect_uri, resource, expires_at (60 s), used_at |
| `access_requests` | id, user_id, kind (group, role), target, note, status, decided_by, decided_at |
| `rbac_changes` | id, actor_user_id, action, object_type, object_id, before jsonb, after jsonb, at — append-only |
| `policy_state` | single row: policy_version bigint, incremented on every RBAC write |

All timestamps are `TIMESTAMP(timezone=True)`, UTC. `chat_sessions` (whose `user_uid` was dropped,
D6) and `atlas_audit_log` gain `user_id` foreign keys during migration.

**Deleting users and groups.** No code path hard-deletes a user; by convention, disabling one
(`status = disabled`) is the only way to remove it. The database backs this up only partly: the
foreign keys from `atlas_audit_log`, `group_members` and `chat_sessions` have no `ON DELETE` action,
so deleting a user with audit, membership or chat history fails. `grants.subject_id` has no foreign
key, because it can point at a user or a group. Groups are protected in application code instead:
`delete_group` refuses while `group_in_use` finds subgroups, members or grants. If a grant were
orphaned anyway (say, by a manual `DELETE` on the box), it would apply to nobody.

## 8. Module layout

```
backend/app/
├── identity/   users, Principal, authenticators (firebase.py, tokens.py, oauth/), bootstrap
│               public: get_principal (FastAPI dependency), authenticate(request) -> Principal
├── access/     roles + capability catalog (code), groups, grants, attributes, rbac_changes,
│               evaluator + cache        public: policy_for(principal) -> Policy, require_capability
├── atlas/      tools take (principal, policy); registry lints scope_dimensions/label_class/{{scope}};
│               scope compiler; masking
├── api/admin/  users, groups, grants, tokens, clients, access requests, audit, effective-access preview
├── api/me/     /me, /me/access, /me/tokens, /me/clients, /me/requests
└── mcp/        per-request principal via identity; OAuth routes; tools filtered by Policy
```

Dependency direction: `api → identity, access → atlas → sources`. `access` never imports `atlas`;
the atlas kernel consumes the Policy interface. The Policy is cached per `(user_id, policy_version)`
in process. Each request reads `policy_version` (one indexed row), so multiple workers stay
consistent.

Frontend: new self-contained features `features/admin/` and `features/account/`, plus an
`auth/oauth-consent` route for the approve screen. Visibility uses `/me/access`; security decisions
never happen in the browser.

## 9. Audit

- `atlas_audit_log` gains: user_id, auth_method, token_id, client_id, decision (allow, deny),
  deny_reason.
- `rbac_changes` records every grant, membership, role, status and token or client revocation, with
  before and after values.
- The admin audit view shows decision history per user, deny spikes, and token or client activity.

## 10. Admin and self-service

| Screen | Function |
|---|---|
| Users | Search, role, status, groups, attributes, direct grants with expiry, revoke all tokens |
| Effective-access preview | Shows exactly what a chosen user can see and do, with the grant that caused each decision |
| Groups | Tree, members and managers, grant editor with a catalog picker filled from the plugin registry, row-scope builder limited to declared dimensions, clearances |
| Label classes | Masking mode per class |
| Access requests | Users request a group or role; group managers or admins approve |
| Tokens and clients | My tokens and connected apps (revoke); admin view of all |
| Audit | §9 |

## 11. Migration

1. Introduce **Alembic** with a baseline of the current schema (today the app uses `create_all`).
   The baseline must include `chat_messages.blocks` (nullable JSON), added by the Hybrid Glass
   Track C branch through a temporary startup ALTER. In the same change, delete
   `ensure_blocks_column()` in `app/models/migrations.py` and its call in the `app/main.py`
   lifespan, and remove the matching known-debt row in `ARCHITECTURE.md` §6.
2. Create the §7 tables. Seed the capabilities, the label-class defaults and the starter groups
   (`atlas-admins`, `leadership`, `marketing`, `csm`, `risk-ops`, `engineering`; all empty).
3. Backfill: one `users` row per distinct existing `chat_sessions.user_uid`, then set `user_id` on
   sessions and audit rows.
4. Plugin YAML: add `scope_dimensions`, `label_class` and `{{scope}}` to the DeepSales and demo
   definitions; new plugins (e.g. `ecom_users`) are written with them from the start.
5. Replace `ATLAS_MCP_TOKEN` (one shared token) with per-user auth; remove the setting.

## 12. Security requirements

- Fail closed everywhere: missing user, missing attribute, unknown dimension, an evaluator error,
  or an unreadable `policy_version` all mean deny.
- No permission data in any client-held token.
- Scope values only as bind parameters; contact identifiers never selectable.
- Startup refused for `AUTH_DISABLED=true` in production.
- Rate limits per principal and per token.
- Token hashes only; raw tokens shown once. Refresh reuse detection.
- OAuth redirect URIs allowlisted; codes single-use, 60 s.
- Every RBAC write audited and increments `policy_version`; an API write whose actor's Policy
  predates the current `policy_version` is refused (§5.3, write discipline).
- **Ops: a corrupt grant fails closed.** The evaluator warnings name the grant (`grant_id`):
  - `access.malformed_grant` (unknown effect or target kind): everyone the grant applies to loses
    all data, all capabilities and all manager rights.
  - `access.invalid_deny_pattern`: everyone it applies to loses all data.
  - `access.invalid_allow_pattern`: that allow is ignored, so its data is not granted.

  A corrupt **group** grant hits every member of that group and of its child groups at once.
  Investigate how the row got corrupt and fix or revoke it; do not work around it with new grants.

## 13. Testing

- **Evaluator (table-driven):** role inheritance, group inheritance, deny wins at every level, user
  overrides, expiry, OR-ed scopes, unscoped wins, cycle rejection, tenant isolation, fail-closed
  cases.
- **Registry lint:** missing `{{scope}}`, undeclared dimension, missing `label_class`.
- **Scope compiler:** predicates use bind parameters only; adversarial values cannot alter SQL.
- **Masking:** each mode per class; stable pseudonyms.
- **End-to-end:** the same question from three principals (unscoped, row-scoped, no clearance)
  returns three correctly different answers. Revocation takes effect on the next request.
- **MCP:** full OAuth PKCE flow, dynamic registration, refresh rotation and reuse detection, denied
  user (no `mcp:use`), disabled user mid-session, PAT fallback, revoked token.
- **Web:** 24h session cap, domain lock, auto-provisioning lands with zero access.
- **Evals:** new goldens for an honest denial and a scoped answer.

## 14. Rollout

Each phase ships independently, gated by tests and evals.

| Phase | Delivers |
|---|---|
| 1. Identity foundation | Alembic, `users`, Principal, hardened Firebase web auth (server-side 24h, revocation), auto-provisioning, bootstrap admins, production guard |
| 2. Policy core | Capabilities, roles, groups tree, grants (allow and deny, user grants, expiry), evaluator and cache, catalog enforcement and discovery filtering, decision audit, `rbac_changes`, admin API |
| 3. Row and field | `scope_dimensions`, `{{scope}}` lint and compiler, `user_attributes`, label classes and masking; plugin definitions updated |
| 4. MCP authentication | OAuth 2.1 server (primary), PAT fallback, service accounts, per-principal MCP, `tools/list` filtering; shared token removed |
| 5. Admin and self-service UI | Users, groups, effective-access preview, access requests, tokens and connected apps, audit view |

Until phase 5, administration happens through the admin API (and the bootstrap admins).

## 15. Out of scope (designed for, not built)

- External client tenants: the `tenant` column and implicit dimension exist; tenant onboarding does
  not.
- Google Groups or SCIM sync of memberships.
- Row-scoped deny rules.
- An external authorization engine (OpenFGA, Cerbos); the `policy_for` interface keeps this
  swappable.

## 16. To verify at the start of implementation

- What the MCP Python SDK version we pin (`mcp<2`) provides for OAuth authorization-server routes,
  versus implementing the §4.3 endpoints ourselves.
- The exact redirect URIs used by claude.ai, Claude Desktop and Claude Code for the allowlist.
- Claude Code's current support for dynamic client registration with remote HTTP MCP servers.
- Firebase: restricting Google sign-in to the `yougotagift.com` hosted domain at the provider, in
  addition to the backend domain check.

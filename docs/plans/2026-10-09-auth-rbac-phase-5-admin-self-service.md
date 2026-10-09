# Auth & RBAC Phase 5: Admin and Self-Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Before writing any code, follow `.claude/skills/engineering-standards/SKILL.md`; before
> calling a task done, run the two-stage review (spec, then quality per `production-code-review`) and
> keep every gate below green.

**Goal:** Every user can see their own access and ask for more (group, role or an exact resource);
group managers and admins decide those requests in one audited unit of work; admins get paginated
change and decision logs, user and group detail, and a catalog picker with a per-user preview. Then,
once the mockups are approved, the admin and account UI is built over those APIs. The browser never
decides access: anything the UI hides by capability, the API also refuses.

**Architecture:** Everything access-shaped stays in `app/access` (`router → dependencies → requests →
admin → service → repository → models → schemas → … → policy → pure leaves`). A new layer
`app/access/requests.py` holds the request lifecycle; approvals reuse the `AccessAdmin` staged helpers
(extracted in B2, no behaviour change), so D10 and the `policy_state` lock cover every decision and an
approval writes two `rbac_changes` rows with one version bump. Request create, cancel and decline
change no access: they write only `access_requests`, so request traffic never evicts cached policies.
One pure function (`decidable_scope(policy)`) defines which requests a caller may decide; the list,
approve, decline and the `/me/access` badge count all use it. Logs page with one generic keyset cursor
(`app/access/cursor.py`) and one `Page[T]` envelope. Catalog metadata lives in `app/insights`, which may
import both `app.atlas` and `app.access`; `app.access` never imports the atlas. The frontend adds
`features/account` and `features/admin` on shared `api/` hooks, gated by `/me/access`.

**Tech Stack:** FastAPI, SQLModel / SQLAlchemy async, Alembic, Pydantic 2.13 (PEP 695 generics),
pytest (+ xdist), ruff, pyright (strict for `app/access`, `app/insights`), import-linter. Frontend:
React 19, Vite, TypeScript, TanStack Query, Tailwind, Radix primitives, vitest.

**Spec:** `docs/specs/2026-10-08-auth-rbac-design.md` §3.2 (step 4), §5.2, §5.3, §6 (point 2), §7
(`access_requests`), §9, §10, §14 phase 5. **Design analysis:** `phase5-analysis.md` §1–9 (decisions
D5-1…D5-13). **Cross-phase contracts:** `contracts.md` (binding; it supersedes the analysis where they
differ, see "Interfaces from phases 3 and 4").

**Working directory:** worktree `/Users/ashikbabu/Projects/ygg-atlas/.claude/worktrees/p5-admin-ui`,
branch `feature/auth-admin-ui`, based on `origin/main` @ `ac8ba38` (phases 1 and 2 merged). Backend
commands run from `backend/`; frontend commands from `frontend/`. Do not touch other worktrees. Merge
order is 3 → 4 → 5; this branch is rebased by the coordinator after phases 3 and 4 merge.

---

## Decisions this plan makes (read before starting)

The analysis decisions D5-1…D5-13 stand. These are the implementation decisions on top of them.
Change them only with the coordinator.

| # | Decision | Why |
|---|---|---|
| P5-D1 | **Migration `0006_access_requests.py`**: `revision = "0006"`, `down_revision = "0003"  # chain: set to predecessor at integration`. Table `access_requests` (analysis §1.1 plus `tenant`), every datetime `TIMESTAMP(timezone=True)`, CHECKs on `kind` and `status`, a partial unique index on `(user_id, kind, target) WHERE status = 'pending'` (`sqlite_where` + `postgresql_where`), and an index on `(tenant, status, created_at)`. Tests downgrade to `"0003"` in isolation; at integration the coordinator sets `down_revision = "0005"` and the round-trip target follows. | contracts.md "Alembic chain". The partial index makes "one pending request per target" a database fact, not a race-prone check. |
| P5-D2 | **Task split deviates from analysis §5:** B1 ships only the migration, the `AccessRequest` model, the request schemas, `Page[T]` and `cursor.py`. Log schemas belong to B4; `UserDetailOut`, `GroupDetailOut`, `UserOut.created_at`, `MemberOut.role/status` and the `MeAccessOut` additions belong to B5. | No speculative, dead schemas: each schema lands with the route and tests that use it. |
| P5-D3 | **Import-linter access layers gain exactly two modules**: `requests` (between `dependencies` and `admin`) and `cursor` (in the bottom pure layer `catalog \| patterns \| facts \| errors \| cursor`). | contracts.md hotspot rule for `pyproject.toml`. |
| P5-D4 | **`cursor.py` raises its own `InvalidCursorError(ValueError)`**, and the admin/requests layer maps it to `InvalidChangeError` (422). | In import-linter 2.x, `\|` siblings are *independent*: `cursor` may not import `errors`. Same pattern as `patterns.InvalidPatternError` → `InvalidChangeError` today. |
| P5-D5 | **B2 is a mechanical refactor of `AccessAdmin`**: `_commit(*changes: RbacChange)` writes every row and bumps the version once; `_stage_member`, `_stage_grant`, `_stage_user_update` hold everything that today runs *inside* `_write(actor)` (lookups, authority, validation, D10, the row mutation) and return the staged row plus `RbacChange \| None` (None = no-op). Public methods keep their pre-lock gates unchanged (so error precedence is unchanged) and become thin wrappers. Existing tests stay untouched and green. | Analysis D5-1 needs one transaction for an approval; contracts.md asks for a refactor that rebases cleanly over phases 3 and 4. The helpers re-run the authority checks under the lock, so a caller that skips the public pre-lock gate (the approval path) is still fully checked. |
| P5-D6 | **`AccessRequests` subclasses `AccessAdmin`** (in `requests.py`). | pyright strict reports `_name` access from another class (`reportPrivateUsage`) but allows it from a subclass. This keeps B2's helpers private and adds no public write seam to the hotspot `admin.py`. |
| P5-D7 | **Approve = one transaction under `_write(actor)`**: re-read the request with `SELECT … FOR UPDATE` (Postgres; SQLite is serialized anyway), require `pending` (else 409), require `decided_by != user_id` (409 "You can't decide your own request."), require the request to be in the actor's decidable scope (else 404), stage the access change with the B2 helper, set status/`decided_by`/`decided_at`/`decision_note`, then `_commit(access_change, request_change)` → two `rbac_changes` rows (`member.put` \| `grant.create` \| `user.role`, plus `request.approve`) and one bump. A no-op access change (already a member at any standing; role already at or above the target; an identical live allow grant) still approves, with only the `request.approve` row (and its one bump). | Analysis D5-1. The no-op rules also stop an approval from *demoting* a manager to member or an admin to the requested lower role. |
| P5-D8 | **Create, cancel and decline write no `rbac_changes` and do not bump `policy_version`.** Decline still takes `_write(actor)` (authority re-check under the lock, stale actor 409) but commits with `repo.commit()`, not `_commit`. Cancel and decline are conditional updates `WHERE id = :id AND tenant = :t AND status = 'pending'` (cancel adds `AND user_id = :requester`); rowcount 0 → 409. | Analysis D5-2. The conditional update means a cancel can never race an approval: on Postgres it blocks on the approval's row lock and then finds the row no longer pending. |
| P5-D9 | **Decidable scope is one pure function**, `decidable_scope(policy) -> DecidableScope`, appended to `app/access/policy.py`. `admin:users` → `role` and `resource` kinds; `admin:groups` → every `group` request; a manager → `group` requests whose target is in `policy.managed_group_ids` (already includes descendants). Own requests are never decidable. `DecidableScope.covers(kind, target, user_id)` decides one request; the repository turns the same value into a `WHERE` clause for the list and the `/me/access` count. | Lives in `policy.py` because `repository`, `service` and `requests` all sit above it. **Deviates from the coordinator's "admin:users → all kinds"**: approving a group request runs `_stage_member`, whose unchanged D8 check needs `admin:groups` or manager standing, so listing group requests to an `admin:users`-only holder would show requests they cannot approve. The admin role holds both capabilities, so admins still see everything. |
| P5-D10 | **404, not 403, for a request outside the actor's view**: a cross-tenant id, an unknown id, or a same-tenant request the actor cannot decide all read "No such request." A caller whose scope is empty gets 403 on `GET /admin/requests` ("This needs admin:users, admin:groups or group manager standing."). | Never reveal another group's or tenant's requests; the list and the decide routes agree. |
| P5-D11 | **Create rules**: only `policy.active` users (spec §3.2 step 4; no capability). Per kind: `group` → the target parses as a UUID of a group in the tenant, and the user is not a direct member; `role` → in `ROLES` and strictly above the user's role; `resource` → `is_resource_path`. At most 20 pending per user (422). A duplicate pending request → 409 (pre-check, plus the partial-index `IntegrityError` mapped to 409). The cap is atomic: create locks the requester's `users` row `FOR UPDATE` first. | Analysis §1.1; spam and race resistance (analysis §7). |
| P5-D12 | **Resource approval creates exactly the requested path** as a direct user `allow` grant, reason `"Access request <id>: <note>"`. `RequestDecision.expires_at`: field absent → now + 90 days; explicit `null` → no expiry; a value must be in the future (422); `expires_at` present (even `null`) on a non-resource request → 422. | User-approved default 9; analysis D5-3 (the approver cannot widen). |
| P5-D13 | **`/me/requests/options?resource=`** lists tenant groups that, judged as the evaluator would for a member, hold a live allow matching the resource and no live deny matching it (own and ancestor grants), excluding groups the user is directly in. Managers are shown by **display name only**, never email. No notifications; pending counts are badges. | User-approved default 10; analysis D5-4. |
| P5-D14 | **`/admin/rbac-changes` and `/admin/users` change shape in place to `Page[T]`**, keyset on `(at, id)` descending and `(email, id)` ascending. `limit` is `1..200` on every paged route (rbac-changes was `≤500`). Existing tests that read a bare list are updated to `["items"]` (`test_admin_api.py`) or `.items` (`list_changes` callers in `test_admin_users.py`, `test_admin_grants.py`). | Analysis D5-6: no parallel legacy route. |
| P5-D15 | **The audit decision schema is `AuditDecisionOut`**, not `DecisionOut`. | `schemas.py` already has `DecisionOut` (the preview's resource decision). |
| P5-D16 | **Cursor**: base64url (no padding) of `"<key>\|<uuid>"`; decoded with strict base64, split on the *last* `\|`, the UUID parsed strictly, the key non-empty, the encoded length ≤ 512. Time keys are ISO-8601 and must be timezone-aware. Any failure → `InvalidCursorError` → 422 "That page link is invalid; reload the list." Every paged query also filters by tenant, so a cursor naming another tenant's row only positions the page. | Analysis §1.2; analysis §7 "cursor tampering". |
| P5-D17 | **`GET /api/v1/atlas/catalog/resources` lives in `app/insights`** on a second router without the `chat:use` router dependency, aggregated into the exported `insights.router`, so `app/main.py` stays untouched (contracts.md: phase 5 does not edit `main.py`). Gate: no `as_user` → `admin:users` or `admin:groups`; with `as_user` → `admin:users` via `AccessAdmin.effective_access` (tenant-checked, 404 cross-tenant). Metadata only, no numeric fields, no data, no scope dimensions (phase 3 owns `/meta/scope-dimensions`). | Analysis D5-5, D5-7. The capability gate is the admin capability; `chat:use` is unrelated. |
| P5-D18 | **Resource paths in the catalog come from `app.atlas.policy`** (`metric_resource`, `funnel_resource`, `entity_resource`), imported directly as insights already imports `app.atlas.models`; `app/atlas/__init__.py` is not touched. | The picker and the evaluator agree byte-for-byte; no extra atlas hotspot. |
| P5-D19 | **`app/access/__init__.py` gains exactly the phase-4 export lines** (identical text, so the rebase is a no-op): `from app.access.admin import AccessAdmin, Actor` as a new import line; `get_access_admin` and `get_actor` added to the existing `from app.access.dependencies import …` line (ruff format decides wrapping); `"AccessAdmin"`, `"Actor"`, `"get_access_admin"`, `"get_actor"` in `__all__` in ruff's sorted order. | contracts.md hotspot table. |
| P5-D20 | **Order and parallelism**: {B1 ∥ B2} → {B3 ∥ B6} → B4 → B5 → B7 (after phase 3 merges). F0 is the gate; then F1 ∥ F2 → F3 → F4…F9. | Coordinator. B4 and B5 touch the same router/schemas/repository regions as B3, so they run after it. |

## Interfaces from phases 3 and 4

Phase 5 binds to these shapes from `contracts.md`. **Where analysis §4 differs, contracts.md wins**;
analysis §4 is superseded on every point marked ✱.

| From | Interface | Phase 5 use |
|---|---|---|
| Phase 3 | `GrantCreate/GrantOut.row_scope` | Grant editor (F6); stubbed until merged |
| Phase 3 | ✱ `GET /admin/users/{id}/attributes`, **per-key** `PUT` / `DELETE /admin/users/{id}/attributes/{key}` (no bulk PUT) | Attributes editor (F5) |
| Phase 3 | `GET /admin/label-classes`, `PUT /admin/label-classes/{label_class}` | Label classes (F6) |
| Phase 3 | ✱ `GET /meta/scope-dimensions` (the catalog endpoint does **not** embed dimensions) | Row-scope builder and `/me/requests/options` UI; until merged: "Arrives with row and field controls" |
| Phase 3 | `/meta/capabilities` + `clearances`, `label_classes`, `mask_modes`; `/me/access` + `clearances`; `EffectiveAccessOut` + `clearances`, `allow[].row_scope`, `skipped`, `decision.row_scope` | My access, preview |
| Phase 4 | `/me/tokens` (GET/POST/DELETE) | Tokens page (F9) |
| Phase 4 | ✱ **`/me/connected-apps`** and `DELETE /me/connected-apps/{family_id}` (not `/me/clients`) | Connected apps (F9) |
| Phase 4 | ✱ `GET /api/v1/meta/auth-methods` → `{pat: {enabled, default_days, max_days}, oauth: {enabled, hosted_connectors}}` (not `clients_allowlisted`); 404 ⇒ both disabled | Feature flag (F1, F9) |
| Phase 4 | `/admin/tokens`, `/admin/users/{id}/tokens/revoke-all`, `/admin/service-accounts*`, `/admin/clients` | Admin tokens and clients (F9) |
| Phase 4 | ✱ Token and client revocations go to **`/admin/credential-events`**, not `rbac_changes` | Audit "Credentials" tab (F8) |
| Phase 4 | Consent denial page links to `/account/requests/new?kind=role` | Route must exist (F4) |

## File map

| File | Responsibility | Task |
|---|---|---|
| `backend/migrations/versions/0006_access_requests.py` | `access_requests` table, CHECKs, partial unique index, tenant/status index | B1 |
| `backend/app/access/models.py` | `+ AccessRequest` (same constraints and indexes as the migration) | B1 |
| `backend/app/access/cursor.py` | Generic keyset cursor: `encode_cursor`, `decode_cursor`, `decode_time_cursor`, `InvalidCursorError` | B1 |
| `backend/app/access/schemas.py` | `Page[T]`, request schemas (B1); `ChangeOut.actor`, `AuditDecisionOut`, `AuditSummaryOut` (B4); `UserDetailOut`, `GroupDetailOut`, `UserOut.created_at`, `MemberOut.role/status`, `MeAccessOut` additions (B5) | B1, B4, B5 |
| `backend/app/access/admin.py` | B2 staged helpers and `_commit(*changes)`; B4 paged `list_changes`, `list_decisions`, `audit_summary`; B5 `user_detail`, `group_detail`, filtered `list_users` | B2, B4, B5 |
| `backend/app/access/policy.py` | `+ DecidableScope`, `decidable_scope(policy)` (appended) | B3 |
| `backend/app/access/requests.py` | `AccessRequests(AccessAdmin)`: create, cancel, list own, options, list decidable, approve, decline; `groups_granting` (pure) | B3 |
| `backend/app/access/repository.py` | Request reads/writes, user row lock, keyset queries, decisions join, summary aggregates, detail counts | B3, B4, B5 |
| `backend/app/access/service.py` | `describe` gains identity and counts | B5 |
| `backend/app/access/dependencies.py` | `+ get_access_requests` | B3 |
| `backend/app/access/router.py` | `/me/requests*`, `/admin/requests*` (B3); paged logs, audit routes (B4); detail routes, user filters (B5) | B3, B4, B5 |
| `backend/app/access/__init__.py` | The four admin exports (P5-D19) | B6 |
| `backend/app/insights/{router,dependencies,schemas}.py`, `backend/app/insights/catalog_resources.py` | Catalog metadata + preview decisions | B6 |
| `backend/pyproject.toml` | Access layers `requests`, `cursor` | B1 |
| `backend/app/atlas/tools.py`, `backend/app/agent/{blocks,loop}.py`, `evals/run_evals.py`, `evals/goldens/core_metrics.yaml` | Structured `denied` block | B7 |
| `backend/tests/test_alembic.py`, `backend/tests/test_alembic_postgres.py`, `backend/tests/test_access_postgres.py` | Migration and concurrency proofs | B1, B3 |
| `backend/tests/access/test_cursor.py`, `test_admin_staging.py`, `test_requests.py`, `test_requests_approval.py`, `test_requests_api.py`, `test_audit_views.py`, `test_admin_detail.py` (new); `test_admin_api.py`, `test_admin_users.py`, `test_admin_grants.py`, `test_access_api.py` (modified) | Backend tests | B1–B5 |
| `backend/tests/test_insights_catalog_resources.py` | Catalog metadata tests | B6 |
| `ARCHITECTURE.md` (access lines only), `docs/specs/2026-10-08-auth-rbac-design.md` (phase-5 notes only) | Docs | B1, B3 |
| `docs/design/reference/atlas-admin-self-service.html`, `DESIGN.md` | Mockup gate and design additions | F0, F2 |
| `frontend/src/api/**`, `frontend/src/ui/**`, `frontend/src/features/{auth,layout,command,chat,account,admin}/**`, `frontend/src/App.tsx` | UI | F1–F9 |

## Gates (every backend task)

While iterating: the task's targeted `uv run pytest tests/<file> -q`. Before each commit, from
`backend/`:

```bash
uv run ruff check . ../evals && uv run ruff format --check . ../evals \
  && uv run pyright && uv run lint-imports && uv run pytest -n auto -q
```

Before each commit also: the `engineering-standards` procedure, then the two-stage review (spec, then
quality per `production-code-review`); fix and re-review until approved. Commits are signed (1Password
SSH); on signing failure retry 2–3 times, then leave the change staged and report `SIGNING_FAILED`.
Never disable signing. Every commit message ends with:

```
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
```

**Phase end** (Task 18): `make check` at the worktree root, then the opt-in Postgres tests. The repo
opts into real Postgres with **`TEST_PG_URL`** (guarded by `tests/pg_guard.py`: the database name must
carry a `test` or `scratch` token; both PG modules share the xdist group `real-postgres`):

```bash
docker run --rm -d --name atlas-p5-pg -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \
  -e POSTGRES_DB=scratch -p 55436:5432 postgres:16
cd backend && TEST_PG_URL=postgresql+asyncpg://atlas:atlas@localhost:55436/scratch \
  uv run pytest tests/test_alembic_postgres.py tests/test_access_postgres.py -q
docker stop atlas-p5-pg
```

Frontend tasks: `pnpm test`, `pnpm lint && pnpm typecheck` (or `make check-frontend`).

---

### Task 1 (B1): Migration 0006, `AccessRequest`, request schemas, `Page[T]`, cursor

**Status:** ready. Parallel with B2.

**Files:**
- Create: `backend/migrations/versions/0006_access_requests.py`, `backend/app/access/cursor.py`,
  `backend/tests/access/test_cursor.py`
- Modify: `backend/app/access/models.py` (+`AccessRequest`), `backend/app/access/schemas.py`,
  `backend/pyproject.toml` (access layers), `backend/tests/test_alembic.py`,
  `backend/tests/test_alembic_postgres.py`, `ARCHITECTURE.md` (access lines only)

**Migration skeleton** (load-bearing):

```python
revision = "0006"
down_revision = "0003"  # chain: set to predecessor at integration
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
PENDING = sa.text("status = 'pending'")


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "kind IN ('group', 'role', 'resource')", name="ck_access_requests_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'cancelled')",
            name="ck_access_requests_status",
        ),
    )
    op.create_index("ix_access_requests_user_id", "access_requests", ["user_id"])
    op.create_index(
        "uq_access_requests_one_pending",
        "access_requests",
        ["user_id", "kind", "target"],
        unique=True,
        sqlite_where=PENDING,
        postgresql_where=PENDING,
    )
    op.create_index(
        "ix_access_requests_tenant_status_created",
        "access_requests",
        ["tenant", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_access_requests_tenant_status_created", "access_requests")
    op.drop_index("uq_access_requests_one_pending", "access_requests")
    op.drop_index("ix_access_requests_user_id", "access_requests")
    op.drop_table("access_requests")
```

The model declares the same names: `CheckConstraint`s and two `Index(...)` entries in `__table_args__`
(`Index("uq_access_requests_one_pending", "user_id", "kind", "target", unique=True,
sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'"))`,
`Index("ix_access_requests_tenant_status_created", "tenant", "status", "created_at")`), and
`user_id = Field(foreign_key="users.id", index=True)`, so `test_head_on_empty_postgres_has_no_drift`
and `test_check_constraints_match_the_models` stay green. Every datetime field uses
`sa_type=TIMESTAMP(timezone=True)`; `created_at` defaults to `_utcnow`; `tenant` defaults to
`DEFAULT_TENANT`; `decision_note` defaults to `""`. Declare `REQUEST_KINDS` and `REQUEST_STATUSES`
as `Final` tuples in `models.py` next to the table, not in `facts.py` (a pure leaf phase 3 also
edits); schemas use `Literal[...]` directly.

**Cursor interface** (load-bearing):

```python
MAX_CURSOR_LENGTH: Final = 512

class InvalidCursorError(ValueError):
    """A cursor that is not one this server issued. Mapped to 422 by the caller."""

def encode_cursor(key: str, row_id: UUID) -> str: ...          # base64url("<key>|<uuid>"), no padding
def decode_cursor(raw: str) -> tuple[str, UUID]: ...           # strict; raises InvalidCursorError
def decode_time_cursor(raw: str) -> tuple[datetime, UUID]: ... # key is aware ISO-8601
```

**Schemas added in B1:**

```python
class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None

class AccessRequestCreate(BaseModel):
    kind: Literal["group", "role", "resource"]
    target: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=500)   # stripped; blank → 422 in the service

class RequestDecision(BaseModel):
    note: str = Field(default="", max_length=500)
    expires_at: AwareDatetime | None = None             # presence read via model_fields_set (P5-D12)

class RequesterOut(BaseModel):  user_id: UUID; email: str; display_name: str; role: str
class DeciderOut(BaseModel):    user_id: UUID | None; display_name: str   # None = CLI

class AccessRequestOut(BaseModel):
    id: UUID; kind: str; target: str; target_label: str; note: str; status: str
    created_at: datetime; decided_by: DeciderOut | None; decided_at: datetime | None
    decision_note: str; requester: RequesterOut | None = None   # admin views only

class RequestGroupOptionOut(BaseModel): id: UUID; name: str; managers: list[str]  # display names
class RequestOptionsOut(BaseModel):
    resource: str; groups: list[RequestGroupOptionOut]; can_request_resource: bool
```

**pyproject** (`Access module layering`): `"dependencies"`, then a new `"requests"` line, then
`"admin"`; bottom line becomes `"catalog | patterns | facts | errors | cursor"`.

- [ ] **Step 1: Write the failing tests**
  - `tests/access/test_cursor.py`:
    - `test_round_trips_a_key_and_id` — `decode_cursor(encode_cursor("sara@x.com", id)) == ("sara@x.com", id)`.
    - `test_key_may_contain_the_separator` — a key with `|` round-trips (split on the last `|`).
    - `test_time_cursor_round_trips_an_aware_datetime` — UTC datetime in, equal aware datetime out.
    - `test_garbage_is_rejected` (parametrized) — `""`, `"!!!"`, non-base64, padding tricks, no `|`,
      bad UUID, empty key, over-long input (> 512) → `InvalidCursorError`.
    - `test_naive_time_cursor_is_rejected` — ISO without offset → `InvalidCursorError`.
    - `test_cursor_is_url_safe` — encoded text matches `^[A-Za-z0-9_-]+$`.
  - `tests/test_alembic.py`:
    - add `"access_requests"` to the `test_head_matches_model_columns` tuple.
    - `test_access_requests_table_constraints_and_indexes` — after `upgrade head`, the inspector shows
      the three indexes (the partial one unique) and both CHECK names.
    - `test_one_pending_request_per_target` — two `pending` rows with the same
      `(user_id, kind, target)` → `IntegrityError`; a `cancelled` + a `pending` row coexist; two
      `declined` rows coexist.
    - `test_bad_kind_or_status_is_rejected` — CHECK violations raise.
    - `test_downgrade_0006_round_trips` — `upgrade head` → `downgrade "0003"` (table gone) →
      `upgrade head` (table back). Comment: `# at integration the chain predecessor is 0005`.
  - `tests/test_alembic_postgres.py`:
    - `test_access_requests_partial_index_on_postgres` — duplicate pending raises
      `UniqueViolation`; a decided duplicate does not. (Drift is covered by the existing test.)
  - Schema unit tests in `tests/access/test_cursor.py` are enough for `Page`; request schemas are
    exercised by B3.

- [ ] **Step 2: Run red** — `uv run pytest tests/access/test_cursor.py tests/test_alembic.py -q`
  (import errors / missing table).

- [ ] **Step 3: Implement** the migration, model, `cursor.py`, schemas, and the pyproject layers.

- [ ] **Step 4: Run green** — same command, then `uv run lint-imports` (proves the two layer
  additions and that `cursor` imports nothing from `app.access`).

- [ ] **Step 5: Docs** — `ARCHITECTURE.md`: there is no per-module list of access files today; edit
  only the access-module lines: extend the "Identity and access follow the §2.2 anatomy" row (or add
  one line under §2.2) naming the two phase-5 helper modules, `requests.py` (request lifecycle, above
  `admin`) and `cursor.py` (pure keyset cursor, bottom layer).

- [ ] **Step 6: Gate** (see Gates).

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/versions/0006_access_requests.py backend/app/access/{models,schemas,cursor}.py \
  backend/pyproject.toml backend/tests/access/test_cursor.py backend/tests/test_alembic.py \
  backend/tests/test_alembic_postgres.py ARCHITECTURE.md
git commit -m "feat(access): access_requests table, request schemas, Page envelope and keyset cursor"
```

---

### Task 2 (B2): `AccessAdmin` staged helpers (no behaviour change)

**Status:** ready. Parallel with B1.

**Files:**
- Modify: `backend/app/access/admin.py`
- Create: `backend/tests/access/test_admin_staging.py`

**Signatures** (load-bearing):

```python
async def _commit(self, *changes: RbacChange) -> None:
    """Stage every row, bump policy_version ONCE, commit, log each action."""

async def _stage_member(
    self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
) -> tuple[MemberOut, RbacChange | None]: ...

async def _stage_grant(
    self, actor: Actor, payload: GrantCreate, now: datetime
) -> tuple[Grant, RbacChange]: ...          # a duplicate is a ConflictError, never a no-op

async def _stage_user_update(
    self, actor: Actor, user_id: UUID, payload: UserUpdate
) -> tuple[User, RbacChange | None]: ...
```

Each helper assumes the caller holds `_write(actor)` and contains everything the public method runs
today inside the lock **plus** the authority and D10 checks the public method runs before it
(`require_member_admin`, `_no_self_membership`, standing validation, the service-user and
manager-standing `admin:groups` checks; `_grant_capability`, the no-self-grant check,
`_validated_target`, capability-held check; `ADMIN_USERS`, `_not_self`, `_check_not_above_actor`,
`_apply_user_update`). It stages the row (`self._repo.add`) and returns the change, or `None` for a
no-op. The public methods keep their existing pre-lock gates exactly where they are (error
precedence unchanged), then:

```python
async with self._write(actor):
    out, change = await self._stage_member(actor, group_id, user_id, standing)
    if change is None:
        await self._repo.commit()  # release the lock; nothing changed
        return out
    await self._commit(change)
return out
```

`update_user` keeps its post-commit `_end_firebase_sessions` call (phase 4 appends one line there).
No other method changes.

- [ ] **Step 1: Write the failing test** — `tests/access/test_admin_staging.py`:
  - `test_commit_writes_several_changes_with_one_bump` — inside `admin._write(Actor.cli())`, stage a
    member and a grant via the helpers, `_commit(a, b)`; assert `policy_version` +1 exactly and two
    new `rbac_changes` rows with the expected actions (`member.put`, `grant.create`).
  - `test_staged_noop_member_returns_none` — re-putting an existing member at the same standing
    returns `(out, None)` and stages nothing.
  - `test_stage_helpers_recheck_authority` — a viewer actor calling `_stage_member` /
    `_stage_grant` / `_stage_user_update` directly under `_write` gets `AccessDeniedError` (the
    approval path skips the public pre-lock gates, so the helpers must hold the checks).
  (The test file uses `# pyright: reportPrivateUsage=false` at the top; it tests private seams.)

- [ ] **Step 2: Run red** — `uv run pytest tests/access/test_admin_staging.py -q`.

- [ ] **Step 3: Refactor** `admin.py` as above. Do not edit any existing test.

- [ ] **Step 4: Run green** — `uv run pytest tests/access -q` (every existing D10, stale-actor and
  admin test passes untouched) and `uv run pyright`.

- [ ] **Step 5: Gate.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/access/admin.py backend/tests/access/test_admin_staging.py
git commit -m "refactor(access): staged AccessAdmin helpers and multi-change commit"
```

---

### Task 3 (B3): Access requests: lifecycle, decisions, routes

**Status:** after B1 and B2. Parallel with B6.

**Files:**
- Create: `backend/app/access/requests.py`, `backend/tests/access/test_requests.py`,
  `backend/tests/access/test_requests_approval.py`, `backend/tests/access/test_requests_api.py`
- Modify: `backend/app/access/policy.py` (append scope), `backend/app/access/repository.py`,
  `backend/app/access/dependencies.py` (`get_access_requests`), `backend/app/access/router.py`,
  `backend/tests/test_access_postgres.py`, `docs/specs/2026-10-08-auth-rbac-design.md`
  (phase-5 notes)

**Decidable scope** (appended to `policy.py`):

```python
@dataclass(frozen=True, slots=True)
class DecidableScope:
    user_id: UUID                       # never decides own requests
    role_and_resource: bool             # admin:users
    all_groups: bool                    # admin:groups
    group_ids: frozenset[UUID]          # managed subtree (Policy.managed_group_ids)

    @property
    def empty(self) -> bool: ...
    def covers(self, kind: str, target: str, requester_id: UUID) -> bool: ...

def decidable_scope(policy: Policy) -> DecidableScope: ...   # inactive policy → empty
```

**Repository additions:**

```python
async def lock_user(self, user_id: UUID) -> User | None                  # SELECT … FOR UPDATE
async def count_pending(self, user_id: UUID) -> int
async def pending_request(self, user_id: UUID, kind: str, target: str) -> AccessRequest | None
async def request_for_update(self, request_id: UUID) -> AccessRequest | None   # FOR UPDATE
async def request(self, request_id: UUID) -> AccessRequest | None
async def list_own_requests(self, user_id: UUID, limit: int) -> list[AccessRequest]
async def list_decidable(
    self, tenant: str, scope: DecidableScope, status: str | None,
    after: tuple[datetime, UUID] | None, limit: int,
) -> list[tuple[AccessRequest, User]]                                     # newest first, limit+1
async def count_decidable(self, tenant: str, scope: DecidableScope) -> int   # pending only (B5 uses it)
async def finish_request(
    self, request_id: UUID, tenant: str, status: str, *, decided_by: UUID | None,
    note: str, requester: UUID | None = None,
) -> int                                                                  # conditional UPDATE, rowcount
async def group_managers(self, group_ids: Iterable[UUID]) -> dict[UUID, list[str]]  # display names
async def all_group_grants(self, tenant: str) -> list[GrantFacts]
```

`list_decidable` / `count_decidable` build the `WHERE` from `DecidableScope` in one private helper
(`kind IN ('role','resource')` when `role_and_resource`; `kind = 'group'` when `all_groups`;
`kind = 'group' AND target IN (:managed)` otherwise; always `user_id != scope.user_id` and
`tenant = :tenant`).

**Service** (`requests.py`, `class AccessRequests(AccessAdmin)`):

```python
async def create(self, policy: Policy, payload: AccessRequestCreate) -> AccessRequestOut
async def cancel(self, policy: Policy, request_id: UUID) -> AccessRequestOut
async def list_own(self, policy: Policy) -> list[AccessRequestOut]
async def options(self, policy: Policy, resource: str) -> RequestOptionsOut
async def list_decidable(
    self, actor: Actor, status: str | None, cursor: str | None, limit: int
) -> Page[AccessRequestOut]
async def approve(self, actor: Actor, request_id: UUID, decision: RequestDecision) -> AccessRequestOut
async def decline(self, actor: Actor, request_id: UUID, decision: RequestDecision) -> AccessRequestOut

def groups_granting(
    resource: str, groups: Mapping[UUID, GroupFacts], grants: Sequence[GrantFacts], now: datetime
) -> list[UUID]   # pure: own + ancestor live allow matches, no live deny/malformed match
```

`approve`, in order (P5-D7): load the request (tenant check → 404); `_write(actor)`;
`request_for_update` (→ 404 / not pending → 409 "This request was already decided."); requester is
actor → 409; `decidable_scope(actor.policy).covers(...)` (CLI actor: covers all) → else 404; for
resource kind validate `expires_at` (P5-D12); build the access change by kind with the no-op rules;
set the request fields; `_commit(*(c for c in (access_change, request_change) if c))`.
`request.approve` change: `object_type="access_request"`, `object_id=str(id)`, `before`
`{"status": "pending"}`, `after` `{"status": "approved", "kind", "target", "user_id", "expires_at"?}`.
Group kind stages `_stage_member(actor, group_id, user_id, "member")`; role kind
`_stage_user_update(actor, user_id, UserUpdate(role=target))`; resource kind `_stage_grant(actor,
GrantCreate(subject_type="user", subject_id=user_id, effect="allow", target_kind="resource",
target=request.target, reason=f"Access request {id}: {note}", expires_at=...), now)`.

**Routes** (all under `/api/v1`):

| Route | Dependency | Response |
|---|---|---|
| `GET /me/requests` | `get_policy` (active check in service) | `list[AccessRequestOut]` newest first (≤100) |
| `GET /me/requests/options?resource=` | same; `resource` `min_length=1, max_length=200`, must pass `is_resource_path` (422) | `RequestOptionsOut` |
| `POST /me/requests` | same | 201 `AccessRequestOut` |
| `POST /me/requests/{request_id}/cancel` | same | `AccessRequestOut` |
| `GET /admin/requests?status=&cursor=&limit=` | `get_actor` | `Page[AccessRequestOut]` (keyset `(created_at, id)` desc; `limit` 1..200, default 50; `status` `Literal[...] \| None`, default `pending`) |
| `POST /admin/requests/{request_id}/approve` | `get_actor` | `AccessRequestOut` |
| `POST /admin/requests/{request_id}/decline` | `get_actor` | `AccessRequestOut` |

- [ ] **Step 1: Write the failing tests.**
  - `tests/access/test_requests.py` (service, SQLite):
    - `test_a_viewer_with_no_groups_requests_a_resource_and_reads_it_back`
    - `test_a_disabled_user_cannot_create_or_list` → `AccessDeniedError`
    - `test_group_request_needs_a_group_in_the_tenant` — unknown / other-tenant / non-UUID target → 422
    - `test_group_request_refused_when_already_a_member` → 422
    - `test_role_request_must_be_strictly_above_current_role` — same or lower role, unknown role → 422
    - `test_resource_request_needs_a_full_resource_path` — `demo/*`, `demo` → 422
    - `test_blank_note_is_rejected` → 422
    - `test_duplicate_pending_request_is_409`
    - `test_partial_index_violation_maps_to_409` — bypass the pre-check (monkeypatch
      `pending_request` to return None) → still 409
    - `test_twenty_pending_cap` — the 21st → 422; after one cancel, a new one succeeds
    - `test_cancel_by_requester_only` — another user's request → 404; a decided one → 409
    - `test_create_cancel_decline_write_no_rbac_changes_and_no_bump` — `policy_version` and
      `rbac_changes` count unchanged across all three
    - `test_options_lists_groups_holding_the_resource` — direct and inherited (ancestor) allow
    - `test_options_excludes_member_groups_and_deny_matched_groups` (own or ancestor deny; expired
      allow ignored; expired deny does not exclude)
    - `test_options_shows_manager_display_names_not_emails`
    - `test_options_is_tenant_scoped`
    - `test_groups_granting_is_pure` — table-driven unit test of `groups_granting`
    - `test_decidable_scope_by_capability` — table: admin (both) / `admin:users` only / `admin:groups`
      only / manager of a parent (covers child group target) / viewer (empty) / inactive (empty) /
      own request never covered
  - `tests/access/test_requests_approval.py`:
    - `test_manager_approves_group_request` — member row, two `rbac_changes` (`member.put`,
      `request.approve`), version +1, request `approved` with `decided_by`/`decided_at`/note
    - `test_manager_of_parent_approves_subgroup_request`
    - `test_manager_cannot_see_or_decide_role_or_resource_requests` → 404, and absent from the list
    - `test_manager_cannot_decide_other_subtree_group_request` → 404
    - `test_admin_users_only_does_not_list_group_requests` (P5-D9)
    - `test_nobody_decides_their_own_request` — approve and decline → 409 "You can't decide your own request."
    - `test_role_approval_runs_d10` — approver without the role's capabilities → 403; target above
      the approver → 403; request stays pending
    - `test_role_approval_never_demotes` — user promoted past the target meanwhile → approved with one
      `request.approve` row, role unchanged
    - `test_group_approval_when_already_a_manager_is_a_noop_approve` — standing stays `manager`
    - `test_resource_approval_creates_exact_user_grant` — target equals the request, effect allow,
      reason `"Access request <id>: <note>"`, default expiry ≈ now + 90 days
    - `test_resource_approval_expiry_explicit_null_and_value` — `null` → no expiry; past → 422
    - `test_expires_at_on_group_or_role_request_is_422`
    - `test_resource_approval_with_existing_live_grant_is_noop_approve`
    - `test_stale_actor_gets_409_and_request_stays_pending`
    - `test_already_decided_request_is_409` — approve after decline / cancel / approve
    - `test_decline_takes_the_lock_but_does_not_bump` — stale actor → 409; fresh → declined, no bump
    - `test_cross_tenant_request_is_404` (approve, decline)
    - `test_list_is_keyset_paged_and_filtered_by_status` — 3 pages, no gaps or repeats, tenant-only
    - `test_tampered_cursor_is_422`
  - `tests/access/test_requests_api.py` (HTTP):
    - `test_me_requests_round_trip_shapes` — POST 201 → GET list → cancel; `requester` is null on `/me`
    - `test_disabled_user_gets_403_on_me_requests`
    - `test_options_rejects_a_pattern_with_422`
    - `test_admin_requests_403_for_a_plain_viewer`
    - `test_admin_requests_page_embeds_the_requester`
    - `test_approve_and_decline_over_http` (status codes 200/404/409/422 mapped by the handler)
  - `tests/test_access_postgres.py` (opt-in):
    - `test_concurrent_approvals_exactly_one_wins` — two CLI actors (no stale check, so the request
      row lock is what is proven) approve the same request → one `AccessRequestOut`, one
      `ConflictError`; `rbac_changes` +2, version +1, one membership row
    - `test_cancel_racing_an_approval_one_wins` — approve (holding the lock via `_widen_race`) vs
      cancel → exactly one of approved / cancelled; a cancelled request has no grant
    - `test_concurrent_creates_respect_the_cap` — 19 pending + two concurrent creates → one 201, one 422

- [ ] **Step 2: Run red** — `uv run pytest tests/access/test_requests*.py -q`.

- [ ] **Step 3: Implement** `policy.py` scope, repository methods, `requests.py`,
  `get_access_requests` (built like `get_access_admin`), routes. Map `InvalidCursorError` →
  `InvalidChangeError`; map `IntegrityError` from the partial index on create → `ConflictError`
  ("You already asked for this; it's pending.").

- [ ] **Step 4: Run green**, then `uv run lint-imports` (`router → dependencies → requests → admin`).

- [ ] **Step 5: Docs** — in the spec, edit only phase-5 material: §7 `access_requests` row gains
  `tenant`, `note`, `decision_note`, kind `resource`; add a short **"Phase 5 notes"** paragraph under
  §14: (1) `kind=resource` is an accepted addition (analysis D5-3: exact path, direct user grant,
  90-day default expiry, approver can't widen); (2) request lifecycle `pending → approved | declined |
  cancelled`, who decides each kind (P5-D9); (3) create, cancel and decline change no access, so they
  write no `rbac_changes` and do not bump `policy_version`; an approval writes the access change and
  `request.approve` with one bump.

- [ ] **Step 6: Gate.**

- [ ] **Step 7: Commit**

```bash
git add backend/app/access backend/tests/access backend/tests/test_access_postgres.py \
  docs/specs/2026-10-08-auth-rbac-design.md
git commit -m "feat(access): access requests with one-transaction approvals"
```

---

### Task 4 (B4): Paged change log, decision log, audit summary

**Status:** after B3.

**Files:**
- Create: `backend/tests/access/test_audit_views.py`
- Modify: `backend/app/access/{schemas,repository,admin,router}.py`,
  `backend/tests/access/test_admin_api.py` (lines 64, 141, 144: envelope and `limit` 201),
  `backend/tests/access/test_admin_users.py` (`list_changes` callers → `.items`),
  `backend/tests/access/test_admin_grants.py` (line 166)

**Schemas:**

```python
class ActorRefOut(BaseModel): display_name: str; email: str
class ChangeOut(BaseModel):  ... existing fields ...; actor: ActorRefOut | None = None
class AuditUserOut(BaseModel): user_id: UUID; email: str; display_name: str
class AuditDecisionOut(BaseModel):
    id: UUID; user: AuditUserOut; auth_method: str | None; surface: str; tool: str
    arguments: dict[str, Any] | None; decision: str; deny_reason: str | None
    success: bool; error: str | None; duration_ms: int | None; created_at: datetime
class DayCountOut(BaseModel): date: date; allow: int; deny: int
class ReasonCountOut(BaseModel): reason: str; count: int
class UserCountOut(BaseModel): user_id: UUID; display_name: str; count: int
class AuditSummaryOut(BaseModel):
    days: int; per_day: list[DayCountOut]; top_deny_reasons: list[ReasonCountOut]
    top_denied_users: list[UserCountOut]
```

**Admin methods** (all `actor.require(ADMIN_AUDIT)` first, all tenant-filtered):

```python
async def list_changes(self, actor: Actor, query: ChangeQuery = ChangeQuery()) -> Page[ChangeOut]
async def list_decisions(self, actor: Actor, query: DecisionQuery) -> Page[AuditDecisionOut]
async def audit_summary(self, actor: Actor, days: Literal[7, 30]) -> AuditSummaryOut
```

`ChangeQuery` / `DecisionQuery` are frozen dataclasses in `schemas.py` (cursor, limit, filters).
Changes: `LEFT JOIN users` on `actor_user_id` for the actor ref; filters `actor_user_id, object_type,
action, object_id, since, until`. Decisions: `atlas_audit_log JOIN users ON users.id = user_id`
(`user_id IS NULL` rows excluded by the inner join; `users.tenant = :tenant` fails closed), filters
`user_id, decision ('allow'|'deny'), surface, tool, auth_method, since, until`. Both keyset on
`(at|created_at, id)` desc with `limit + 1`. Summary: SQL `GROUP BY func.date(created_at), decision`
over `now - days`, zero-filled per day in Python; top 5 deny reasons and top 5 denied users.

**Routes:** `GET /admin/rbac-changes` → `Page[ChangeOut]` (`limit` 1..200 default 100);
`GET /admin/audit/decisions` → `Page[AuditDecisionOut]` (`limit` 1..200 default 100);
`GET /admin/audit/summary?days=` → `AuditSummaryOut` (`days` must be 7 or 30, else 422).

- [ ] **Step 1: Write the failing tests** — `tests/access/test_audit_views.py`:
  - `test_changes_cursor_walks_250_rows_without_gaps_or_repeats` (including equal timestamps: the id
    tiebreak)
  - `test_changes_cursor_is_stable_under_new_inserts` — insert rows between pages; the walk still
    returns the original set once
  - `test_changes_filters` — each filter alone and combined; `since`/`until` bounds
  - `test_changes_carry_the_actor_ref` — CLI rows have `actor: null`
  - `test_decisions_exclude_null_user_and_other_tenants`
  - `test_decisions_filters_and_deny_only`
  - `test_cursor_naming_another_tenants_row_returns_only_own_rows` — for both logs
  - `test_tampered_cursor_is_422` — both logs
  - `test_summary_counts_per_day_and_tops` — zero-filled days, allow/deny split, top reasons/users
  - `test_summary_days_must_be_7_or_30` → 422
  - `test_audit_views_need_admin_audit` — builder / `admin:users`-only → 403 on all three
  - `test_limit_bounds` — 0 and 201 → 422
  - Update `test_admin_api.py` and the `list_changes` call sites to the envelope (no behaviour
    assertions change).

- [ ] **Step 2: Run red** — `uv run pytest tests/access/test_audit_views.py tests/access/test_admin_api.py -q`.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run green**; then `uv run pytest tests/access -q`.

- [ ] **Step 5: Gate.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/access backend/tests/access
git commit -m "feat(access): paged rbac changes, decision log and audit summary"
```

---

### Task 5 (B5): User and group detail, user filters, `/me/access` additions

**Status:** after B4.

**Files:**
- Create: `backend/tests/access/test_admin_detail.py`
- Modify: `backend/app/access/{schemas,repository,admin,service,router}.py`,
  `backend/tests/access/test_admin_api.py` (`/admin/users` list → `["items"]`),
  `backend/tests/access/test_admin_users.py` (`list_users` callers → `.items`),
  `backend/tests/access/test_access_api.py`

**Schemas:** `UserOut` gains `created_at: datetime`; `MemberOut` gains `role: str`, `status: str`;
`UserGroupOut {id, name, standing}`; `UserDetailOut(UserOut) {groups: list[UserGroupOut],
direct_grants: list[GrantOut], pending_requests: int}`; `GroupDetailOut(GroupOut) {member_count: int,
grant_count: int, path: list[str]}` (names root → group); `MeAccessOut` gains `user_id: UUID,
email: str, display_name: str, pending_requests: int, pending_approvals: int, is_manager: bool`.

**Admin methods:**

```python
async def list_users(self, actor: Actor, query: UserQuery) -> Page[UserOut]   # q, role, status, kind, cursor, limit
async def user_detail(self, actor: Actor, user_id: UUID) -> UserDetailOut      # admin:users; 404 cross-tenant
async def group_detail(self, actor: Actor, group_id: UUID) -> GroupDetailOut   # require_member_admin; 404 cross-tenant
```

`list_users` keysets on `(email, id)` ascending. `AccessService.describe` reads the user row for
email/display name, `repo.count_pending(policy.user_id)` and
`repo.count_decidable(policy.tenant, decidable_scope(policy))`; `is_manager = bool(policy.managed_group_ids)`.
No authority logic is duplicated: the count uses the B3 scope.

**Routes:** `GET /admin/users` → `Page[UserOut]` (`q`, `role`, `status`, `kind`, `cursor`, `limit`
1..200 default 50); `GET /admin/users/{user_id}` → `UserDetailOut`; `GET /admin/groups/{group_id}` →
`GroupDetailOut`.

- [ ] **Step 1: Write the failing tests**
  - `tests/access/test_admin_detail.py`:
    - `test_user_detail_lists_groups_direct_grants_and_pending_count`
    - `test_user_detail_cross_tenant_is_404` / `test_user_detail_needs_admin_users` (403)
    - `test_group_detail_counts_and_path` — three-level tree; path from root
    - `test_group_detail_for_a_manager_of_an_ancestor` (200) and an unrelated manager (403)
    - `test_group_detail_cross_tenant_is_404`
    - `test_user_filters_role_status_kind_and_search`
    - `test_user_cursor_walks_by_email` — ties impossible (unique email) but id is in the cursor
    - `test_members_carry_role_and_status`
  - `tests/access/test_access_api.py`:
    - `test_me_access_identity_fields`
    - `test_me_access_pending_counts` — own pending count; approvals for admin, for a manager (only
      subtree group requests), zero for a viewer; own requests never counted as approvals
    - `test_me_access_is_manager`

- [ ] **Step 2: Run red.** **Step 3: Implement.** **Step 4: Run green** (`uv run pytest tests/access -q`).

- [ ] **Step 5: Gate.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/access backend/tests/access
git commit -m "feat(access): user and group detail, user filters, request counts in /me/access"
```

---

### Task 6 (B6): Catalog metadata and per-user preview in insights

**Status:** after B1 (needs nothing from B2/B3). Parallel with B3.

**Files:**
- Create: `backend/app/insights/catalog_resources.py`,
  `backend/tests/test_insights_catalog_resources.py`
- Modify: `backend/app/access/__init__.py` (P5-D19 lines only), `backend/app/insights/router.py`,
  `backend/app/insights/dependencies.py`, `backend/app/insights/schemas.py`

**Exports** (`app/access/__init__.py`, identical to phase 4's lines):

```python
from app.access.admin import AccessAdmin, Actor
from app.access.dependencies import (
    access_error_handler,
    get_access_admin,
    get_actor,
    get_policy,
    require_capability,
)
# __all__ gains "AccessAdmin", "Actor", "get_access_admin", "get_actor" in ruff's sorted order
```

**Schemas** (no numeric fields anywhere):

```python
class ResourceDecisionOut(BaseModel): allowed: bool; reason: str; origin: str | None
class CatalogItemOut(BaseModel):
    path: str; id: str; name: str; kind: Literal["metric", "funnel"]
    decision: ResourceDecisionOut | None = None
class CatalogEntityOut(BaseModel):
    path: str; name: str; items: list[CatalogItemOut]; decision: ResourceDecisionOut | None = None
class CatalogSourceOut(BaseModel): id: str; name: str; entities: list[CatalogEntityOut]
class CatalogResourcesOut(BaseModel): sources: list[CatalogSourceOut]; as_user: UUID | None = None
```

**Function:** `build_catalog_resources(registry: AtlasRegistry, policy: Policy | None) ->
CatalogResourcesOut` (pure; paths from `metric_resource` / `funnel_resource` / `entity_resource`;
`policy.decide(path)` when given).

**Router:** split `insights/router.py` into `_dashboard` (the existing prefix `/api/v1/atlas` and its
`chat:use` dependency, unchanged routes) and `_catalog_admin` (prefix `/api/v1/atlas`, no router
dependency), aggregated into the exported `router = APIRouter(); router.include_router(...)` so
`app/main.py` is untouched:

```python
@_catalog_admin.get("/catalog/resources", response_model=CatalogResourcesOut)
async def catalog_resources(
    as_user: UUID | None = None,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> CatalogResourcesOut   # body calls build_catalog_resources(get_registry(), policy_or_none)
```

Without `as_user`: `actor.require_any(ADMIN_USERS, ADMIN_GROUPS)`. With `as_user`:
`await admin.effective_access(actor, as_user)` (requires `admin:users`, 404 cross-tenant). `AccessError`
is already mapped app-wide by `access_error_handler`.

- [ ] **Step 1: Write the failing tests** — `tests/test_insights_catalog_resources.py`:
  - `test_admin_with_no_data_sees_full_metadata` (D2: no grants, still every source/entity/item)
  - `test_admin_groups_alone_may_list` / `test_viewer_gets_403` / `test_builder_gets_403`
  - `test_as_user_needs_admin_users` — `admin:groups`-only → 403
  - `test_as_user_returns_the_targets_decisions_with_origin` — group allow, user deny, nothing
  - `test_as_user_from_another_tenant_is_404`
  - `test_paths_match_the_atlas_resource_builders` — every item path equals
    `metric_resource(m)` / `funnel_resource(f)`; entity path equals `entity_resource(e)`
  - `test_response_contains_no_numeric_values` — walk the JSON: no `int`/`float` anywhere
  - `test_dashboard_routes_still_require_chat_use` — `/api/v1/atlas/metrics` still 403 without it
  - `test_no_scope_dimensions_are_embedded` — no `scope_dimensions` key

- [ ] **Step 2: Run red.** **Step 3: Implement.** **Step 4: Run green**; `uv run lint-imports`
  (insights may import access and atlas; access still imports neither).

- [ ] **Step 5: Gate.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/access/__init__.py backend/app/insights backend/tests/test_insights_catalog_resources.py
git commit -m "feat(insights): catalog resource metadata with per-user access preview"
```

---

### Task 7 (B7): Structured `denied` answer block + golden

**Status: after phase 3 merge** (rebase on phase 3 first; touches `atlas/tools.py`, which phase 3
changes for scope and masking). Last backend task.

**Files:**
- Modify: `backend/app/atlas/tools.py` (`AtlasAccessDeniedError` carries `resource`; `execute`
  returns `{"error": msg, "denied": {"resource": path, "label": label}}` for a policy denial only),
  `backend/app/agent/blocks.py` (`denied_from_result(result) -> Block | None`),
  `backend/app/agent/loop.py` (`_TurnRecorder.execute` appends one `denied` block per resource,
  deduplicated, persisted with the turn's blocks), `evals/run_evals.py` (`expect_denied_block`),
  `evals/goldens/core_metrics.yaml` (`denied-funnel-is-honest` gains `expect_denied_block: true`)
- Tests: `backend/tests/test_atlas_tools.py`, `backend/tests/test_agent_loop.py`,
  `backend/tests/test_answer_blocks.py`

- [ ] **Step 1: Failing tests**
  - `test_atlas_tools.py`: `test_denial_carries_a_denied_payload`;
    `test_policy_failure_has_no_denied_key` (the "couldn't be checked" path);
    `test_denied_payload_holds_no_numbers`.
  - `test_agent_loop.py`: `test_denied_block_is_appended_once_per_resource`;
    `test_denied_block_is_persisted_in_done`; `test_model_prose_unchanged` (the tool message the model
    sees still carries only `error`).
  - `test_answer_blocks.py`: `test_denied_from_result_shape`.
- [ ] **Step 2: Run red.** **Step 3: Implement.** **Step 4: Run green.**
- [ ] **Step 5: Evals** — `cd backend && uv run python ../evals/run_evals.py` (live run; see the
  local eval recipe); `denied-funnel-is-honest` passes with the block; MCP output unchanged (the block
  is chat-only).
- [ ] **Step 6: Gate.**
- [ ] **Step 7: Commit**

```bash
git add backend/app/atlas/tools.py backend/app/agent evals backend/tests
git commit -m "feat(agent): structured denied answer block with a request-access path"
```

---

### Task 8 (F0): Mockups (the gate)

**Status:** in review on branch `feature/admin-ui-mockups` (built separately). Its commit is merged
into this branch after the user approves a mode.

- File: `docs/design/reference/atlas-admin-self-service.html` (same control dock as
  `atlas-hybrid-glass.html`); scope and dock toggles per analysis §9 (personas, theme, accessibility,
  width, states, phase-4 flag, origins overlay; screens 1–12).
- Accept: the user approves a mode; DESIGN.md additions (analysis §6) are written from it before F2.

---

### Task 9 (F1): API layer and hooks

**Status: blocked on mockup approval.** Parallel with F2.

- Files: `frontend/src/api/access.ts`, `frontend/src/api/tokens.ts` (phase-4 shapes from contracts.md:
  `/me/connected-apps`, `/meta/auth-methods` with `hosted_connectors`), `frontend/src/api/catalog-admin.ts`,
  `frontend/src/api/mutation-errors.ts`, `frontend/src/api/hooks/use-{my-access,admin-users,admin-groups,admin-grants,access-requests,audit,tokens,auth-methods,catalog-resources,credential-events}.ts`
  (`useInfiniteQuery` on `next_cursor`).
- Tests: `api/cursor.test.ts` (page merge), `api/mutation-errors.test.ts` (409 → invalidate
  `['me','access']` + toast; 403 → backend sentence), `api/hooks/use-my-access.test.tsx` (error ⇒
  fail-closed `{capabilities: []}` shape), `api/hooks/use-auth-methods.test.tsx` (404 ⇒ both disabled).
- Accept: `pnpm typecheck` green; no feature imports.
- Commit: `feat(frontend): access, requests, audit and token API hooks`

### Task 10 (F2): `ui/` primitives and DESIGN.md entries

**Status: blocked on mockup approval.** Parallel with F1.

- Files: `frontend/src/ui/{data-table,status-pill,tree-list,filter-bar,empty-state,review-card,select,tabs,checkbox,textarea,field,token-reveal}.tsx`, `frontend/src/ui/index.ts`, `DESIGN.md`,
  `frontend/src/index.css` (only if a token is missing), `frontend/package.json` (Radix additions only).
- Tests: one `*.test.tsx` per primitive (render, a11y roles, `review-card` reduced-motion path,
  `data-table` tabular-nums class, `token-reveal` copies once and masks after).
- Accept: `npx @google/design.md lint DESIGN.md` clean; no hex in components; no new UI libraries.
- Commit: `feat(ui): admin primitives (data table, status pill, tree list, review card, …)`

### Task 11 (F3): Route guard, nav composition, account menu

**Status: blocked on mockup approval.** After F1.

- Files: `frontend/src/features/auth/require-access.tsx` (+ export in `index.ts`),
  `frontend/src/features/layout/sidebar-content.tsx` (`NavItem` gains `section?`, `badge?`),
  `account-controls.tsx` (`menuItems` prop), `frontend/src/App.tsx` (admin and account routes; nav
  built from `useMyAccess`; admin section when any `admin:*` or `is_manager`),
  `frontend/src/features/command/command-palette.tsx` (same filter).
- Tests: `require-access.test.tsx` (loading; lacking → denied page; error → denied page; pass →
  children), `shell-nav.test.tsx` (+ admin section, badges from `pending_approvals` /
  `pending_requests`), an `App` route smoke test.
- Accept: a viewer never sees `/admin/*` chrome; a deep link renders the denied page, not a redirect loop.
- Commit: `feat(frontend): capability route guard and admin navigation`

### Task 12 (F4): `features/account` + chat `DeniedBlock`

**Status: blocked on mockup approval.** After F2, F3; backend B3 (and B7 for the chat block).

- Files: `frontend/src/features/account/{index.ts, components/my-access-page.tsx, access-summary.tsx, group-list.tsx, requests-page.tsx, request-card.tsx, new-request-page.tsx, request-form.tsx, hooks/use-request-form.ts, request-rules.ts}`,
  `frontend/src/features/chat/components/{denied-block.tsx, answer-blocks.tsx}`, `frontend/src/api/chat.ts`
  (`DeniedBlock` type), `App.tsx` (first run without data lands on `/account`). Route
  `/account/requests/new` honours `?kind=role` (phase-4 consent link) and `?resource=&label=`.
- Tests: `my-access-page.test.tsx`, `request-form.test.tsx` (kind rules mirror the backend; options
  from `/me/requests/options`; manager names only), `denied-block.test.tsx`, `request-rules.test.ts`.
- Accept: a new viewer signs in, sees "No data access yet", requests `demo/*` via a suggested group,
  and sees it pending.
- Commit: `feat(account): my access, access requests and request-from-denial`

### Task 13 (F5): Admin users, detail, preview

**Status: blocked on mockup approval.** After F2, F3; backend B5, B6.

- Files: `frontend/src/features/admin/{index.ts, components/users-page.tsx, user-row.tsx, user-detail-page.tsx, role-status-editor.tsx, direct-grants.tsx, effective-access-panel.tsx, resource-probe.tsx, catalog-decisions.tsx, attributes-editor.tsx (phase-3 per-key PUT/DELETE, stub until merged), hooks/use-user-detail.ts}`.
- Tests: `users-page.test.tsx` (search, filters, "Load more"), `role-status-editor.test.tsx` (review
  card before → after; self-edit disabled with the backend sentence; 409), `effective-access-panel.test.tsx`.
- Accept: a role change's review-card diff equals the resulting `rbac_changes` before/after.
- Commit: `feat(admin): users, user detail and effective-access preview`

### Task 14 (F6): Groups tree, members, grant editor

**Status: blocked on mockup approval.** Parallel with F5; backend B5, B6.

- Files: `features/admin/components/{groups-page.tsx, group-tree.tsx, group-detail-page.tsx, members-panel.tsx, member-picker.tsx, grant-editor.tsx, catalog-picker.tsx, row-scope-builder.tsx, clearance-picker.tsx, label-classes-page.tsx, group-form.tsx}`,
  `features/admin/group-tree.ts`, `features/admin/grant-rules.ts`. The row-scope builder reads phase
  3's `/meta/scope-dimensions` (not the catalog endpoint); until merged it shows "Arrives with row and
  field controls".
- Tests: `group-tree.test.ts`, `grant-rules.test.ts` (same table as `test_patterns.py`),
  `grant-editor.test.tsx`, `members-panel.test.tsx`.
- Accept: a manager persona adds a member and nothing else; an `admin:groups` persona edits grants.
- Commit: `feat(admin): groups tree, members and grant editor`

### Task 15 (F7): Requests queue

**Status: blocked on mockup approval.** Parallel with F5, F6; backend B3.

- Files: `features/admin/components/{requests-page.tsx, request-queue-row.tsx, decide-dialog.tsx}`.
- Tests: `requests-page.test.tsx` (review card per kind; expiry only for resource, prefilled +90 days
  and clearable; decline needs no note; own request has no actions; 409 → row refreshes).
- Accept: the badge count decrements after a decision.
- Commit: `feat(admin): access requests queue`

### Task 16 (F8): Audit (Changes, Decisions, Credentials, Summary)

**Status: blocked on mockup approval.** Parallel with F5–F7; backend B4; phase 4 for Credentials.

- Files: `features/admin/components/{audit-page.tsx, changes-table.tsx, decisions-table.tsx, credentials-table.tsx, audit-summary.tsx, change-diff.tsx}`. The Credentials tab reads phase 4's
  `/admin/credential-events` (404 → "Not available yet").
- Tests: `audit-page.test.tsx` (tabs; filters update query keys; infinite scroll; diff expand; deny
  reason in mono; summary labels in text, not color only; Credentials tab disabled state).
- Accept: no number without a label; `arguments` only in a collapsed JSON view.
- Commit: `feat(admin): audit views`

### Task 17 (F9): Tokens and connected apps

**Status: blocked on mockup approval.** After F2, F3; phase 4 merged or stubbed.

- Files: `features/account/components/{tokens-page.tsx, token-list.tsx, create-token-dialog.tsx, connected-apps.tsx}`, `features/admin/components/{tokens-page.tsx, clients-page.tsx, service-accounts-page.tsx}`.
- Tests: `create-token-dialog.test.tsx` (shown once via `token-reveal`; expiry ≤ `max_days`),
  `connected-apps.test.tsx` (`oauth.enabled=false` → "Not enabled for this deployment"; enabled +
  empty; populated → revoke via `DELETE /me/connected-apps/{family_id}` with a review card;
  `hosted_connectors=false` → no claude.ai copy), `tokens-page.test.tsx` (admin revoke-all review card).
- Accept: works against mocked `api/tokens.ts`; on the real backend 404 flags render disabled.
- Commit: `feat(account): tokens and connected apps`

---

### Task 18: Phase gate

- [ ] `make check` at the worktree root (backend coverage ≥ 80%, frontend check incl. build).
- [ ] Opt-in Postgres: alembic round trip and drift, partial index, concurrent approve (exactly one
  wins), cancel-vs-approve, concurrent cap (see Gates for the `TEST_PG_URL` command).
- [ ] Live evals (after B7): `cd backend && uv run python ../evals/run_evals.py`.
- [ ] Final two-stage review of the whole branch; report to the coordinator. No push, no PR, no deploy.

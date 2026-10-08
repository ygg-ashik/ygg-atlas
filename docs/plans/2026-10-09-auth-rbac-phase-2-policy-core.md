# Auth & RBAC Phase 2: Policy Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Before writing any code, follow `.claude/skills/engineering-standards/SKILL.md`; before
> calling a task done, `make check` must be green.

**Goal:** Every atlas request is authorized by an evaluated, cached `Policy`. Roles grant actions,
groups and grants decide which data a person can see (deny always wins), the agent and the dashboard
only see and query what is allowed, and every decision and every access change is audited.

**Architecture:** A new self-contained module `app/access` owns the capability catalog, groups,
grants, the pure evaluator, the per-`(user, policy_version)` cache, the admin service, the admin API
and an admin CLI. The atlas kernel never imports it: `AtlasTools` takes any object with
`allows(resource)` / `deny_reason(resource)` (a `ResourcePolicy` protocol defined in the atlas), and
the edges (chat API, insights, MCP) pass the caller's `Policy`. Every access write commits together
with its `rbac_changes` row and a `policy_version` bump, so no worker serves a stale policy.

**Tech Stack:** FastAPI, SQLModel / SQLAlchemy async, Alembic, pytest, ruff, pyright (strict for
`app/access`), import-linter.

**Spec:** `docs/specs/2026-10-08-auth-rbac-design.md` §2, §3.2 (step 4), §5.1–5.4, §6 (enforcement
points 1, 2, 5), §7, §8, §9, §10 (API only), §11.2, §12, §13, §14 phase 2.

**Working directory:** worktree `/Users/ashikbabu/Projects/ygg-atlas-wt-policy`, branch
`feature/auth-policy`, based on `main` @ `5388548` (Phase 1 merged). Backend commands run from
`backend/`.

---

## Decisions this plan makes (read before starting)

The spec leaves these to implementation. They are deliberate; change them only with the user.

| # | Decision | Why |
|---|---|---|
| D1 | **Phase 2 has no row scopes and no clearances.** The `grants` table has no `row_scope` column yet; the API rejects `target_kind = clearance` with a business message; the evaluator ignores clearance grants. | Phase 3 adds `scope_dimensions`, the `{{scope}}` compiler and masking together. A row scope stored now would silently grant *all* rows (fail open). |
| D2 | **No admin bypass.** The `admin` role grants admin *actions* only. Admins see data only through grants, like everyone else (spec §5.4). | Spec. Deploy step: an admin grants `atlas-admins` access with the CLI. |
| D3 | **Role and status are written by `app.access`** (they live on `users`, but changing them is an authorization change that must commit with its audit row and version bump). `IdentityService.disable_user` moves to `AccessAdmin.set_status`. | One unit of work per change; no stale cached policy. |
| D4 | **MCP still uses the shared `ATLAS_MCP_TOKEN` until phase 4**, but calls now run as a real service user (`MCP_SERVICE_EMAIL`, role `analyst`), authorized by its own grants (none by default), and **MCP is refused when no token is configured** (today an empty token means open). | Fail closed; no anonymous data path. Per-user MCP auth is phase 4. |
| D5 | **An admin CLI** (`python -m app.access.cli`) ships with the admin API. | There is no admin UI until phase 5, and the API needs a Firebase token that is awkward to obtain by hand. The CLI runs on the box (`docker compose exec backend …`) and is audited with `via="cli"`. |
| D6 | **`chat_sessions.user_uid` is dropped** and `user_id` becomes required; the guardrails count by `user_id`. `atlas_audit_log` gains `user_id` (backfilled) and keeps its legacy `user_uid` (append-only). | Closes the Phase 1 debt rows. |
| D7 | **Local development needs one grant**: `make dev-access` grants the dev user `*`. | No bypass, even locally (D2). |
| D8 | **Managers** (group standing `manager`) may add and remove *members* of their group and its descendants; only `admin:groups` can make someone a manager or edit grants. Direct user grants need `admin:users` and a reason. | Spec §5.2, §5.3. |
| D9 | **Admin routes live in `app/access/router.py`** (prefix `/api/v1/admin`), not in a separate `api/admin` package as spec §8 sketches. | ARCHITECTURE.md §2.2: a module owns its router; this keeps the admin API next to the service it calls. |
| D10 | **No self-escalation.** Nobody grants to themselves or lifts a deny on themselves; a capability grant, or lifting a capability deny, requires holding that capability; a role can only be assigned if its capabilities are within the actor's own. This covers direct grants; access gained through a group is allowed and relies on the rbac_changes audit trail. | Added after review: without it an `admin:users` holder could widen their own access. |

## File map

| File | Responsibility |
|---|---|
| `backend/app/access/__init__.py` | Public interface: `Policy`, `policy_for`, `get_policy`, `require_capability`, `access_router`, `access_error_handler`, `AccessError`, `prepare_access`, capability codes, `evaluate` + facts (for evals) |
| `backend/app/access/catalog.py` | Capability codes and the cumulative role bundles (§5.1) |
| `backend/app/access/patterns.py` | Resource-pattern validation and matching (§2) |
| `backend/app/access/facts.py` | Plain evaluator inputs and the access vocabulary constants |
| `backend/app/access/errors.py` | Access errors, each with its HTTP status |
| `backend/app/access/policy.py` | `Policy`, `Rule`, `Decision`: the only object enforcement consults |
| `backend/app/access/evaluator.py` | `evaluate(inputs, now) -> Policy`, pure (§5.4) |
| `backend/app/access/cache.py` | `PolicyCache` keyed by `(user_id, policy_version)`, expiry-aware, bounded |
| `backend/app/access/models.py` | Tables: `capabilities`, `groups`, `group_members`, `grants`, `rbac_changes`, `policy_state` |
| `backend/app/access/repository.py` | All access DB reads; staged writes; version bump |
| `backend/app/access/service.py` | `AccessService.policy_for` (fail closed) and `policy_for(db, principal)` |
| `backend/app/access/startup.py` | `prepare_access`: sync the capability catalog, bump the version |
| `backend/app/access/admin.py` | `AccessAdmin` + `Actor`: groups, members, grants, roles, status, preview, change log |
| `backend/app/access/schemas.py` | API request/response models |
| `backend/app/access/dependencies.py` | `get_policy`, `require_capability`, `get_actor`, `get_access_admin`, error handler |
| `backend/app/access/router.py` | `/api/v1/me/access`, `/api/v1/meta/capabilities`, `/api/v1/admin/...` |
| `backend/app/access/cli.py` | Admin CLI |
| `backend/migrations/versions/0003_access.py` | Tables, seeds, audit columns, chat ownership cleanup |
| `backend/app/atlas/policy.py` (new) | `ResourcePolicy` protocol, `AtlasCaller`, resource-path builders |
| `backend/app/atlas/tools.py` (modify) | Discovery filtering, execution checks, decision audit |
| `backend/app/agent/{loop,guardrails,prompts}.py` (modify) | Turn takes `AtlasTools`; guardrails by `user_id`; honest-denial rule |
| `backend/app/api/chat.py`, `backend/app/insights/*`, `backend/app/mcp/server.py` (modify) | Capability gates; pass the caller's Policy |
| `backend/app/identity/{bootstrap,service,__init__}.py` (modify) | `ensure_service_user`, `service_principal`; exports; `disable_user` removed (D3) |
| `backend/app/middleware/` (delete) | Deprecated shim, no users left |
| `backend/tests/access/…`, `backend/tests/access_helpers.py`, `backend/tests/fakes.py` | Tests and shared test helpers |
| `evals/run_evals.py`, `evals/goldens/core_metrics.yaml` | Per-golden policy; an honest-denial golden |
| `backend/pyproject.toml`, `ARCHITECTURE.md`, `README.md`, `CLAUDE.md`, `backend/.env.example`, `Makefile` | Contracts, strict typing, docs, `make dev-access` |

---

### Task 1: Capability catalog, resource patterns, errors, facts

**Files:**
- Create: `backend/app/access/__init__.py` (docstring only for now), `backend/app/access/catalog.py`,
  `backend/app/access/patterns.py`, `backend/app/access/errors.py`, `backend/app/access/facts.py`
- Test: `backend/tests/access/__init__.py` (empty), `backend/tests/access/test_catalog.py`,
  `backend/tests/access/test_patterns.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_catalog.py
from app.access.catalog import (
    ADMIN_GROUPS,
    CAPABILITIES,
    CHAT_USE,
    MCP_USE,
    ROLES,
    role_capabilities,
)


def test_roles_are_cumulative() -> None:
    bundles = [role_capabilities(role) for role in ROLES]
    for lower, higher in zip(bundles, bundles[1:], strict=False):
        assert lower < higher


def test_viewer_can_only_chat() -> None:
    assert role_capabilities("viewer") == {CHAT_USE}


def test_mcp_starts_at_analyst_and_admin_actions_at_admin() -> None:
    assert MCP_USE not in role_capabilities("viewer")
    assert MCP_USE in role_capabilities("analyst")
    assert ADMIN_GROUPS not in role_capabilities("builder")
    assert ADMIN_GROUPS in role_capabilities("admin")


def test_unknown_role_grants_nothing() -> None:
    assert role_capabilities("superuser") == frozenset()


def test_every_capability_is_described_and_reachable() -> None:
    assert all(CAPABILITIES.values())
    assert set(CAPABILITIES) == role_capabilities("admin")
```

```python
# backend/tests/access/test_patterns.py
import pytest

from app.access.patterns import InvalidPatternError, matches, validate_pattern


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*", "demo/order/revenue", True),
        ("*", "demo/order", True),
        ("demo/*", "demo/order/revenue", True),
        ("demo/*", "demo/order", True),
        ("demo/*", "demo", False),
        ("demo/order/*", "demo/order/revenue", True),
        ("demo/order/*", "demo/order", False),
        ("demo/order/*", "demo/checkout/checkout_funnel", False),
        ("demo/order/revenue", "demo/order/revenue", True),
        ("demo/order/revenue", "demo/order/aov", False),
        ("demo/*/revenue", "demo/order/revenue", True),
        ("demo/*/revenue", "demo/order/aov", False),
        ("deepsales/*", "demo/order/revenue", False),
        ("demo/order", "demo/order", True),
        ("demo/order", "demo/order/revenue", False),
    ],
)
def test_matches(pattern: str, path: str, expected: bool) -> None:
    assert matches(pattern, path) is expected


@pytest.mark.parametrize(
    "pattern", ["*", "deepsales/*", "demo/order/revenue", "demo/*/revenue"]
)
def test_valid_patterns(pattern: str) -> None:
    assert validate_pattern(pattern) == pattern


@pytest.mark.parametrize(
    "pattern",
    ["", "demo//x", "Demo/*", "demo/order/revenue/x", "demo/*x", "demo/a b", "../x"],
)
def test_invalid_patterns(pattern: str) -> None:
    with pytest.raises(InvalidPatternError):
        validate_pattern(pattern)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.access'`.

- [ ] **Step 3: Implement**

```python
# backend/app/access/__init__.py
"""Access: what a caller may do and see (spec §5). Other modules import only from here."""
```

```python
# backend/app/access/catalog.py
"""Capabilities and roles (spec §5.1). Code is the source of truth; the DB mirrors it."""

from typing import Final

CHAT_USE: Final = "chat:use"
MCP_USE: Final = "mcp:use"
TOKENS_CREATE: Final = "tokens:create"
EXPORT_DATA: Final = "export:data"
SANDBOX_RUN: Final = "sandbox:run"
ALERTS_MANAGE: Final = "alerts:manage"
SCHEDULES_MANAGE: Final = "schedules:manage"
ANALYSES_SAVE: Final = "analyses:save"
ADMIN_USERS: Final = "admin:users"
ADMIN_GROUPS: Final = "admin:groups"
ADMIN_AUDIT: Final = "admin:audit"
ADMIN_TOKENS: Final = "admin:tokens"
ADMIN_CLIENTS: Final = "admin:clients"

CAPABILITIES: Final[dict[str, str]] = {
    CHAT_USE: "Use the atlas web chat and dashboard",
    MCP_USE: "Connect MCP clients such as Claude Code, claude.ai or Claude Desktop",
    TOKENS_CREATE: "Create personal access tokens",
    EXPORT_DATA: "Export results as files",
    SANDBOX_RUN: "Run analyses in the sandbox",
    ALERTS_MANAGE: "Create and manage alerts",
    SCHEDULES_MANAGE: "Create and manage schedules",
    ANALYSES_SAVE: "Save analyses for reuse",
    ADMIN_USERS: "Manage users, roles, status and direct grants",
    ADMIN_GROUPS: "Manage groups, members and group grants",
    ADMIN_AUDIT: "Read the audit and access-change logs",
    ADMIN_TOKENS: "Manage everyone's tokens",
    ADMIN_CLIENTS: "Manage connected OAuth clients",
}

# Ascending: each role includes everything below it.
ROLES: Final[tuple[str, ...]] = ("viewer", "analyst", "builder", "admin")

_ADDS: Final[dict[str, frozenset[str]]] = {
    "viewer": frozenset({CHAT_USE}),
    "analyst": frozenset({MCP_USE, TOKENS_CREATE, EXPORT_DATA, SANDBOX_RUN}),
    "builder": frozenset({ALERTS_MANAGE, SCHEDULES_MANAGE, ANALYSES_SAVE}),
    "admin": frozenset(
        {ADMIN_USERS, ADMIN_GROUPS, ADMIN_AUDIT, ADMIN_TOKENS, ADMIN_CLIENTS}
    ),
}


def role_capabilities(role: str) -> frozenset[str]:
    """The role's cumulative bundle. An unknown role grants nothing (fail closed)."""
    if role not in ROLES:
        return frozenset()
    bundle: set[str] = set()
    for name in ROLES[: ROLES.index(role) + 1]:
        bundle |= _ADDS[name]
    return frozenset(bundle)
```

```python
# backend/app/access/patterns.py
"""Resource paths and grant patterns (spec §2).

A resource path is `source/entity/item` (an entity itself is `source/entity`).
Pattern segments are literal or `*`. A trailing `*` matches one or more remaining
segments, so `deepsales/*` covers every entity and item in DeepSales; a `*` in
the middle matches exactly one segment.
"""

import re

_SEGMENT = re.compile(r"[a-z0-9_]+")
MAX_SEGMENTS = 3


class InvalidPatternError(ValueError):
    """A grant target that is not a resource pattern."""


def validate_pattern(pattern: str) -> str:
    segments = pattern.split("/")
    if not 1 <= len(segments) <= MAX_SEGMENTS or any(
        s != "*" and not _SEGMENT.fullmatch(s) for s in segments
    ):
        msg = (
            f"'{pattern}' is not a resource pattern. Use paths like '*', "
            "'deepsales/*' or 'demo/order/revenue'."
        )
        raise InvalidPatternError(msg)
    return pattern


def matches(pattern: str, path: str) -> bool:
    want = pattern.split("/")
    have = path.split("/")
    if want[-1] == "*":
        prefix = want[:-1]
        return len(have) > len(prefix) and _same(prefix, have)
    return len(want) == len(have) and _same(want, have)


def _same(pattern: list[str], path: list[str]) -> bool:
    return all(p in ("*", s) for p, s in zip(pattern, path, strict=False))
```

```python
# backend/app/access/errors.py
"""Access failures. Each carries the HTTP status the API maps it to."""

from typing import ClassVar


class AccessError(Exception):
    status_code: ClassVar[int] = 400


class AccessDeniedError(AccessError):
    """403: the caller may not do this."""

    status_code: ClassVar[int] = 403


class NotFoundError(AccessError):
    status_code: ClassVar[int] = 404


class ConflictError(AccessError):
    status_code: ClassVar[int] = 409


class InvalidChangeError(AccessError):
    status_code: ClassVar[int] = 422


class PolicyUnavailableError(AccessError):
    """503: the policy could not be evaluated, so everything is denied (spec §12)."""

    status_code: ClassVar[int] = 503
```

```python
# backend/app/access/facts.py
"""Plain inputs to the evaluator (spec §5.4) and the access vocabulary.

No database, HTTP or clock here: the repository builds these, the evaluator reads them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

SUBJECT_GROUP: Final = "group"
SUBJECT_USER: Final = "user"
EFFECT_ALLOW: Final = "allow"
EFFECT_DENY: Final = "deny"
KIND_RESOURCE: Final = "resource"
KIND_CAPABILITY: Final = "capability"
KIND_CLEARANCE: Final = "clearance"  # phase 3; ignored until then (decision D1)
STANDING_MEMBER: Final = "member"
STANDING_MANAGER: Final = "manager"
DEFAULT_TENANT: Final = "ygg"


@dataclass(frozen=True, slots=True)
class UserFacts:
    id: UUID
    role: str
    status: str
    tenant: str


@dataclass(frozen=True, slots=True)
class GroupFacts:
    id: UUID
    name: str
    parent_id: UUID | None
    tenant: str


@dataclass(frozen=True, slots=True)
class GrantFacts:
    id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    target_kind: str
    target: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PolicyInputs:
    user: UserFacts
    groups: Mapping[UUID, GroupFacts]  # every group in the user's tenant
    memberships: Mapping[UUID, str]  # group id -> standing, for this user
    grants: Sequence[GrantFacts]  # grants on this user and on the tenant's groups
    policy_version: int
```

Create `backend/tests/access/__init__.py` as an empty file.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/access -q`
Expected: all pass (5 catalog tests + 26 pattern cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/access backend/tests/access
git commit -m "feat(access): capability catalog, resource patterns, errors and facts"
```

---

### Task 2: Policy and the evaluator

**Files:**
- Create: `backend/app/access/policy.py`, `backend/app/access/evaluator.py`
- Modify: `backend/app/identity/__init__.py` (export `User`, `UserStatus`, `UserKind`)
- Test: `backend/tests/access/test_evaluator.py`

- [ ] **Step 1: Export the identity types access needs**

Replace `backend/app/identity/__init__.py` with:

```python
"""Identity: who is calling. Other modules import only from here."""

from app.identity.bootstrap import bootstrap_admins
from app.identity.dependencies import get_principal, get_token_verifier
from app.identity.models import User, UserKind, UserStatus
from app.identity.principal import Principal
from app.identity.router import router as identity_router
from app.identity.tokens import TokenVerifier

__all__ = [
    "Principal",
    "TokenVerifier",
    "User",
    "UserKind",
    "UserStatus",
    "bootstrap_admins",
    "get_principal",
    "get_token_verifier",
    "identity_router",
]
```

- [ ] **Step 2: Write the failing tests (table-driven, spec §13)**

```python
# backend/tests/access/test_evaluator.py
"""The evaluator, case by case (spec §5.4, §13). Pure: no database."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.access.catalog import ADMIN_GROUPS, CHAT_USE, MCP_USE
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, GroupFacts, PolicyInputs, UserFacts
from app.access.policy import Policy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
USER = uuid4()
ROOT, CHILD, OTHER_TENANT = uuid4(), uuid4(), uuid4()
GROUPS = {
    ROOT: GroupFacts(ROOT, "marketing", None, "ygg"),
    CHILD: GroupFacts(CHILD, "growth", ROOT, "ygg"),
    OTHER_TENANT: GroupFacts(OTHER_TENANT, "acme", None, "acme"),
}
REVENUE = "demo/order/revenue"


def grant(
    subject: UUID,
    target: str = "*",
    *,
    effect: str = "allow",
    kind: str = "resource",
    expires_at: datetime | None = None,
) -> GrantFacts:
    subject_type = "user" if subject == USER else "group"
    return GrantFacts(uuid4(), subject_type, subject, effect, kind, target, expires_at)


def policy(
    *,
    role: str = "viewer",
    status: str = "active",
    member_of: dict[UUID, str] | None = None,
    grants: Iterable[GrantFacts] = (),
    groups: dict[UUID, GroupFacts] | None = None,
) -> Policy:
    inputs = PolicyInputs(
        user=UserFacts(USER, role, status, "ygg"),
        groups=GROUPS if groups is None else groups,
        memberships=member_of or {},
        grants=list(grants),
        policy_version=7,
    )
    return evaluate(inputs, NOW)


def test_new_user_can_chat_but_sees_no_data() -> None:
    p = policy()
    assert p.has(CHAT_USE)
    assert not p.allows(REVENUE)
    assert not p.has_data_access
    assert p.policy_version == 7


def test_group_grant_applies_to_members_only() -> None:
    g = grant(ROOT, "demo/*")
    assert policy(member_of={ROOT: "member"}, grants=[g]).allows(REVENUE)
    assert not policy(grants=[g]).allows(REVENUE)


def test_subgroup_members_inherit_parent_grants() -> None:
    assert policy(member_of={CHILD: "member"}, grants=[grant(ROOT)]).allows(REVENUE)


def test_parent_members_do_not_inherit_subgroup_grants() -> None:
    assert not policy(member_of={ROOT: "member"}, grants=[grant(CHILD)]).allows(
        REVENUE
    )


def test_deny_wins_at_every_level() -> None:
    allow_child = grant(CHILD, "demo/*")
    deny_parent = grant(ROOT, "demo/order/*", effect="deny")
    p = policy(member_of={CHILD: "member"}, grants=[allow_child, deny_parent])
    assert not p.allows(REVENUE)
    assert p.allows("demo/checkout/checkout_funnel")


def test_direct_user_allow_cannot_beat_a_group_deny() -> None:
    p = policy(
        member_of={ROOT: "member"},
        grants=[grant(USER, REVENUE), grant(ROOT, "demo/*", effect="deny")],
    )
    assert not p.allows(REVENUE)


def test_direct_user_grant_works_without_groups() -> None:
    p = policy(grants=[grant(USER, REVENUE)])
    decision = p.decide(REVENUE)
    assert decision.allowed
    assert decision.rule is not None
    assert decision.rule.origin == "user"


def test_decision_names_the_deciding_grant_and_group() -> None:
    deny = grant(ROOT, "demo/*", effect="deny")
    p = policy(member_of={ROOT: "member"}, grants=[grant(ROOT), deny])
    assert p.deny_reason(REVENUE) == f"denied by grant {deny.id} (group:marketing)"
    assert policy().deny_reason(REVENUE) == "no grant allows it"


def test_expired_grants_are_ignored() -> None:
    past = grant(USER, expires_at=NOW - timedelta(minutes=1))
    assert not policy(grants=[past]).allows(REVENUE)


def test_future_expiry_is_kept_and_bounds_the_cache() -> None:
    soon = NOW + timedelta(hours=1)
    later = NOW + timedelta(days=1)
    p = policy(grants=[grant(USER, expires_at=later), grant(USER, expires_at=soon)])
    assert p.allows(REVENUE)
    assert p.valid_until == soon


def test_user_capability_overrides() -> None:
    p = policy(
        grants=[
            grant(USER, MCP_USE, kind="capability"),
            grant(USER, CHAT_USE, kind="capability", effect="deny"),
        ]
    )
    assert p.has(MCP_USE)
    assert not p.has(CHAT_USE)


def test_groups_never_grant_capabilities() -> None:
    p = policy(member_of={ROOT: "member"}, grants=[grant(ROOT, MCP_USE, kind="capability")])
    assert not p.has(MCP_USE)


def test_unknown_capability_grant_is_ignored() -> None:
    p = policy(grants=[grant(USER, "root:everything", kind="capability")])
    assert p.capabilities == {CHAT_USE}


def test_clearance_grants_are_ignored_until_phase_3() -> None:
    p = policy(grants=[grant(USER, "fields:people_names", kind="clearance")])
    assert not p.has_data_access


def test_other_tenants_groups_grant_nothing() -> None:
    p = policy(member_of={OTHER_TENANT: "member"}, grants=[grant(OTHER_TENANT)])
    assert not p.allows(REVENUE)


def test_disabled_user_gets_nothing() -> None:
    p = policy(status="disabled", grants=[grant(USER)])
    assert not p.active
    assert not p.has(CHAT_USE)
    assert not p.allows(REVENUE)


def test_unknown_role_gets_no_capabilities() -> None:
    assert policy(role="superuser").capabilities == frozenset()


def test_unknown_effect_grants_nothing() -> None:
    assert not policy(grants=[grant(USER, effect="maybe")]).allows(REVENUE)


def test_a_group_cycle_cannot_hang_the_evaluator() -> None:
    a, b = uuid4(), uuid4()
    cyclic = {a: GroupFacts(a, "a", b, "ygg"), b: GroupFacts(b, "b", a, "ygg")}
    p = policy(member_of={a: "member"}, grants=[grant(b)], groups=cyclic)
    assert p.allows(REVENUE)


def test_managers_manage_their_group_and_its_subgroups() -> None:
    manager = policy(member_of={ROOT: "manager"})
    assert manager.can_manage_members(ROOT)
    assert manager.can_manage_members(CHILD)
    member = policy(member_of={ROOT: "member"})
    assert not member.can_manage_members(ROOT)


def test_admin_groups_capability_manages_any_group() -> None:
    admin = policy(role="admin")
    assert admin.has(ADMIN_GROUPS)
    assert admin.can_manage_members(CHILD)
    assert not admin.allows(REVENUE)  # decision D2: no data bypass for admins
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/access/test_evaluator.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.access.evaluator'`.

- [ ] **Step 4: Implement**

```python
# backend/app/access/policy.py
"""The evaluated access of one user at one policy_version (spec §2).

It is the only object enforcement code consults. Immutable, so it is safe to cache.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from app.access.catalog import ADMIN_GROUPS
from app.access.patterns import matches

NO_GRANT = "no grant allows it"


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: str
    grant_id: UUID
    origin: str  # "user", or "group:<name>"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    rule: Rule | None = None  # the deny that won, or the allow that matched

    @property
    def reason(self) -> str:
        if self.rule is None:
            return NO_GRANT
        verb = "allowed" if self.allowed else "denied"
        return f"{verb} by grant {self.rule.grant_id} ({self.rule.origin})"


@dataclass(frozen=True, slots=True)
class Policy:
    user_id: UUID
    tenant: str
    role: str
    active: bool
    policy_version: int
    capabilities: frozenset[str] = frozenset()
    allow_rules: tuple[Rule, ...] = ()
    deny_rules: tuple[Rule, ...] = ()
    group_ids: frozenset[UUID] = frozenset()
    managed_group_ids: frozenset[UUID] = frozenset()
    valid_until: datetime | None = None  # earliest expiry among the grants used

    @classmethod
    def deny_all(
        cls, user_id: UUID, tenant: str, policy_version: int, role: str = ""
    ) -> Self:
        return cls(
            user_id=user_id,
            tenant=tenant,
            role=role,
            active=False,
            policy_version=policy_version,
        )

    def has(self, capability: str) -> bool:
        return self.active and capability in self.capabilities

    def decide(self, resource: str) -> Decision:
        if not self.active:
            return Decision(allowed=False)
        for rule in self.deny_rules:
            if matches(rule.pattern, resource):
                return Decision(allowed=False, rule=rule)
        for rule in self.allow_rules:
            if matches(rule.pattern, resource):
                return Decision(allowed=True, rule=rule)
        return Decision(allowed=False)

    def allows(self, resource: str) -> bool:
        return self.decide(resource).allowed

    def deny_reason(self, resource: str) -> str:
        return self.decide(resource).reason

    @property
    def has_data_access(self) -> bool:
        return self.active and bool(self.allow_rules)

    def can_manage_members(self, group_id: UUID) -> bool:
        if self.has(ADMIN_GROUPS):
            return True
        return self.active and group_id in self.managed_group_ids
```

```python
# backend/app/access/evaluator.py
"""Evaluates one user's access from plain facts (spec §5.4). Pure: no I/O, no clock."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from app.access.catalog import CAPABILITIES, role_capabilities
from app.access.facts import (
    EFFECT_ALLOW,
    EFFECT_DENY,
    KIND_CAPABILITY,
    KIND_RESOURCE,
    STANDING_MANAGER,
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    PolicyInputs,
)
from app.access.policy import Policy, Rule
from app.identity import UserStatus

type Groups = Mapping[UUID, GroupFacts]


def evaluate(inputs: PolicyInputs, now: datetime) -> Policy:
    user = inputs.user
    if user.status != UserStatus.ACTIVE:
        return Policy.deny_all(user.id, user.tenant, inputs.policy_version, user.role)
    groups = {gid: g for gid, g in inputs.groups.items() if g.tenant == user.tenant}
    member_of = frozenset(gid for gid in inputs.memberships if gid in groups)
    reach = _with_ancestors(member_of, groups)
    grants = [g for g in inputs.grants if _applies(g, user.id, reach) and _live(g, now)]
    allow, deny = _resource_rules(grants, groups)
    managed = {g for g in member_of if inputs.memberships[g] == STANDING_MANAGER}
    expiries = [g.expires_at for g in grants if g.expires_at is not None]
    return Policy(
        user_id=user.id,
        tenant=user.tenant,
        role=user.role,
        active=True,
        policy_version=inputs.policy_version,
        capabilities=_capabilities(user.role, grants),
        allow_rules=allow,
        deny_rules=deny,
        group_ids=member_of,
        managed_group_ids=_with_descendants(managed, groups),
        valid_until=min(expiries, default=None),
    )


def _live(grant: GrantFacts, now: datetime) -> bool:
    return grant.expires_at is None or grant.expires_at > now


def _applies(grant: GrantFacts, user_id: UUID, reach: frozenset[UUID]) -> bool:
    if grant.subject_type == SUBJECT_USER:
        return grant.subject_id == user_id
    return grant.subject_type == SUBJECT_GROUP and grant.subject_id in reach


def _with_ancestors(start: Iterable[UUID], groups: Groups) -> frozenset[UUID]:
    """The groups plus every ancestor. Cycle-safe: a group is visited once."""
    seen: set[UUID] = set()
    for gid in start:
        current: UUID | None = gid
        while current is not None and current in groups and current not in seen:
            seen.add(current)
            current = groups[current].parent_id
    return frozenset(seen)


def _with_descendants(roots: Iterable[UUID], groups: Groups) -> frozenset[UUID]:
    children: dict[UUID, list[UUID]] = {}
    for group in groups.values():
        if group.parent_id is not None:
            children.setdefault(group.parent_id, []).append(group.id)
    seen: set[UUID] = set()
    stack = list(roots)
    while stack:
        gid = stack.pop()
        if gid not in seen:
            seen.add(gid)
            stack.extend(children.get(gid, ()))
    return frozenset(seen)


def _capabilities(role: str, grants: Sequence[GrantFacts]) -> frozenset[str]:
    """Role bundle + direct user allows - direct user denies (spec §5.4 step 1)."""
    overrides = [
        g
        for g in grants
        if g.subject_type == SUBJECT_USER
        and g.target_kind == KIND_CAPABILITY
        and g.target in CAPABILITIES
    ]
    allowed = {g.target for g in overrides if g.effect == EFFECT_ALLOW}
    denied = {g.target for g in overrides if g.effect == EFFECT_DENY}
    return frozenset((role_capabilities(role) | allowed) - denied)


def _rule_key(rule: Rule) -> tuple[str, str]:
    return rule.pattern, str(rule.grant_id)


def _resource_rules(
    grants: Sequence[GrantFacts], groups: Groups
) -> tuple[tuple[Rule, ...], tuple[Rule, ...]]:
    allow: list[Rule] = []
    deny: list[Rule] = []
    for g in grants:
        if g.target_kind != KIND_RESOURCE or g.effect not in (EFFECT_ALLOW, EFFECT_DENY):
            continue
        origin = "user" if g.subject_type == SUBJECT_USER else f"group:{groups[g.subject_id].name}"
        (deny if g.effect == EFFECT_DENY else allow).append(Rule(g.target, g.id, origin))
    return tuple(sorted(allow, key=_rule_key)), tuple(sorted(deny, key=_rule_key))
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run ruff format app/access tests/access && uv run pytest tests/access -q`
Expected: all pass. `ruff format` wraps the two long lines in `_resource_rules`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/access backend/app/identity/__init__.py backend/tests/access
git commit -m "feat(access): Policy and the pure evaluator (deny wins, inheritance, expiry)"
```

---

### Task 3: Tables, migration 0003, ownership cleanup

**Files:**
- Create: `backend/app/access/models.py`, `backend/migrations/versions/0003_access.py`
- Modify: `backend/app/models/chat.py`, `backend/app/models/audit.py`, `backend/tests/conftest.py`,
  `backend/migrations/env.py`
- Test: `backend/tests/test_alembic.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alembic.py`:

```python
STARTER_GROUPS = {"atlas-admins", "leadership", "marketing", "csm", "risk-ops", "engineering"}


def test_access_tables_and_seeds(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        groups = set(conn.execute(sa.text("SELECT name FROM groups")).scalars())
        version = conn.execute(
            sa.text("SELECT policy_version FROM policy_state WHERE id = 1")
        ).scalar_one()
        session_columns = {
            c["name"] for c in sa.inspect(conn).get_columns("chat_sessions")
        }
    engine.dispose()
    assert groups == STARTER_GROUPS
    assert version == 1
    assert "user_uid" not in session_columns  # decision D6


def _seed_user_and_audit(sync_url: str, user_id: UUID, firebase_uid: str) -> None:
    engine = sa.create_engine(sync_url)
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("email", sa.String()),
        sa.column("firebase_uid", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("role", sa.String()),
        sa.column("tenant", sa.String()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    )
    audit = sa.table(
        "atlas_audit_log",
        sa.column("id", sa.Uuid()),
        sa.column("user_uid", sa.String()),
        sa.column("surface", sa.String()),
        sa.column("tool", sa.String()),
        sa.column("success", sa.Boolean()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
    )
    now = sa.func.current_timestamp()
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email="sara@yougotagift.com",
                firebase_uid=firebase_uid,
                display_name="",
                status="active",
                kind="human",
                role="viewer",
                tenant="ygg",
                created_at=now,
            )
        )
        for owner in (str(user_id), firebase_uid, "nobody"):
            conn.execute(
                audit.insert().values(
                    id=uuid4(),
                    user_uid=owner,
                    surface="chat",
                    tool="query_metric",
                    success=True,
                    created_at=now,
                )
            )
    engine.dispose()


def test_audit_rows_gain_user_id(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0002")
    user_id = uuid4()
    _seed_user_and_audit(f"sqlite:///{db}", user_id, "fb-sara")

    command.upgrade(config, "0003")

    engine = sa.create_engine(f"sqlite:///{db}")
    audit = sa.table(
        "atlas_audit_log", sa.column("user_uid", sa.String()), sa.column("user_id", sa.Uuid())
    )
    with engine.connect() as conn:
        owners = dict(conn.execute(sa.select(audit.c.user_uid, audit.c.user_id)).all())
    engine.dispose()
    assert owners[str(user_id)] == user_id
    assert owners["fb-sara"] == user_id  # pre-0002 rows join through firebase_uid
    assert owners["nobody"] is None


def test_sessions_without_an_owner_stop_the_migration(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0002")
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chat_sessions (id, user_uid, user_email, title, "
                "created_at, updated_at) VALUES (:id, 'orphan', '', 't', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": uuid4().hex},
        )
    engine.dispose()
    with pytest.raises(RuntimeError, match="no user_id"):
        command.upgrade(config, "0003")
```

In the same file:
- add `from uuid import UUID, uuid4` (replacing `from uuid import uuid4`) and `import pytest` with the
  other imports, and `import app.access.models  # noqa: F401  # registers access tables` next to the
  existing metadata-registering imports;
- in `test_head_matches_model_columns`, change the table tuple to:

```python
        for table in (
            "users",
            "chat_sessions",
            "chat_messages",
            "atlas_audit_log",
            "capabilities",
            "groups",
            "group_members",
            "grants",
            "rbac_changes",
            "policy_state",
        ):
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_alembic.py -q`
Expected: FAIL (no revision `0003`; no `app.access.models`).

- [ ] **Step 3: Add the tables**

```python
# backend/app/access/models.py
"""Access-control tables (spec §7). Row scopes and clearances arrive in phase 3."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, TIMESTAMP, BigInteger, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.access.facts import DEFAULT_TENANT, STANDING_MEMBER


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Capability(SQLModel, table=True):
    """Mirror of the code catalog (app.access.catalog), synced at startup."""

    __tablename__ = "capabilities"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    code: str = Field(primary_key=True, max_length=64)
    description: str = Field(max_length=200)
    deprecated: bool = False


class Group(SQLModel, table=True):
    __tablename__ = "groups"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr
    __table_args__ = (UniqueConstraint("tenant", "name", name="uq_groups_tenant_name"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=100)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = Field(default=None, foreign_key="groups.id", index=True)
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64)
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class GroupMember(SQLModel, table=True):
    __tablename__ = "group_members"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    group_id: UUID = Field(foreign_key="groups.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True, index=True)
    standing: str = Field(default=STANDING_MEMBER, max_length=16)
    added_by: UUID | None = Field(default=None, foreign_key="users.id")
    added_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class Grant(SQLModel, table=True):
    __tablename__ = "grants"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    subject_type: str = Field(max_length=16)
    subject_id: UUID = Field(index=True)
    effect: str = Field(max_length=16)
    target_kind: str = Field(max_length=16)
    target: str = Field(max_length=200)
    reason: str = Field(default="", max_length=500)
    expires_at: datetime | None = Field(
        default=None, sa_type=TIMESTAMP(timezone=True)
    )
    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class RbacChange(SQLModel, table=True):
    """Append-only record of every access change (spec §9)."""

    __tablename__ = "rbac_changes"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    actor_user_id: UUID | None = Field(
        default=None, foreign_key="users.id", index=True
    )
    via: str = Field(default="api", max_length=16)  # 'api' | 'cli'
    action: str = Field(max_length=64)
    object_type: str = Field(max_length=32)
    object_id: str = Field(max_length=100)
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True), index=True
    )


class PolicyState(SQLModel, table=True):
    """Single row. Every access write increments policy_version (spec §8)."""

    __tablename__ = "policy_state"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: int = Field(default=1, primary_key=True)
    policy_version: int = Field(default=1, sa_type=BigInteger)
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
```

Note: `__table_args__` may need the same `# pyright: ignore[reportAssignmentType]` comment if pyright
flags it; add it only if `uv run pyright app/access/models.py` reports that error.

- [ ] **Step 4: Change the chat and audit models (decision D6)**

In `backend/app/models/chat.py`, replace the three `ChatSession` owner lines:

```python
    user_uid: str = Field(index=True)
    # Owner (atlas users.id). user_uid holds the same id as text for components that
    # still key on strings (guardrails, audit) until phase 2 passes a Principal.
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
```

with:

```python
    user_id: UUID = Field(foreign_key="users.id", index=True)  # the owner (users.id)
```

In `backend/app/models/audit.py`, replace the `user_uid` line with:

```python
    # Legacy owner key: a Firebase uid before migration 0002, the atlas id after it.
    # Append-only, so it is kept; new code reads user_id.
    user_uid: str = Field(index=True)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    auth_method: str | None = Field(default=None, max_length=16)
```

and after the `error` line add:

```python
    decision: str = Field(default="allow", max_length=8)  # 'allow' | 'deny'
    deny_reason: str | None = Field(default=None, max_length=200)
```

- [ ] **Step 5: Write the migration**

```python
# backend/migrations/versions/0003_access.py
"""Access control (spec §7, §11.2) and the phase-2 ownership cleanup.

- New tables: capabilities, groups, group_members, grants, rbac_changes, policy_state.
- Seeds: policy_state (version 1) and the empty starter groups. Capabilities are
  synced from code at startup (app.access.startup), not here.
- atlas_audit_log gains user_id, auth_method, decision and deny_reason. user_id is
  backfilled from user_uid (an atlas id after 0002, a Firebase uid before it); the
  legacy column stays because the log is append-only.
- chat_sessions: user_id becomes required and the user_uid mirror is dropped.

Revision ID: 0003
Revises: 0002
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
TENANT = "ygg"
STARTER_GROUPS = (
    ("atlas-admins", "People who administer atlas access"),
    ("leadership", "Company leadership"),
    ("marketing", "Marketing and growth"),
    ("csm", "Customer success managers"),
    ("risk-ops", "Risk and fraud operations"),
    ("engineering", "Engineering"),
)

_users = sa.table(
    "users", sa.column("id", sa.Uuid()), sa.column("firebase_uid", sa.String())
)
_audit = sa.table(
    "atlas_audit_log", sa.column("user_uid", sa.String()), sa.column("user_id", sa.Uuid())
)
_sessions = sa.table(
    "chat_sessions", sa.column("user_uid", sa.String()), sa.column("user_id", sa.Uuid())
)
_groups = sa.table(
    "groups",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("description", sa.String()),
    sa.column("tenant", sa.String()),
    sa.column("created_at", TS),
)
_policy_state = sa.table(
    "policy_state",
    sa.column("id", sa.Integer()),
    sa.column("policy_version", sa.BigInteger()),
    sa.column("updated_at", TS),
)


def upgrade() -> None:
    _create_tables()
    _seed()
    _extend_audit()
    _require_session_owner()


def _create_tables() -> None:
    op.create_table(
        "capabilities",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("deprecated", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("groups.id"), nullable=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("tenant", "name", name="uq_groups_tenant_name"),
    )
    op.create_index("ix_groups_parent_id", "groups", ["parent_id"])
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("standing", sa.String(16), nullable=False),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_grants_subject_id", "grants", ["subject_id"])
    op.create_table(
        "rbac_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(100), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("at", TS, nullable=False),
    )
    op.create_index("ix_rbac_changes_actor_user_id", "rbac_changes", ["actor_user_id"])
    op.create_index("ix_rbac_changes_at", "rbac_changes", ["at"])
    op.create_table(
        "policy_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def _seed() -> None:
    now = datetime.now(UTC)
    op.bulk_insert(_policy_state, [{"id": 1, "policy_version": 1, "updated_at": now}])
    op.bulk_insert(
        _groups,
        [
            {
                "id": uuid4(),
                "name": name,
                "description": description,
                "tenant": TENANT,
                "created_at": now,
            }
            for name, description in STARTER_GROUPS
        ],
    )


def _extend_audit() -> None:
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("auth_method", sa.String(16), nullable=True))
        batch.add_column(
            sa.Column(
                "decision", sa.String(8), nullable=False, server_default="allow"
            )
        )
        batch.add_column(sa.Column("deny_reason", sa.String(200), nullable=True))
        batch.create_index("ix_atlas_audit_log_user_id", ["user_id"])
        batch.create_foreign_key(
            "fk_atlas_audit_log_user_id_users", "users", ["user_id"], ["id"]
        )
    _backfill_audit_owners()


def _backfill_audit_owners() -> None:
    conn = op.get_bind()
    users = conn.execute(sa.select(_users.c.id, _users.c.firebase_uid)).all()
    by_id: dict[str, UUID] = {str(uid): uid for uid, _ in users}
    by_firebase: dict[str, UUID] = {fb: uid for uid, fb in users if fb}
    legacy = conn.execute(
        sa.select(_audit.c.user_uid).where(_audit.c.user_id.is_(None)).distinct()
    ).scalars()
    for user_uid in list(legacy):
        owner = by_id.get(user_uid) or by_firebase.get(user_uid)
        if owner is not None:
            conn.execute(
                _audit.update()
                .where(_audit.c.user_uid == user_uid)
                .where(_audit.c.user_id.is_(None))
                .values(user_id=owner)
            )


def _require_session_owner() -> None:
    orphans = (
        op.get_bind()
        .execute(
            sa.select(sa.func.count())
            .select_from(_sessions)
            .where(_sessions.c.user_id.is_(None))
        )
        .scalar_one()
    )
    if orphans:
        msg = (
            f"{orphans} chat sessions have no user_id; give each one an owner "
            "(see migration 0002's backfill) before upgrading"
        )
        raise RuntimeError(msg)
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_index("ix_chat_sessions_user_uid")
        batch.drop_column("user_uid")
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("user_uid", sa.String(), nullable=True))
    conn = op.get_bind()
    owners = conn.execute(sa.select(_sessions.c.user_id).distinct()).scalars()
    for owner in list(owners):
        conn.execute(
            _sessions.update()
            .where(_sessions.c.user_id == owner)
            .values(user_uid=str(owner))
        )
    with op.batch_alter_table("chat_sessions") as batch:
        batch.alter_column("user_uid", existing_type=sa.String(), nullable=False)
        batch.create_index("ix_chat_sessions_user_uid", ["user_uid"])
    with op.batch_alter_table("atlas_audit_log") as batch:
        batch.drop_constraint("fk_atlas_audit_log_user_id_users", type_="foreignkey")
        batch.drop_index("ix_atlas_audit_log_user_id")
        for column in ("deny_reason", "decision", "auth_method", "user_id"):
            batch.drop_column(column)
    for table in (
        "policy_state",
        "rbac_changes",
        "grants",
        "group_members",
        "groups",
        "capabilities",
    ):
        op.drop_table(table)
```

- [ ] **Step 6: Register the tables for tests and Alembic**

In `backend/migrations/env.py`, add next to the other metadata imports:

```python
import app.access.models  # noqa: F401  # registers the access tables on the metadata
```

In `backend/tests/conftest.py`:
- add `import app.access.models  # noqa: F401  # registers the access tables for create_all`
  next to the identity import;
- inside the `db` fixture, after `await seed_demo(conn)`, seed the policy row that migration 0003
  creates in real databases:

```python
        await conn.execute(
            text(
                "INSERT INTO policy_state (id, policy_version, updated_at) "
                "VALUES (1, 1, :now)"
            ),
            {"now": datetime.now(UTC)},
        )
```

- [ ] **Step 7: Run the migration tests**

Run: `uv run pytest tests/test_alembic.py -q`
Expected: all pass, including `test_head_matches_model_columns` and the downgrade/upgrade round trip.
If the drift test fails, fix the migration to match the models, never the reverse.

Other suites (`test_chat_api`, `test_agent_loop`, `test_guardrails`, `test_atlas_tools`) now fail
because `ChatSession.user_uid` is gone. Tasks 10–12 fix them; do not patch them here.

- [ ] **Step 8: Commit**

```bash
git add backend/app/access/models.py backend/app/models backend/migrations \
  backend/tests/test_alembic.py backend/tests/conftest.py
git commit -m "feat(access): access tables, migration 0003, required session owner"
```

---

### Task 4: Repository reads, policy cache, `policy_for` (fail closed)

**Files:**
- Create: `backend/app/access/repository.py`, `backend/app/access/cache.py`,
  `backend/app/access/service.py`, `backend/tests/access_helpers.py`
- Modify: `backend/tests/conftest.py` (clear the shared cache per test)
- Test: `backend/tests/access/test_cache.py`, `backend/tests/access/test_policy_service.py`

- [ ] **Step 1: Write the shared test helpers**

```python
# backend/tests/access_helpers.py
"""Direct-to-database helpers for tests. They skip AccessAdmin on purpose."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.models import Grant, Group, GroupMember, PolicyState
from app.identity.models import User


async def make_user(
    db: AsyncSession,
    email: str,
    *,
    role: str = "viewer",
    status: str = "active",
    kind: str = "human",
) -> User:
    user = User(email=email, role=role, status=status, kind=kind)
    db.add(user)
    await db.commit()
    return user


async def make_group(db: AsyncSession, name: str, *, parent: Group | None = None) -> Group:
    group = Group(name=name, parent_id=parent.id if parent else None)
    db.add(group)
    await db.commit()
    return group


async def add_member(
    db: AsyncSession, group: Group, user: User, standing: str = "member"
) -> GroupMember:
    member = GroupMember(group_id=group.id, user_id=user.id, standing=standing)
    db.add(member)
    await db.commit()
    await bump(db)
    return member


async def add_grant(
    db: AsyncSession,
    subject: Group | User,
    target: str = "*",
    *,
    effect: str = "allow",
    kind: str = "resource",
    expires_at: datetime | None = None,
    bump_version: bool = True,
) -> Grant:
    grant = Grant(
        subject_type="group" if isinstance(subject, Group) else "user",
        subject_id=subject.id,
        effect=effect,
        target_kind=kind,
        target=target,
        reason="test",
        expires_at=expires_at,
    )
    db.add(grant)
    await db.commit()
    if bump_version:
        await bump(db)
    return grant


async def bump(db: AsyncSession) -> None:
    await db.execute(
        update(PolicyState)
        .where(col(PolicyState.id) == 1)
        .values(policy_version=col(PolicyState.policy_version) + 1)
    )
    await db.commit()


async def grant_all(
    db: AsyncSession, email: str = "dev@yougotagift.com", *, role: str = "viewer"
) -> User:
    """What `make dev-access` does locally: give one user every resource."""
    user = (
        await db.execute(select(User).where(col(User.email) == email))
    ).scalar_one_or_none()
    if user is None:
        user = await make_user(db, email, role=role)
    else:
        user.role = role
        db.add(user)
        await db.commit()
    await add_grant(db, user, "*")
    return user
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/access/test_cache.py
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.access.cache import PolicyCache
from app.access.policy import Policy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _policy(version: int = 1, valid_until: datetime | None = None) -> Policy:
    return Policy(
        user_id=uuid4(),
        tenant="ygg",
        role="viewer",
        active=True,
        policy_version=version,
        valid_until=valid_until,
    )


def test_hit_only_for_the_same_version() -> None:
    cache = PolicyCache()
    policy = _policy(version=3)
    cache.put(policy)
    assert cache.get(policy.user_id, 3, NOW) is policy
    assert cache.get(policy.user_id, 4, NOW) is None


def test_entries_expire_with_their_grants() -> None:
    cache = PolicyCache()
    policy = _policy(valid_until=NOW + timedelta(minutes=5))
    cache.put(policy)
    assert cache.get(policy.user_id, 1, NOW) is policy
    assert cache.get(policy.user_id, 1, NOW + timedelta(minutes=5)) is None


def test_least_recently_used_entries_are_evicted() -> None:
    cache = PolicyCache(max_entries=2)
    first, second, third = _policy(), _policy(), _policy()
    cache.put(first)
    cache.put(second)
    assert cache.get(first.user_id, 1, NOW) is first  # first is now most recent
    cache.put(third)
    assert cache.get(second.user_id, 1, NOW) is None
    assert cache.get(first.user_id, 1, NOW) is first
```

```python
# backend/tests/access/test_policy_service.py
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.access import service as service_module
from app.access.cache import PolicyCache
from app.access.errors import PolicyUnavailableError
from app.access.models import PolicyState
from app.access.repository import AccessRepository
from app.access.service import AccessService
from tests.access_helpers import add_grant, add_member, bump, make_group, make_user

REVENUE = "demo/order/revenue"


def _service(db, clock=None) -> AccessService:
    return AccessService(
        AccessRepository(db), PolicyCache(), clock or (lambda: datetime.now(UTC))
    )


async def test_group_grant_reaches_members(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    group = await make_group(db, "marketing")
    await add_member(db, group, user)
    await add_grant(db, group, "demo/*")

    policy = await _service(db).policy_for_user(user.id)

    assert policy.allows(REVENUE)
    assert policy.has("chat:use")


async def test_policy_is_cached_until_the_version_moves(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    service = _service(db)
    first = await service.policy_for_user(user.id)

    await add_grant(db, user, "demo/*", bump_version=False)
    assert await service.policy_for_user(user.id) is first  # so every write must bump

    await bump(db)
    second = await service.policy_for_user(user.id)
    assert second is not first
    assert second.allows(REVENUE)


async def test_an_expiring_grant_drops_without_a_version_bump(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    expires = datetime.now(UTC) + timedelta(hours=1)
    await add_grant(db, user, "demo/*", expires_at=expires)
    now = [datetime.now(UTC)]
    service = _service(db, clock=lambda: now[0])

    assert (await service.policy_for_user(user.id)).allows(REVENUE)
    now[0] = expires + timedelta(seconds=1)
    assert not (await service.policy_for_user(user.id)).allows(REVENUE)


async def test_unknown_user_is_denied_everything(db) -> None:
    policy = await _service(db).policy_for_user(uuid4())
    assert not policy.active
    assert not policy.has("chat:use")


async def test_missing_policy_state_fails_closed(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await db.execute(delete(PolicyState))
    await db.commit()
    with pytest.raises(PolicyUnavailableError):
        await _service(db).policy_for_user(user.id)


async def test_evaluator_errors_fail_closed(db, monkeypatch) -> None:
    user = await make_user(db, "sara@yougotagift.com")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(service_module, "evaluate", broken)
    with pytest.raises(PolicyUnavailableError):
        await _service(db).policy_for_user(user.id)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/access/test_cache.py tests/access/test_policy_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.access.cache'`.

- [ ] **Step 4: Implement the cache**

```python
# backend/app/access/cache.py
"""Per-process Policy cache keyed by (user_id, policy_version) (spec §8).

Every access write bumps policy_version, so a new version simply misses. An entry
also expires when the earliest grant it used expires (no bump happens then).
"""

from collections import OrderedDict
from datetime import datetime
from uuid import UUID

from app.access.policy import Policy

DEFAULT_MAX_ENTRIES = 1024


class PolicyCache:
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._entries: OrderedDict[tuple[UUID, int], Policy] = OrderedDict()
        self._max = max_entries

    def get(self, user_id: UUID, version: int, now: datetime) -> Policy | None:
        key = (user_id, version)
        policy = self._entries.get(key)
        if policy is None:
            return None
        if policy.valid_until is not None and policy.valid_until <= now:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return policy

    def put(self, policy: Policy) -> None:
        key = (policy.user_id, policy.policy_version)
        self._entries[key] = policy
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


_shared = PolicyCache()


def shared_cache() -> PolicyCache:
    """The process-wide cache used by every request."""
    return _shared
```

- [ ] **Step 5: Implement the repository (evaluator reads)**

```python
# backend/app/access/repository.py
"""All database access for the access module.

Reads return plain facts or rows. Writes are staged (add, delete, bump_version);
the calling service commits once, so a change, its audit row and the version
bump land together.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.errors import PolicyUnavailableError
from app.access.facts import (
    SUBJECT_GROUP,
    SUBJECT_USER,
    GrantFacts,
    GroupFacts,
    UserFacts,
)
from app.access.models import Grant, Group, GroupMember, PolicyState
from app.identity import User


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; every stored timestamp is UTC (CLAUDE.md)."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


class AccessRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ---- reads for the evaluator ---------------------------------------

    async def policy_version(self) -> int:
        version = (
            await self._db.execute(
                select(col(PolicyState.policy_version)).where(col(PolicyState.id) == 1)
            )
        ).scalar_one_or_none()
        if version is None:
            msg = "policy_state has no row"
            raise PolicyUnavailableError(msg)
        return version

    async def user_facts(self, user_id: UUID) -> UserFacts | None:
        user = await self._db.get(User, user_id, populate_existing=True)
        if user is None:
            return None
        return UserFacts(user.id, user.role, user.status, user.tenant)

    async def tenant_groups(self, tenant: str) -> dict[UUID, GroupFacts]:
        rows = (
            (await self._db.execute(select(Group).where(col(Group.tenant) == tenant)))
            .scalars()
            .all()
        )
        return {g.id: GroupFacts(g.id, g.name, g.parent_id, g.tenant) for g in rows}

    async def memberships(self, user_id: UUID) -> dict[UUID, str]:
        rows = (
            (
                await self._db.execute(
                    select(GroupMember).where(col(GroupMember.user_id) == user_id)
                )
            )
            .scalars()
            .all()
        )
        return {m.group_id: m.standing for m in rows}

    async def grants_for(
        self, user_id: UUID, group_ids: Iterable[UUID]
    ) -> list[GrantFacts]:
        ids = list(group_ids)
        clause: ColumnElement[bool] = and_(
            col(Grant.subject_type) == SUBJECT_USER, col(Grant.subject_id) == user_id
        )
        if ids:
            clause = or_(
                clause,
                and_(
                    col(Grant.subject_type) == SUBJECT_GROUP,
                    col(Grant.subject_id).in_(ids),
                ),
            )
        rows = (await self._db.execute(select(Grant).where(clause))).scalars().all()
        return [
            GrantFacts(
                g.id,
                g.subject_type,
                g.subject_id,
                g.effect,
                g.target_kind,
                g.target,
                _aware(g.expires_at),
            )
            for g in rows
        ]
```

- [ ] **Step 6: Implement the service**

```python
# backend/app/access/service.py
"""Resolves a caller's Policy (spec §5.4, §8). Fails closed (spec §12)."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import PolicyCache, shared_cache
from app.access.errors import PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import PolicyInputs
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.identity import Principal

logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AccessService:
    def __init__(
        self,
        repo: AccessRepository,
        cache: PolicyCache,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._clock = clock

    async def policy_for(self, principal: Principal) -> Policy:
        return await self.policy_for_user(principal.user_id)

    async def policy_for_user(self, user_id: UUID) -> Policy:
        """The user's Policy. Any failure raises PolicyUnavailableError: deny."""
        try:
            return await self._resolve(user_id)
        except PolicyUnavailableError:
            logger.exception("access.policy_unavailable", user_id=str(user_id))
            raise
        except Exception as exc:
            logger.exception("access.policy_failed", user_id=str(user_id))
            msg = "The access check failed"
            raise PolicyUnavailableError(msg) from exc

    async def _resolve(self, user_id: UUID) -> Policy:
        version = await self._repo.policy_version()
        now = self._clock()
        cached = self._cache.get(user_id, version, now)
        if cached is not None:
            return cached
        user = await self._repo.user_facts(user_id)
        if user is None:
            return Policy.deny_all(user_id, "", version)
        groups = await self._repo.tenant_groups(user.tenant)
        inputs = PolicyInputs(
            user=user,
            groups=groups,
            memberships=await self._repo.memberships(user_id),
            grants=await self._repo.grants_for(user_id, groups),
            policy_version=version,
        )
        policy = evaluate(inputs, now)
        self._cache.put(policy)
        return policy


async def policy_for(db: AsyncSession, principal: Principal) -> Policy:
    """Public entry point: the caller's Policy through the process-wide cache."""
    return await AccessService(AccessRepository(db), shared_cache()).policy_for(
        principal
    )
```

- [ ] **Step 7: Clear the shared cache between tests**

In `backend/tests/conftest.py`, add `from app.access.cache import shared_cache` with the imports and
make `shared_cache().clear()` the first line of the `db` fixture body (before `reset_plugins()`).

- [ ] **Step 8: Run to verify they pass**

Run: `uv run pytest tests/access -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/access backend/tests/access backend/tests/access_helpers.py \
  backend/tests/conftest.py
git commit -m "feat(access): repository, versioned policy cache, fail-closed policy_for"
```

---

### Task 5: Startup: capability sync, version bump, service users

**Files:**
- Create: `backend/app/access/startup.py`
- Modify: `backend/app/access/repository.py`, `backend/app/identity/bootstrap.py`,
  `backend/app/identity/service.py`, `backend/app/identity/__init__.py`, `backend/app/config.py`,
  `backend/app/main.py`
- Test: `backend/tests/access/test_startup.py`, `backend/tests/identity/test_service_users.py`,
  `backend/tests/test_startup.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_startup.py
from sqlalchemy import delete
from sqlmodel import select

from app.access.catalog import CAPABILITIES, CHAT_USE
from app.access.models import Capability, PolicyState
from app.access.startup import prepare_access


async def _version(db) -> int:
    state = await db.get(PolicyState, 1, populate_existing=True)
    assert state is not None
    return state.policy_version


async def test_prepare_access_mirrors_the_catalog_and_bumps(db) -> None:
    db.add(Capability(code="old:thing", description="retired"))
    await db.commit()

    await prepare_access(db)

    rows = {c.code: c for c in (await db.execute(select(Capability))).scalars()}
    assert set(CAPABILITIES) <= set(rows)
    assert rows["old:thing"].deprecated
    assert not rows[CHAT_USE].deprecated
    assert await _version(db) == 2


async def test_prepare_access_recreates_a_missing_policy_row(db) -> None:
    await db.execute(delete(PolicyState))
    await db.commit()

    await prepare_access(db)

    assert await _version(db) == 2
```

```python
# backend/tests/identity/test_service_users.py
from app.identity.bootstrap import ensure_service_user
from app.identity.models import User, UserKind, UserStatus
from app.identity.repository import UserRepository
from app.identity.service import service_principal

EMAIL = "mcp-shared@atlas.internal"


async def test_service_user_is_created_once(db) -> None:
    first = await ensure_service_user(db, EMAIL, "MCP (shared token)", "analyst")
    second = await ensure_service_user(db, EMAIL, "Renamed", "viewer")

    assert first.id == second.id
    assert second.kind == UserKind.SERVICE
    assert second.role == "analyst"  # later calls never change an existing row


async def test_service_principal_only_for_active_service_users(db) -> None:
    user = await ensure_service_user(db, EMAIL, "MCP (shared token)", "analyst")

    principal = await service_principal(db, EMAIL)
    assert principal is not None
    assert principal.user_id == user.id
    assert principal.auth_method == "service"

    assert await service_principal(db, "nobody@atlas.internal") is None
    await UserRepository(db).save(User(email="human@yougotagift.com"))
    assert await service_principal(db, "human@yougotagift.com") is None

    user.status = UserStatus.DISABLED
    await UserRepository(db).save(user)
    assert await service_principal(db, EMAIL) is None
```

Replace `backend/tests/test_startup.py` with:

```python
"""Startup: bootstrap admins, the MCP service user, the capability catalog."""

import pytest
from sqlmodel import select

from app import main
from app.access.models import Capability
from app.identity.repository import UserRepository


async def test_startup_prepares_identity_and_access(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMINS", "boss@yougotagift.com")
    main.get_settings.cache_clear()
    try:
        await main.apply_startup()
    finally:
        main.get_settings.cache_clear()

    users = UserRepository(db)
    boss = await users.get_by_email("boss@yougotagift.com")
    assert boss is not None
    assert boss.role == "admin"
    mcp = await users.get_by_email("mcp-shared@atlas.internal")
    assert mcp is not None
    assert mcp.kind == "service"
    assert mcp.role == "analyst"
    assert (await db.execute(select(Capability))).scalars().first() is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_startup.py tests/identity/test_service_users.py tests/test_startup.py -q`
Expected: FAIL (`app.access.startup`, `ensure_service_user`, `apply_startup` do not exist).

- [ ] **Step 3: Repository writes**

Add to `backend/app/access/repository.py`. Imports: add `Mapping` to the `collections.abc` import,
`update` from `sqlalchemy`, `SQLModel` from `sqlmodel`, and `Capability` to the models import. Then
append to `AccessRepository`:

```python
    # ---- staged writes (the service commits) ----------------------------

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def delete(self, row: SQLModel) -> None:
        await self._db.delete(row)

    async def bump_version(self) -> None:
        await self._db.execute(
            update(PolicyState)
            .where(col(PolicyState.id) == 1)
            .values(
                policy_version=col(PolicyState.policy_version) + 1,
                updated_at=datetime.now(UTC),
            )
        )

    async def commit(self) -> None:
        await self._db.commit()

    async def ensure_policy_state(self) -> None:
        if await self._db.get(PolicyState, 1, populate_existing=True) is None:
            self._db.add(PolicyState(id=1, policy_version=1))
            await self._db.flush()

    async def sync_capabilities(self, catalog: Mapping[str, str]) -> None:
        existing = {
            c.code: c for c in (await self._db.execute(select(Capability))).scalars()
        }
        for code, description in catalog.items():
            row = existing.get(code) or Capability(code=code, description=description)
            row.description = description
            row.deprecated = False
            self._db.add(row)
        for code, row in existing.items():
            if code not in catalog:
                row.deprecated = True
                self._db.add(row)
```

- [ ] **Step 4: Startup for access**

```python
# backend/app/access/startup.py
"""Startup for access: mirror the capability catalog and invalidate cached policies."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.repository import AccessRepository


async def prepare_access(db: AsyncSession) -> None:
    repo = AccessRepository(db)
    await repo.ensure_policy_state()
    await repo.sync_capabilities(CAPABILITIES)
    # Bootstrap may have changed roles; a bump makes every worker re-evaluate.
    await repo.bump_version()
    await repo.commit()
    shared_cache().clear()
```

- [ ] **Step 5: Service users in identity**

Append to `backend/app/identity/bootstrap.py` (add `UserKind` to the models import):

```python
async def ensure_service_user(
    db: AsyncSession, email: str, display_name: str, role: str
) -> User:
    """Create a service identity once. An existing row is returned unchanged."""
    users = UserRepository(db)
    user = await users.get_by_email(email)
    if user is None:
        user = await users.create_or_get(
            User(
                email=email,
                display_name=display_name,
                kind=UserKind.SERVICE,
                role=role,
            )
        )
        logger.info("identity.service_user_created", user_id=str(user.id))
    return user
```

Append to `backend/app/identity/service.py` (add `from sqlalchemy.ext.asyncio import AsyncSession`
and `UserKind` to the models import):

```python
async def service_principal(db: AsyncSession, email: str) -> Principal | None:
    """The Principal for an active service identity, or None (fail closed)."""
    user = await UserRepository(db).get_by_email(email)
    if user is None or user.kind != UserKind.SERVICE:
        return None
    if user.status != UserStatus.ACTIVE:
        return None
    return to_principal(user, "service")
```

In `backend/app/identity/__init__.py`, change the bootstrap import to
`from app.identity.bootstrap import bootstrap_admins, ensure_service_user`, add
`from app.identity.service import service_principal`, and add `"ensure_service_user"` and
`"service_principal"` to `__all__` (keep it sorted).

- [ ] **Step 6: Settings and startup wiring**

In `backend/app/config.py`, after `atlas_mcp_token: str = ""` add:

```python
    # MCP calls run as this service user until per-user MCP auth (spec phase 4).
    mcp_service_email: str = "mcp-shared@atlas.internal"
```

In `backend/app/main.py`: change the identity import to
`from app.identity import bootstrap_admins, ensure_service_user, identity_router`, add
`from app.access import prepare_access` (Task 6 creates the export; until then import
`from app.access.startup import prepare_access`, then switch in Task 6), and replace
`apply_bootstrap_admins` and its call in `lifespan` with:

```python
MCP_SERVICE_NAME = "MCP (shared token)"
MCP_SERVICE_ROLE = "analyst"


async def apply_startup() -> None:
    settings = get_settings()
    async with get_session_factory()() as db:
        await bootstrap_admins(db, settings.bootstrap_admin_list)
        await ensure_service_user(
            db, settings.mcp_service_email, MCP_SERVICE_NAME, MCP_SERVICE_ROLE
        )
        await prepare_access(db)
```

```python
    await apply_startup()
```

- [ ] **Step 7: Run to verify they pass**

Run: `uv run pytest tests/access tests/identity tests/test_startup.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/access backend/app/identity backend/app/config.py backend/app/main.py \
  backend/tests/access backend/tests/identity backend/tests/test_startup.py
git commit -m "feat(access): startup syncs capabilities and bumps the version; service users"
```

---

### Task 6: Wiring: `get_policy`, `require_capability`, `/me/access`, capability catalog

**Files:**
- Create: `backend/app/access/schemas.py`, `backend/app/access/dependencies.py`,
  `backend/app/access/router.py`
- Modify: `backend/app/access/service.py` (`describe`), `backend/app/access/__init__.py`,
  `backend/app/main.py`
- Test: `backend/tests/access/test_access_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_access_api.py
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.access import require_capability
from app.access.catalog import ADMIN_AUDIT
from app.access.models import PolicyState
from app.main import app as asgi_app
from tests.access_helpers import add_grant, add_member, make_group, make_user


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with _client(asgi_app) as client:
        yield client


async def test_a_new_user_can_chat_but_has_no_data(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/me/access")).json()
    assert body == {
        "role": "viewer",
        "capabilities": ["chat:use"],
        "groups": [],
        "has_data_access": False,
    }


async def test_memberships_and_data_access_show_up(api: AsyncClient, db) -> None:
    dev = await make_user(db, "dev@yougotagift.com")
    group = await make_group(db, "growth")
    await add_member(db, group, dev, "manager")
    await add_grant(db, group, "demo/*")

    body = (await api.get("/api/v1/me/access")).json()

    assert body["groups"] == [
        {"id": str(group.id), "name": "growth", "standing": "manager"}
    ]
    assert body["has_data_access"] is True


async def test_capability_catalog_lists_roles(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/meta/capabilities")).json()
    roles = {r["name"]: set(r["capabilities"]) for r in body["roles"]}
    assert roles["viewer"] == {"chat:use"}
    assert {c["code"] for c in body["capabilities"]} == roles["admin"]


async def test_an_unreadable_policy_is_a_503(api: AsyncClient, db) -> None:
    await db.execute(delete(PolicyState))
    await db.commit()
    assert (await api.get("/api/v1/me/access")).status_code == 503


async def test_require_capability_gates_a_route(db) -> None:
    app = FastAPI()

    @app.get("/audit", dependencies=[Depends(require_capability(ADMIN_AUDIT))])
    async def audit() -> dict[str, str]:
        return {"ok": "yes"}

    async with _client(app) as client:
        denied = await client.get("/audit")
        assert denied.status_code == 403
        assert "admin:audit" in denied.json()["detail"]

        await make_user(db, "dev@yougotagift.com", role="admin")
        assert (await client.get("/audit")).status_code == 200


def test_an_unknown_capability_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="Unknown capability"):
        require_capability("nope:nope")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_access_api.py -q`
Expected: FAIL with `ImportError: cannot import name 'require_capability' from 'app.access'`.

- [ ] **Step 3: Schemas for this task**

```python
# backend/app/access/schemas.py
"""Request and response shapes for the access API (separate from the tables)."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel

from app.access.catalog import CAPABILITIES, ROLES, role_capabilities


class GroupRefOut(BaseModel):
    id: UUID
    name: str
    standing: str


class MeAccessOut(BaseModel):
    role: str
    capabilities: list[str]
    groups: list[GroupRefOut]
    has_data_access: bool


class CapabilityOut(BaseModel):
    code: str
    description: str


class RoleOut(BaseModel):
    name: str
    capabilities: list[str]


class CatalogOut(BaseModel):
    capabilities: list[CapabilityOut]
    roles: list[RoleOut]

    @classmethod
    def build(cls) -> Self:
        return cls(
            capabilities=[
                CapabilityOut(code=code, description=text)
                for code, text in CAPABILITIES.items()
            ],
            roles=[
                RoleOut(name=role, capabilities=sorted(role_capabilities(role)))
                for role in ROLES
            ],
        )
```

(Tasks 7, 8 and 10 append the admin schemas and the imports they need.)

- [ ] **Step 4: `describe` on the service**

Add to `AccessService` in `backend/app/access/service.py` (import `GroupRefOut, MeAccessOut` from
`app.access.schemas`):

```python
    async def describe(self, policy: Policy) -> MeAccessOut:
        """What /me/access shows: role, capabilities, groups, any data at all."""
        memberships = await self._repo.memberships(policy.user_id)
        groups = await self._repo.tenant_groups(policy.tenant)
        refs = [
            GroupRefOut(id=gid, name=groups[gid].name, standing=standing)
            for gid, standing in memberships.items()
            if gid in groups
        ]
        return MeAccessOut(
            role=policy.role,
            capabilities=sorted(policy.capabilities),
            groups=sorted(refs, key=lambda ref: ref.name),
            has_data_access=policy.has_data_access,
        )
```

- [ ] **Step 5: Dependencies**

```python
# backend/app/access/dependencies.py
"""FastAPI wiring for access: the caller's Policy, capability gates, error mapping."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.cache import shared_cache
from app.access.catalog import CAPABILITIES
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.service import AccessService
from app.database import get_db
from app.identity import Principal, get_principal


def get_access_service(db: AsyncSession = Depends(get_db)) -> AccessService:
    return AccessService(AccessRepository(db), shared_cache())


async def get_policy(
    principal: Principal = Depends(get_principal),
    service: AccessService = Depends(get_access_service),
) -> Policy:
    """The caller's Policy. Unavailable means deny: the request fails with 503."""
    try:
        return await service.policy_for(principal)
    except PolicyUnavailableError:
        raise HTTPException(
            503, "The access check is unavailable right now. Try again shortly."
        ) from None


def require_capability(code: str) -> Callable[..., Awaitable[Policy]]:
    """A dependency that admits only callers whose Policy has `code` (spec §3.2)."""
    if code not in CAPABILITIES:
        msg = f"Unknown capability {code!r}"
        raise ValueError(msg)

    async def check(policy: Policy = Depends(get_policy)) -> Policy:
        if not policy.has(code):
            raise HTTPException(
                403, f"Your role doesn't include this ({code}). Ask an atlas admin."
            )
        return policy

    return check


async def access_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Maps AccessError subclasses to their HTTP status with a plain message."""
    status = exc.status_code if isinstance(exc, AccessError) else 500
    return JSONResponse({"detail": str(exc)}, status_code=status)
```

- [ ] **Step 6: Router (self-service part)**

```python
# backend/app/access/router.py
"""Access routes. Thin: resolve the caller, call a service, return a schema."""

from fastapi import APIRouter, Depends

from app.access.dependencies import get_access_service, get_policy
from app.access.policy import Policy
from app.access.schemas import CatalogOut, MeAccessOut
from app.access.service import AccessService
from app.identity import Principal, get_principal

router = APIRouter(prefix="/api/v1", tags=["access"])


@router.get("/me/access", response_model=MeAccessOut)
async def my_access(
    policy: Policy = Depends(get_policy),
    service: AccessService = Depends(get_access_service),
) -> MeAccessOut:
    return await service.describe(policy)


@router.get("/meta/capabilities", response_model=CatalogOut)
async def capability_catalog(
    _principal: Principal = Depends(get_principal),
) -> CatalogOut:
    return CatalogOut.build()
```

- [ ] **Step 7: Public interface and app wiring**

```python
# backend/app/access/__init__.py
"""Access: what a caller may do and see (spec §5). Other modules import only from here."""

from app.access.catalog import (
    ADMIN_AUDIT,
    ADMIN_GROUPS,
    ADMIN_USERS,
    CHAT_USE,
    MCP_USE,
)
from app.access.dependencies import access_error_handler, get_policy, require_capability
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, PolicyInputs, UserFacts
from app.access.policy import Policy
from app.access.router import router as access_router
from app.access.service import policy_for
from app.access.startup import prepare_access

__all__ = [
    "ADMIN_AUDIT",
    "ADMIN_GROUPS",
    "ADMIN_USERS",
    "CHAT_USE",
    "MCP_USE",
    "AccessError",
    "GrantFacts",
    "Policy",
    "PolicyInputs",
    "PolicyUnavailableError",
    "UserFacts",
    "access_error_handler",
    "access_router",
    "evaluate",
    "get_policy",
    "policy_for",
    "prepare_access",
    "require_capability",
]
```

In `backend/app/main.py`: import `from app.access import AccessError, access_error_handler,
access_router, prepare_access` (replacing the Task 5 `app.access.startup` import), add
`app.include_router(access_router)` after `app.include_router(identity_router)`, and add
`app.add_exception_handler(AccessError, access_error_handler)` directly after the CORS middleware.

- [ ] **Step 8: Run to verify they pass**

Run: `uv run pytest tests/access -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/access backend/app/main.py backend/tests/access
git commit -m "feat(access): get_policy, require_capability, /me/access and the capability catalog"
```

---

### Task 7: Admin service: groups and members

**Files:**
- Create: `backend/app/access/admin.py`
- Modify: `backend/app/access/repository.py`, `backend/app/access/schemas.py`,
  `backend/tests/access_helpers.py`
- Test: `backend/tests/access/test_admin_groups.py`

- [ ] **Step 1: Shared admin test helpers**

Append to `backend/tests/access_helpers.py` (add the imports at the top:
`from uuid import uuid4`, `from app.access.admin import AccessAdmin, Actor`,
`from app.access.cache import PolicyCache`, `from app.access.repository import AccessRepository`,
`from app.access.service import AccessService`, `from app.identity import TokenVerifier`):

```python
def admin_for(db: AsyncSession, verifier: TokenVerifier | None = None) -> AccessAdmin:
    repo = AccessRepository(db)
    return AccessAdmin(repo, AccessService(repo, PolicyCache()), verifier)


async def actor_with(
    db: AsyncSession,
    role: str = "admin",
    *,
    member_of: Group | None = None,
    standing: str = "member",
) -> Actor:
    """An API actor backed by a real user and an evaluated policy."""
    user = await make_user(db, f"{role}-{uuid4().hex[:8]}@yougotagift.com", role=role)
    if member_of is not None:
        await add_member(db, member_of, user, standing)
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        user.id
    )
    return Actor.from_policy(policy)


async def policy_version(db: AsyncSession) -> int:
    state = await db.get(PolicyState, 1, populate_existing=True)
    assert state is not None
    return state.policy_version
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/access/test_admin_groups.py
from uuid import uuid4

import pytest
from sqlmodel import col, select

from app.access.admin import Actor
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.models import RbacChange
from app.access.schemas import GroupCreate, GroupUpdate
from tests.access_helpers import (
    actor_with,
    add_grant,
    admin_for,
    make_group,
    make_user,
    policy_version,
)


async def _changes(db) -> list[RbacChange]:
    stmt = select(RbacChange).order_by(col(RbacChange.at))
    return list((await db.execute(stmt)).scalars().all())


async def test_create_group_is_audited_and_bumps_the_version(db) -> None:
    actor = await actor_with(db)
    before = await policy_version(db)

    group = await admin_for(db).create_group(
        actor, GroupCreate(name="growth", description="Growth team")
    )

    assert group.tenant == "ygg"
    assert await policy_version(db) == before + 1
    change = (await _changes(db))[-1]
    assert (change.action, change.object_id, change.via) == (
        "group.create",
        str(group.id),
        "api",
    )
    assert change.actor_user_id == actor.user_id
    assert change.before is None
    assert change.after is not None
    assert change.after["name"] == "growth"


async def test_group_names_are_unique(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_group(actor, GroupCreate(name="growth"))
    with pytest.raises(ConflictError):
        await admin.create_group(actor, GroupCreate(name="growth"))


async def test_only_admin_groups_creates_groups(db) -> None:
    builder = await actor_with(db, "builder")
    with pytest.raises(AccessDeniedError, match="admin:groups"):
        await admin_for(db).create_group(builder, GroupCreate(name="x"))


async def test_an_unknown_parent_is_not_found(db) -> None:
    with pytest.raises(NotFoundError):
        await admin_for(db).create_group(
            await actor_with(db), GroupCreate(name="x", parent_id=uuid4())
        )


async def test_a_group_cannot_move_under_itself_or_a_subgroup(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    parent = await admin.create_group(actor, GroupCreate(name="marketing"))
    child = await admin.create_group(
        actor, GroupCreate(name="growth", parent_id=parent.id)
    )

    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent.id, GroupUpdate(parent_id=child.id))
    with pytest.raises(InvalidChangeError):
        await admin.update_group(actor, parent.id, GroupUpdate(parent_id=parent.id))

    moved = await admin.update_group(actor, child.id, GroupUpdate(parent_id=None))
    assert moved.parent_id is None
    renamed = await admin.update_group(actor, child.id, GroupUpdate(name="growth-mena"))
    assert renamed.name == "growth-mena"


async def test_only_empty_groups_can_be_deleted(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    used = await admin.create_group(actor, GroupCreate(name="used"))
    await add_grant(db, used, "demo/*")
    with pytest.raises(ConflictError):
        await admin.delete_group(actor, used.id)

    empty = await admin.create_group(actor, GroupCreate(name="empty"))
    await admin.delete_group(actor, empty.id)
    assert "empty" not in {g.name for g in await admin.list_groups(actor)}
    assert (await _changes(db))[-1].action == "group.delete"


async def test_admins_add_members_and_managers(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")

    added = await admin.put_member(actor, group.id, sara.id, "manager")

    assert (added.email, added.standing) == ("sara@yougotagift.com", "manager")
    listed = await admin.list_members(actor, group.id)
    assert [(m.email, m.standing) for m in listed] == [
        ("sara@yougotagift.com", "manager")
    ]


async def test_managers_manage_members_of_their_subtree(db) -> None:
    parent = await make_group(db, "marketing")
    child = await make_group(db, "growth", parent=parent)
    manager = await actor_with(db, "viewer", member_of=parent, standing="manager")
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    await admin.put_member(manager, child.id, sara.id, "member")
    with pytest.raises(AccessDeniedError):  # decision D8: only admins appoint managers
        await admin.put_member(manager, child.id, sara.id, "manager")
    await admin.remove_member(manager, child.id, sara.id)


async def test_plain_members_cannot_change_membership(db) -> None:
    group = await make_group(db, "growth")
    member = await actor_with(db, "viewer", member_of=group)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).put_member(member, group.id, sara.id, "member")


async def test_removing_a_non_member_is_not_found(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    with pytest.raises(NotFoundError):
        await admin_for(db).remove_member(actor, group.id, uuid4())


async def test_the_cli_actor_is_trusted_and_recorded(db) -> None:
    await admin_for(db).create_group(Actor.cli(), GroupCreate(name="from-cli"))
    change = (await _changes(db))[-1]
    assert (change.via, change.actor_user_id) == ("cli", None)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/access/test_admin_groups.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.access.admin'`.

- [ ] **Step 4: Schemas for groups and members**

Append to `backend/app/access/schemas.py` (add `from datetime import datetime`, `Literal` to the
`typing` import and `Field` to the pydantic import):

```python
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = None


class GroupUpdate(BaseModel):
    """Only the fields sent are changed; send `parent_id: null` to make a root group."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_id: UUID | None = None


class MemberPut(BaseModel):
    standing: Literal["member", "manager"] = "member"


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    standing: str
    added_at: datetime
```

- [ ] **Step 5: Repository reads for administration**

Append to `AccessRepository` (add `func` to the `sqlalchemy` import):

```python
    # ---- reads for administration ---------------------------------------

    async def group(self, group_id: UUID) -> Group | None:
        return await self._db.get(Group, group_id)

    async def group_by_name(self, tenant: str, name: str) -> Group | None:
        stmt = select(Group).where(col(Group.tenant) == tenant, col(Group.name) == name)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_groups(self, tenant: str) -> list[Group]:
        stmt = select(Group).where(col(Group.tenant) == tenant).order_by(col(Group.name))
        return list((await self._db.execute(stmt)).scalars().all())

    async def group_in_use(self, group_id: UUID) -> bool:
        """True when the group has subgroups, members or grants."""
        checks = (
            select(func.count()).select_from(Group).where(col(Group.parent_id) == group_id),
            select(func.count())
            .select_from(GroupMember)
            .where(col(GroupMember.group_id) == group_id),
            select(func.count())
            .select_from(Grant)
            .where(
                col(Grant.subject_type) == SUBJECT_GROUP,
                col(Grant.subject_id) == group_id,
            ),
        )
        for stmt in checks:
            if (await self._db.execute(stmt)).scalar_one():
                return True
        return False

    async def member(self, group_id: UUID, user_id: UUID) -> GroupMember | None:
        return await self._db.get(GroupMember, (group_id, user_id))

    async def list_members(self, group_id: UUID) -> list[tuple[GroupMember, User]]:
        stmt = (
            select(GroupMember, User)
            .join(User, col(User.id) == col(GroupMember.user_id))
            .where(col(GroupMember.group_id) == group_id)
            .order_by(col(User.email))
        )
        return [(member, user) for member, user in (await self._db.execute(stmt)).all()]

    async def user(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id)
```

- [ ] **Step 6: Implement the admin service (groups and members)**

```python
# backend/app/access/admin.py
"""Administration of access (spec §5, §10): groups, members, grants, roles, status.

Each write is one unit of work: the change, its rbac_changes row and the
policy_version bump commit together, so no cached policy can miss a change.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID

import structlog
from sqlmodel import SQLModel

from app.access.catalog import ADMIN_GROUPS
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.facts import DEFAULT_TENANT, STANDING_MANAGER
from app.access.models import Group, GroupMember, RbacChange
from app.access.policy import Policy
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, GroupUpdate, MemberOut
from app.access.service import AccessService
from app.identity import TokenVerifier, User

logger = structlog.get_logger()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _snapshot(row: SQLModel | None) -> dict[str, Any] | None:
    return None if row is None else row.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class Actor:
    """Who changes access. `policy` is None only for the trusted CLI (decision D5)."""

    user_id: UUID | None
    via: str  # 'api' | 'cli'
    tenant: str
    policy: Policy | None

    @classmethod
    def from_policy(cls, policy: Policy) -> Self:
        return cls(policy.user_id, "api", policy.tenant, policy)

    @classmethod
    def cli(cls, tenant: str = DEFAULT_TENANT) -> Self:
        return cls(None, "cli", tenant, None)

    def require(self, capability: str) -> None:
        if self.policy is not None and not self.policy.has(capability):
            msg = f"This needs {capability}. Ask an atlas admin."
            raise AccessDeniedError(msg)

    def require_member_admin(self, group_id: UUID) -> None:
        if self.policy is not None and not self.policy.can_manage_members(group_id):
            msg = "Only atlas admins and the group's managers can change its members."
            raise AccessDeniedError(msg)


def _change(
    actor: Actor,
    action: str,
    target: tuple[str, UUID | str],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> RbacChange:
    object_type, object_id = target
    return RbacChange(
        actor_user_id=actor.user_id,
        via=actor.via,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        before=before,
        after=after,
    )


def _member_out(member: GroupMember, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        standing=member.standing,
        added_at=member.added_at,
    )


class AccessAdmin:
    def __init__(
        self,
        repo: AccessRepository,
        access: AccessService,
        verifier: TokenVerifier | None = None,
    ) -> None:
        self._repo = repo
        self._access = access
        self._verifier = verifier

    # ---- groups -------------------------------------------------------------

    async def list_groups(self, actor: Actor) -> list[Group]:
        actor.require(ADMIN_GROUPS)
        return await self._repo.list_groups(actor.tenant)

    async def create_group(self, actor: Actor, payload: GroupCreate) -> Group:
        actor.require(ADMIN_GROUPS)
        await self._ensure_name_free(actor, payload.name)
        if payload.parent_id is not None:
            await self._group(actor, payload.parent_id)
        group = Group(
            name=payload.name,
            description=payload.description,
            parent_id=payload.parent_id,
            tenant=actor.tenant,
            created_by=actor.user_id,
        )
        self._repo.add(group)
        await self._commit(
            _change(actor, "group.create", ("group", group.id), None, _snapshot(group))
        )
        return group

    async def update_group(
        self, actor: Actor, group_id: UUID, payload: GroupUpdate
    ) -> Group:
        actor.require(ADMIN_GROUPS)
        group = await self._group(actor, group_id)
        before = _snapshot(group)
        if payload.name is not None and payload.name != group.name:
            await self._ensure_name_free(actor, payload.name)
            group.name = payload.name
        if payload.description is not None:
            group.description = payload.description
        if "parent_id" in payload.model_fields_set:
            await self._check_parent(actor, group.id, payload.parent_id)
            group.parent_id = payload.parent_id
        self._repo.add(group)
        await self._commit(
            _change(actor, "group.update", ("group", group.id), before, _snapshot(group))
        )
        return group

    async def delete_group(self, actor: Actor, group_id: UUID) -> None:
        actor.require(ADMIN_GROUPS)
        group = await self._group(actor, group_id)
        if await self._repo.group_in_use(group.id):
            msg = "Remove the group's subgroups, members and grants first."
            raise ConflictError(msg)
        before = _snapshot(group)
        await self._repo.delete(group)
        await self._commit(_change(actor, "group.delete", ("group", group.id), before, None))

    # ---- members ------------------------------------------------------------

    async def list_members(self, actor: Actor, group_id: UUID) -> list[MemberOut]:
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        return [_member_out(m, u) for m, u in await self._repo.list_members(group.id)]

    async def put_member(
        self, actor: Actor, group_id: UUID, user_id: UUID, standing: str
    ) -> MemberOut:
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        if standing == STANDING_MANAGER:
            actor.require(ADMIN_GROUPS)  # decision D8
        user = await self._user(actor, user_id)
        member = await self._repo.member(group.id, user.id)
        before = _snapshot(member)
        if member is None:
            member = GroupMember(
                group_id=group.id,
                user_id=user.id,
                standing=standing,
                added_by=actor.user_id,
            )
        else:
            member.standing = standing
        self._repo.add(member)
        target = ("group_member", f"{group.id}:{user.id}")
        await self._commit(_change(actor, "member.put", target, before, _snapshot(member)))
        return _member_out(member, user)

    async def remove_member(self, actor: Actor, group_id: UUID, user_id: UUID) -> None:
        group = await self._group(actor, group_id)
        actor.require_member_admin(group.id)
        member = await self._repo.member(group.id, user_id)
        if member is None:
            msg = "That user isn't in this group."
            raise NotFoundError(msg)
        if member.standing == STANDING_MANAGER:
            actor.require(ADMIN_GROUPS)
        before = _snapshot(member)
        await self._repo.delete(member)
        target = ("group_member", f"{group.id}:{user_id}")
        await self._commit(_change(actor, "member.remove", target, before, None))

    # ---- helpers ------------------------------------------------------------

    async def _commit(self, change: RbacChange) -> None:
        self._repo.add(change)
        await self._repo.bump_version()
        await self._repo.commit()
        logger.info(
            "access.changed",
            action=change.action,
            object_id=change.object_id,
            via=change.via,
        )

    async def _group(self, actor: Actor, group_id: UUID) -> Group:
        group = await self._repo.group(group_id)
        if group is None or group.tenant != actor.tenant:
            msg = "No such group."
            raise NotFoundError(msg)
        return group

    async def _user(self, actor: Actor, user_id: UUID) -> User:
        user = await self._repo.user(user_id)
        if user is None or user.tenant != actor.tenant:
            msg = "No such user."
            raise NotFoundError(msg)
        return user

    async def _ensure_name_free(self, actor: Actor, name: str) -> None:
        if await self._repo.group_by_name(actor.tenant, name) is not None:
            msg = f"A group named '{name}' already exists."
            raise ConflictError(msg)

    async def _check_parent(
        self, actor: Actor, group_id: UUID, parent_id: UUID | None
    ) -> None:
        """Reject a parent that is the group itself or one of its subgroups."""
        if parent_id is None:
            return
        groups = await self._repo.tenant_groups(actor.tenant)
        if parent_id not in groups:
            msg = "No such parent group."
            raise NotFoundError(msg)
        current: UUID | None = parent_id
        seen: set[UUID] = set()
        while current is not None and current in groups and current not in seen:
            if current == group_id:
                msg = "A group can't sit under itself or one of its subgroups."
                raise InvalidChangeError(msg)
            seen.add(current)
            current = groups[current].parent_id
```

- [ ] **Step 7: Run to verify they pass**

Run: `uv run ruff format app/access tests && uv run pytest tests/access -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/access backend/tests/access backend/tests/access_helpers.py
git commit -m "feat(access): admin service for groups and members (audited, versioned)"
```

---

### Task 8: Admin service: grants

**Files:**
- Modify: `backend/app/access/admin.py`, `backend/app/access/repository.py`,
  `backend/app/access/schemas.py`
- Test: `backend/tests/access/test_admin_grants.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_admin_grants.py
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.access.cache import PolicyCache
from app.access.errors import (
    AccessDeniedError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate
from app.access.service import AccessService
from tests.access_helpers import actor_with, add_member, admin_for, make_group, make_user

REVENUE = "demo/order/revenue"
FUTURE = datetime.now(UTC) + timedelta(days=30)


def group_grant(group_id: Any, **changes: Any) -> GrantCreate:
    return GrantCreate.model_validate(
        {"subject_type": "group", "subject_id": group_id, "target": "demo/*", **changes}
    )


async def test_a_group_grant_reaches_members_on_their_next_request(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    sara = await make_user(db, "sara@yougotagift.com")
    await add_member(db, group, sara)
    service = AccessService(AccessRepository(db), PolicyCache())
    assert not (await service.policy_for_user(sara.id)).allows(REVENUE)

    await admin_for(db).create_grant(actor, group_grant(group.id))

    assert (await service.policy_for_user(sara.id)).allows(REVENUE)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"target": "demo order"}, "not a resource pattern"),
        ({"target_kind": "clearance", "target": "fields:people_names"}, "clearances"),
        ({"target_kind": "capability", "target": "mcp:use"}, "Groups grant data"),
        ({"expires_at": datetime(2020, 1, 1, tzinfo=UTC)}, "future"),
    ],
)
async def test_invalid_group_grants_are_rejected(
    db, changes: dict[str, Any], message: str
) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    with pytest.raises(InvalidChangeError, match=message):
        await admin_for(db).create_grant(actor, group_grant(group.id, **changes))


async def test_user_grants_need_a_reason_and_a_known_capability(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    def user_grant(**fields: Any) -> GrantCreate:
        return GrantCreate.model_validate(
            {"subject_type": "user", "subject_id": sara.id, **fields}
        )

    with pytest.raises(InvalidChangeError, match="reason"):
        await admin.create_grant(actor, user_grant(target="demo/*"))
    with pytest.raises(InvalidChangeError, match="Unknown capability"):
        await admin.create_grant(
            actor,
            user_grant(target_kind="capability", target="root:all", reason="x"),
        )
    grant = await admin.create_grant(
        actor,
        user_grant(
            target_kind="capability",
            target="mcp:use",
            reason="MCP pilot",
            expires_at=FUTURE,
        ),
    )
    assert grant.reason == "MCP pilot"


async def test_duplicate_grants_conflict(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    admin = admin_for(db)
    await admin.create_grant(actor, group_grant(group.id))
    with pytest.raises(ConflictError):
        await admin.create_grant(actor, group_grant(group.id))


async def test_an_unknown_subject_is_not_found(db) -> None:
    with pytest.raises(NotFoundError):
        await admin_for(db).create_grant(await actor_with(db), group_grant(uuid4()))


async def test_group_grants_need_admin_groups(db) -> None:
    group = await make_group(db, "growth")
    with pytest.raises(AccessDeniedError):
        await admin_for(db).create_grant(
            await actor_with(db, "builder"), group_grant(group.id)
        )


async def test_revoking_records_the_old_grant(db) -> None:
    actor = await actor_with(db)
    group = await make_group(db, "growth")
    admin = admin_for(db)
    grant = await admin.create_grant(actor, group_grant(group.id))

    await admin.revoke_grant(actor, grant.id)

    assert await admin.list_grants(actor, "group", group.id) == []
    changes = await admin.list_changes(actor)
    assert changes[0].action == "grant.revoke"
    assert changes[0].before is not None
    assert changes[0].before["target"] == "demo/*"
```

(`list_changes` arrives in Task 9. Until then, run this file with
`-k "not revoking"` in Step 4, then run it whole at the end of Task 9.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_admin_grants.py -q`
Expected: FAIL with `ImportError: cannot import name 'GrantCreate'`.

- [ ] **Step 3: Implement**

Append to `backend/app/access/schemas.py` (add `AwareDatetime` to the pydantic import):

```python
class GrantCreate(BaseModel):
    subject_type: Literal["group", "user"]
    subject_id: UUID
    effect: Literal["allow", "deny"] = "allow"
    target_kind: Literal["resource", "capability", "clearance"] = "resource"
    target: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=500)
    expires_at: AwareDatetime | None = None
```

Append to `AccessRepository`:

```python
    async def grant(self, grant_id: UUID) -> Grant | None:
        return await self._db.get(Grant, grant_id)

    async def list_grants(self, subject_type: str, subject_id: UUID) -> list[Grant]:
        stmt = (
            select(Grant)
            .where(
                col(Grant.subject_type) == subject_type,
                col(Grant.subject_id) == subject_id,
            )
            .order_by(col(Grant.created_at))
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def find_grant(
        self, subject: tuple[str, UUID], effect: str, target_kind: str, target: str
    ) -> Grant | None:
        subject_type, subject_id = subject
        stmt = select(Grant).where(
            col(Grant.subject_type) == subject_type,
            col(Grant.subject_id) == subject_id,
            col(Grant.effect) == effect,
            col(Grant.target_kind) == target_kind,
            col(Grant.target) == target,
        )
        return (await self._db.execute(stmt)).scalars().first()
```

In `backend/app/access/admin.py`, extend the imports:

```python
from app.access.catalog import ADMIN_GROUPS, ADMIN_USERS, CAPABILITIES
from app.access.facts import (
    DEFAULT_TENANT,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    STANDING_MANAGER,
    SUBJECT_GROUP,
    SUBJECT_USER,
)
from app.access.models import Grant, Group, GroupMember, RbacChange
from app.access.patterns import InvalidPatternError, validate_pattern
from app.access.schemas import GrantCreate, GroupCreate, GroupUpdate, MemberOut
```

add these module functions above `class AccessAdmin`:

```python
def _grant_capability(subject_type: str) -> str:
    """Group grants are group administration; direct user grants are user admin."""
    return ADMIN_GROUPS if subject_type == SUBJECT_GROUP else ADMIN_USERS


def _validated_target(payload: GrantCreate, now: datetime) -> str:
    if payload.expires_at is not None and payload.expires_at <= now:
        msg = "The expiry must be in the future."
        raise InvalidChangeError(msg)
    if payload.subject_type == SUBJECT_USER and not payload.reason.strip():
        msg = "Direct user grants need a reason."
        raise InvalidChangeError(msg)
    if payload.target_kind == KIND_CLEARANCE:
        msg = (
            "Field clearances arrive with row and field controls; "
            "they can't be granted yet."
        )
        raise InvalidChangeError(msg)
    if payload.target_kind == KIND_CAPABILITY:
        return _capability_target(payload)
    try:
        return validate_pattern(payload.target)
    except InvalidPatternError as exc:
        raise InvalidChangeError(str(exc)) from None


def _capability_target(payload: GrantCreate) -> str:
    if payload.subject_type != SUBJECT_USER:
        msg = (
            "Groups grant data, not actions. Change the user's role, or give the "
            "capability to a user directly."
        )
        raise InvalidChangeError(msg)
    if payload.target not in CAPABILITIES:
        msg = f"Unknown capability '{payload.target}'."
        raise InvalidChangeError(msg)
    return payload.target
```

and add a grants section to `AccessAdmin`, before the helpers:

```python
    # ---- grants -------------------------------------------------------------

    async def list_grants(
        self, actor: Actor, subject_type: str, subject_id: UUID
    ) -> list[Grant]:
        actor.require(_grant_capability(subject_type))
        await self._subject(actor, subject_type, subject_id)
        return await self._repo.list_grants(subject_type, subject_id)

    async def create_grant(self, actor: Actor, payload: GrantCreate) -> Grant:
        actor.require(_grant_capability(payload.subject_type))
        target = _validated_target(payload, _utcnow())
        await self._subject(actor, payload.subject_type, payload.subject_id)
        subject = (payload.subject_type, payload.subject_id)
        if await self._repo.find_grant(subject, payload.effect, payload.target_kind, target):
            msg = "That grant already exists."
            raise ConflictError(msg)
        grant = Grant(
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            effect=payload.effect,
            target_kind=payload.target_kind,
            target=target,
            reason=payload.reason.strip(),
            expires_at=payload.expires_at,
            created_by=actor.user_id,
        )
        self._repo.add(grant)
        await self._commit(
            _change(actor, "grant.create", ("grant", grant.id), None, _snapshot(grant))
        )
        return grant

    async def revoke_grant(self, actor: Actor, grant_id: UUID) -> None:
        grant = await self._repo.grant(grant_id)
        if grant is None:
            msg = "No such grant."
            raise NotFoundError(msg)
        actor.require(_grant_capability(grant.subject_type))
        await self._subject(actor, grant.subject_type, grant.subject_id)
        before = _snapshot(grant)
        await self._repo.delete(grant)
        await self._commit(_change(actor, "grant.revoke", ("grant", grant.id), before, None))
```

and add to the helpers:

```python
    async def _subject(self, actor: Actor, subject_type: str, subject_id: UUID) -> None:
        """The grant subject must exist in the actor's tenant."""
        if subject_type == SUBJECT_GROUP:
            await self._group(actor, subject_id)
        else:
            await self._user(actor, subject_id)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run ruff format app/access tests && uv run pytest tests/access -q -k "not revoking"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/access backend/tests/access
git commit -m "feat(access): grants with validation (patterns, capabilities, reasons, expiry)"
```

---

### Task 9: Admin service: roles, status, preview, change log

**Files:**
- Modify: `backend/app/access/admin.py`, `backend/app/access/repository.py`,
  `backend/app/access/schemas.py`, `backend/app/identity/service.py`
- Replace: `backend/tests/identity/test_service_admin.py`
- Test: `backend/tests/access/test_admin_users.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_admin_users.py
import pytest

from app.access.cache import PolicyCache
from app.access.errors import AccessDeniedError, ConflictError, InvalidChangeError
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate, UserUpdate
from app.access.service import AccessService
from app.identity.tokens import VerifiedToken
from tests.access_helpers import actor_with, add_grant, admin_for, make_user

REVENUE = "demo/order/revenue"


class RecordingVerifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.revoked: list[str] = []
        self.fail = fail

    async def verify(self, token: str) -> VerifiedToken:
        raise AssertionError("not used")

    async def revoke(self, firebase_uid: str) -> None:
        if self.fail:
            raise RuntimeError("no service-account credentials")
        self.revoked.append(firebase_uid)


async def test_a_role_change_is_audited_and_takes_effect(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    admin = admin_for(db)

    await admin.update_user(actor, sara.id, UserUpdate(role="analyst"))

    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        sara.id
    )
    assert policy.has("mcp:use")
    change = (await admin.list_changes(actor))[0]
    assert (change.action, change.before, change.after) == (
        "user.role",
        {"role": "viewer"},
        {"role": "analyst"},
    )


async def test_unknown_roles_and_empty_updates_are_rejected(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    with pytest.raises(InvalidChangeError, match="Unknown role"):
        await admin_for(db).update_user(actor, sara.id, UserUpdate(role="owner"))
    with pytest.raises(InvalidChangeError, match="Nothing to change"):
        await admin_for(db).update_user(actor, sara.id, UserUpdate())


async def test_nobody_changes_their_own_role_or_status(db) -> None:
    actor = await actor_with(db)
    assert actor.user_id is not None
    for update in (UserUpdate(role="viewer"), UserUpdate(status="disabled")):
        with pytest.raises(ConflictError):
            await admin_for(db).update_user(actor, actor.user_id, update)


async def test_disabling_ends_firebase_sessions(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    verifier = RecordingVerifier()

    user = await admin_for(db, verifier).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )

    assert user.status == "disabled"
    assert verifier.revoked == ["fb-sara"]
    policy = await AccessService(AccessRepository(db), PolicyCache()).policy_for_user(
        sara.id
    )
    assert not policy.active


async def test_a_failed_revocation_still_disables(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com", firebase_uid="fb-sara")
    user = await admin_for(db, RecordingVerifier(fail=True)).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )
    assert user.status == "disabled"


async def test_user_search_is_case_insensitive(db) -> None:
    actor = await actor_with(db)
    await make_user(db, "sara.ali@yougotagift.com")
    users = await admin_for(db).list_users(actor, "SARA")
    assert [u.email for u in users] == ["sara.ali@yougotagift.com"]


async def test_effective_access_names_the_deciding_grant(db) -> None:
    actor = await actor_with(db)
    sara = await make_user(db, "sara@yougotagift.com")
    grant = await add_grant(db, sara, "demo/*")

    policy = await admin_for(db).effective_access(actor, sara.id)

    rule = policy.decide(REVENUE).rule
    assert rule is not None
    assert rule.grant_id == grant.id


async def test_the_change_log_needs_admin_audit_and_is_newest_first(db) -> None:
    with pytest.raises(AccessDeniedError):
        await admin_for(db).list_changes(await actor_with(db, "builder"))
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_group(actor, GroupCreate(name="first"))
    await admin.create_group(actor, GroupCreate(name="second"))

    changes = await admin.list_changes(actor)

    assert len(changes) == 2
    assert changes[0].at >= changes[1].at
```

Also add a `firebase_uid: str | None = None` keyword to `make_user` in
`backend/tests/access_helpers.py` and pass it to `User(...)`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_admin_users.py -q`
Expected: FAIL with `ImportError: cannot import name 'UserUpdate'`.

- [ ] **Step 3: Schemas, repository, service**

Append to `backend/app/access/schemas.py`:

```python
class UserUpdate(BaseModel):
    role: str | None = None
    status: Literal["active", "disabled"] | None = None
```

Append to `AccessRepository` (import `RbacChange` from the models):

```python
    async def user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(col(User.email) == email.strip().lower())
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_users(self, tenant: str, query: str, limit: int) -> list[User]:
        stmt = select(User).where(col(User.tenant) == tenant)
        if query:
            stmt = stmt.where(
                or_(
                    col(User.email).icontains(query, autoescape=True),
                    col(User.display_name).icontains(query, autoescape=True),
                )
            )
        stmt = stmt.order_by(col(User.email)).limit(limit)
        return list((await self._db.execute(stmt)).scalars().all())

    async def list_changes(self, limit: int) -> list[RbacChange]:
        stmt = select(RbacChange).order_by(col(RbacChange.at).desc()).limit(limit)
        return list((await self._db.execute(stmt)).scalars().all())
```

In `backend/app/access/admin.py`: import `ADMIN_AUDIT`, `ADMIN_USERS` and `ROLES` from the catalog,
`UserUpdate` from the schemas, and `UserStatus` from `app.identity`; add this module function:

```python
def _not_self(actor: Actor, user: User) -> None:
    if actor.user_id is not None and actor.user_id == user.id:
        msg = "You can't change your own role or status. Ask another admin."
        raise ConflictError(msg)
```

and add these sections to `AccessAdmin`, before the helpers:

```python
    # ---- users --------------------------------------------------------------

    async def list_users(self, actor: Actor, query: str = "", limit: int = 50) -> list[User]:
        actor.require(ADMIN_USERS)
        return await self._repo.list_users(actor.tenant, query.strip(), limit)

    async def update_user(self, actor: Actor, user_id: UUID, payload: UserUpdate) -> User:
        actor.require(ADMIN_USERS)  # before any lookup: no probing for user ids
        if payload.role is None and payload.status is None:
            msg = "Nothing to change: send a role or a status."
            raise InvalidChangeError(msg)
        user = await self._user(actor, user_id)
        if payload.role is not None:
            user = await self._set_role(actor, user, payload.role)
        if payload.status is not None:
            user = await self._set_status(actor, user, payload.status)
        return user

    async def effective_access(self, actor: Actor, user_id: UUID) -> Policy:
        """The user's evaluated Policy, for the preview (spec §10)."""
        actor.require(ADMIN_USERS)
        user = await self._user(actor, user_id)
        return await self._access.policy_for_user(user.id)

    async def list_changes(self, actor: Actor, limit: int = 100) -> list[RbacChange]:
        actor.require(ADMIN_AUDIT)
        return await self._repo.list_changes(limit)

    async def _set_role(self, actor: Actor, user: User, role: str) -> User:
        actor.require(ADMIN_USERS)
        if role not in ROLES:
            msg = f"Unknown role '{role}'. Roles: {', '.join(ROLES)}."
            raise InvalidChangeError(msg)
        _not_self(actor, user)
        before = {"role": user.role}
        user.role = role
        self._repo.add(user)
        await self._commit(_change(actor, "user.role", ("user", user.id), before, {"role": role}))
        return user

    async def _set_status(self, actor: Actor, user: User, status: str) -> User:
        actor.require(ADMIN_USERS)
        _not_self(actor, user)
        before = {"status": user.status}
        user.status = status
        self._repo.add(user)
        after = {"status": status}
        await self._commit(_change(actor, "user.status", ("user", user.id), before, after))
        if status == UserStatus.DISABLED:
            await self._end_firebase_sessions(user)
        return user

    async def _end_firebase_sessions(self, user: User) -> None:
        if self._verifier is None or not user.firebase_uid:
            return
        try:
            await self._verifier.revoke(user.firebase_uid)
        except Exception:
            # Status is enforced on every request; revocation only ends sessions sooner.
            logger.exception("access.revoke_failed", user_id=str(user.id))
```

- [ ] **Step 4: Retire `IdentityService.disable_user` (decision D3)**

In `backend/app/identity/service.py`, delete the `disable_user` method, then remove any import it
alone used (ruff reports them: `uv run ruff check app/identity`).

Replace `backend/tests/identity/test_service_admin.py` with:

```python
from app.config import Settings
from app.identity.repository import UserRepository
from app.identity.service import IdentityService


def _service(db) -> IdentityService:
    return IdentityService(
        UserRepository(db), Settings.model_validate({"environment": "test"})
    )


async def test_dev_user_is_created_once_as_viewer(db) -> None:
    first = await _service(db).ensure_dev_user()
    second = await _service(db).ensure_dev_user()

    assert first.user_id == second.user_id
    assert first.email == "dev@yougotagift.com"
    assert first.role == "viewer"
    assert first.auth_method == "dev"
```

(Disabling and revocation are now covered by `tests/access/test_admin_users.py`.)

- [ ] **Step 5: Run to verify they pass**

Run: `uv run ruff format app tests && uv run pytest tests/access tests/identity -q`
Expected: all pass, including `test_revoking_records_the_old_grant` from Task 8.

- [ ] **Step 6: Commit**

```bash
git add backend/app/access backend/app/identity backend/tests/access \
  backend/tests/identity backend/tests/access_helpers.py
git commit -m "feat(access): roles, status with revocation, effective access, change log"
```

---

### Task 10: Admin API

**Files:**
- Modify: `backend/app/access/schemas.py`, `backend/app/access/dependencies.py`,
  `backend/app/access/router.py`
- Test: `backend/tests/access/test_admin_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_admin_api.py
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app as asgi_app
from tests.access_helpers import make_user

REVENUE = "demo/order/revenue"


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


async def test_an_admin_grants_a_group_and_the_preview_explains_it(
    api: AsyncClient, db
) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")

    group = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    assert group.status_code == 201
    group_id = group.json()["id"]
    member = await api.put(
        f"/api/v1/admin/groups/{group_id}/members/{sara.id}", json={}
    )
    assert member.json()["email"] == "sara@yougotagift.com"
    grant = await api.post(
        "/api/v1/admin/grants",
        json={"subject_type": "group", "subject_id": group_id, "target": "demo/*"},
    )
    assert grant.status_code == 201

    preview = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()
    assert preview["decision"]["allowed"] is True
    assert "group:growth" in preview["decision"]["reason"]

    assert (await api.delete(f"/api/v1/admin/grants/{grant.json()['id']}")).status_code == 204
    preview = (
        await api.get(
            f"/api/v1/admin/users/{sara.id}/access", params={"resource": REVENUE}
        )
    ).json()
    assert preview["decision"]["allowed"] is False

    changes = (await api.get("/api/v1/admin/rbac-changes")).json()
    assert [c["action"] for c in changes[:4]] == [
        "grant.revoke",
        "grant.create",
        "member.put",
        "group.create",
    ]


async def test_viewers_cannot_administer(api: AsyncClient) -> None:
    resp = await api.get("/api/v1/admin/groups")
    assert resp.status_code == 403
    assert "admin:groups" in resp.json()["detail"]


async def test_errors_map_to_status_codes(api: AsyncClient, db) -> None:
    dev = await make_user(db, "dev@yougotagift.com", role="admin")
    await api.post("/api/v1/admin/groups", json={"name": "growth"})

    duplicate = await api.post("/api/v1/admin/groups", json={"name": "growth"})
    assert duplicate.status_code == 409
    missing = await api.delete(
        "/api/v1/admin/groups/00000000-0000-0000-0000-000000000000"
    )
    assert missing.status_code == 404
    groups = (await api.get("/api/v1/admin/groups")).json()
    bad_pattern = await api.post(
        "/api/v1/admin/grants",
        json={
            "subject_type": "group",
            "subject_id": groups[0]["id"],
            "target": "demo order",
        },
    )
    assert bad_pattern.status_code == 422
    myself = await api.patch(f"/api/v1/admin/users/{dev.id}", json={"role": "viewer"})
    assert myself.status_code == 409


async def test_user_admin_lists_and_updates_users(api: AsyncClient, db) -> None:
    await make_user(db, "dev@yougotagift.com", role="admin")
    sara = await make_user(db, "sara@yougotagift.com")

    found = (await api.get("/api/v1/admin/users", params={"q": "sara"})).json()
    assert [u["email"] for u in found] == ["sara@yougotagift.com"]
    updated = await api.patch(
        f"/api/v1/admin/users/{sara.id}", json={"role": "analyst"}
    )
    assert updated.json()["role"] == "analyst"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_admin_api.py -q`
Expected: FAIL with 404s (the admin routes do not exist).

- [ ] **Step 3: Response schemas**

Append to `backend/app/access/schemas.py` (add `Any` to the `typing` import, `ConfigDict` to the
pydantic import, and `from app.access.policy import Policy, Rule`):

```python
class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    parent_id: UUID | None
    created_at: datetime


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    target_kind: str
    target: str
    reason: str
    expires_at: datetime | None
    created_by: UUID | None
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    kind: str
    role: str
    status: str
    last_seen_at: datetime | None


class RuleOut(BaseModel):
    pattern: str
    grant_id: UUID
    origin: str

    @classmethod
    def of(cls, rule: Rule) -> Self:
        return cls(pattern=rule.pattern, grant_id=rule.grant_id, origin=rule.origin)


class DecisionOut(BaseModel):
    resource: str
    allowed: bool
    reason: str


class EffectiveAccessOut(BaseModel):
    user_id: UUID
    role: str
    active: bool
    capabilities: list[str]
    allow: list[RuleOut]
    deny: list[RuleOut]
    decision: DecisionOut | None

    @classmethod
    def from_policy(cls, policy: Policy, resource: str | None) -> Self:
        decision = None
        if resource:
            verdict = policy.decide(resource)
            decision = DecisionOut(
                resource=resource, allowed=verdict.allowed, reason=verdict.reason
            )
        return cls(
            user_id=policy.user_id,
            role=policy.role,
            active=policy.active,
            capabilities=sorted(policy.capabilities),
            allow=[RuleOut.of(r) for r in policy.allow_rules],
            deny=[RuleOut.of(r) for r in policy.deny_rules],
            decision=decision,
        )


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_user_id: UUID | None
    via: str
    action: str
    object_type: str
    object_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    at: datetime
```

- [ ] **Step 4: Dependencies for administration**

Append to `backend/app/access/dependencies.py` (imports: `AccessAdmin, Actor` from
`app.access.admin`; `TokenVerifier, get_token_verifier` from `app.identity`):

```python
def get_access_admin(
    db: AsyncSession = Depends(get_db),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AccessAdmin:
    repo = AccessRepository(db)
    return AccessAdmin(repo, AccessService(repo, shared_cache()), verifier)


def get_actor(policy: Policy = Depends(get_policy)) -> Actor:
    """Capability checks happen in AccessAdmin (managers are not admins, D8)."""
    return Actor.from_policy(policy)
```

- [ ] **Step 5: Admin routes**

Append to `backend/app/access/router.py`. Extend its imports:

```python
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.admin import AccessAdmin, Actor
from app.access.dependencies import (
    get_access_admin,
    get_access_service,
    get_actor,
    get_policy,
)
from app.access.schemas import (
    CatalogOut,
    ChangeOut,
    EffectiveAccessOut,
    GrantCreate,
    GrantOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    MeAccessOut,
    MemberOut,
    MemberPut,
    UserOut,
    UserUpdate,
)
```

then add:

```python
# ---- administration (spec §10; UI in phase 5) -------------------------------


@router.get("/admin/groups", response_model=list[GroupOut])
async def list_groups(
    actor: Actor = Depends(get_actor), admin: AccessAdmin = Depends(get_access_admin)
) -> list[GroupOut]:
    return [GroupOut.model_validate(g) for g in await admin.list_groups(actor)]


@router.post("/admin/groups", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(await admin.create_group(actor, payload))


@router.patch("/admin/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(await admin.update_group(actor, group_id, payload))


@router.delete("/admin/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.delete_group(actor, group_id)


@router.get("/admin/groups/{group_id}/members", response_model=list[MemberOut])
async def list_members(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[MemberOut]:
    return await admin.list_members(actor, group_id)


@router.put("/admin/groups/{group_id}/members/{user_id}", response_model=MemberOut)
async def put_member(
    group_id: UUID,
    user_id: UUID,
    payload: MemberPut,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> MemberOut:
    return await admin.put_member(actor, group_id, user_id, payload.standing)


@router.delete("/admin/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: UUID,
    user_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.remove_member(actor, group_id, user_id)


@router.get("/admin/grants", response_model=list[GrantOut])
async def list_grants(
    subject_type: Literal["group", "user"],
    subject_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[GrantOut]:
    grants = await admin.list_grants(actor, subject_type, subject_id)
    return [GrantOut.model_validate(g) for g in grants]


@router.post("/admin/grants", response_model=GrantOut, status_code=201)
async def create_grant(
    payload: GrantCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GrantOut:
    return GrantOut.model_validate(await admin.create_grant(actor, payload))


@router.delete("/admin/grants/{grant_id}", status_code=204)
async def revoke_grant(
    grant_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.revoke_grant(actor, grant_id)


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await admin.list_users(actor, q, limit)]


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> UserOut:
    return UserOut.model_validate(await admin.update_user(actor, user_id, payload))


@router.get("/admin/users/{user_id}/access", response_model=EffectiveAccessOut)
async def user_access(
    user_id: UUID,
    resource: str | None = None,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> EffectiveAccessOut:
    policy = await admin.effective_access(actor, user_id)
    return EffectiveAccessOut.from_policy(policy, resource)


@router.get("/admin/rbac-changes", response_model=list[ChangeOut])
async def rbac_changes(
    limit: int = Query(100, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[ChangeOut]:
    return [ChangeOut.model_validate(c) for c in await admin.list_changes(actor, limit)]
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run ruff format app tests && uv run pytest tests/access -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/access backend/tests/access
git commit -m "feat(access): admin API for groups, members, grants, users and the change log"
```

---

### Task 11: Admin CLI

**Files:**
- Create: `backend/app/access/cli.py`
- Test: `backend/tests/access/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/access/test_cli.py
import pytest
from sqlmodel import select

from app.access import cli
from app.access.models import RbacChange
from tests.access_helpers import make_group, make_user


async def test_bootstrap_an_admin_from_the_shell(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_group(db, "atlas-admins")
    await make_user(db, "ashik@yougotagift.com", role="admin")

    assert await cli.run(["add-member", "ashik@yougotagift.com", "atlas-admins", "--manager"]) == 0
    assert await cli.run(
        ["grant", "group:atlas-admins", "allow", "*", "--reason", "bootstrap"]
    ) == 0
    assert await cli.run(
        ["access", "ashik@yougotagift.com", "--resource", "demo/order/revenue"]
    ) == 0

    out = capsys.readouterr().out
    assert "is now a manager of atlas-admins" in out
    assert "allowed by grant" in out
    changes = (await db.execute(select(RbacChange))).scalars().all()
    assert {c.via for c in changes} == {"cli"}


async def test_errors_are_reported_not_raised(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["add-member", "ghost@yougotagift.com", "nowhere"]) == 1
    assert "error: No group named 'nowhere'" in capsys.readouterr().out


async def test_bad_subjects_and_patterns_fail(db) -> None:
    await make_group(db, "marketing")
    assert await cli.run(["grant", "team:marketing", "allow", "*"]) == 1
    assert await cli.run(["grant", "group:marketing", "allow", "demo order"]) == 1


async def test_groups_prints_the_tree(db, capsys: pytest.CaptureFixture[str]) -> None:
    parent = await make_group(db, "marketing")
    await make_group(db, "growth", parent=parent)

    assert await cli.run(["groups"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("marketing")
    assert lines[1].startswith("  growth")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/access/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'cli'`.

- [ ] **Step 3: Implement**

```python
# backend/app/access/cli.py
"""Administer access from a shell; there is no admin UI until phase 5 (decision D5).

    uv run python -m app.access.cli groups
    uv run python -m app.access.cli add-member ashik@yougotagift.com atlas-admins --manager
    uv run python -m app.access.cli remove-member someone@yougotagift.com marketing
    uv run python -m app.access.cli grant group:atlas-admins allow '*' --reason bootstrap
    uv run python -m app.access.cli grant user:dev@yougotagift.com allow '*' --reason dev
    uv run python -m app.access.cli revoke <grant-id>
    uv run python -m app.access.cli set-role someone@yougotagift.com analyst
    uv run python -m app.access.cli access someone@yougotagift.com --resource demo/order/revenue

On the server: `docker compose exec backend uv run --no-dev python -m app.access.cli ...`.
Every change is recorded in rbac_changes with via="cli".
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.access.admin import AccessAdmin, Actor
from app.access.cache import shared_cache
from app.access.errors import AccessError, InvalidChangeError, NotFoundError
from app.access.facts import DEFAULT_TENANT, SUBJECT_GROUP, SUBJECT_USER
from app.access.models import Group
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate, UserUpdate
from app.access.service import AccessService
from app.database import get_session_factory
from app.identity import User


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


@dataclass(frozen=True, slots=True)
class _Context:
    admin: AccessAdmin
    repo: AccessRepository
    actor: Actor

    async def group(self, name: str) -> Group:
        group = await self.repo.group_by_name(DEFAULT_TENANT, name)
        if group is None:
            msg = f"No group named '{name}'. Run `groups` to list them."
            raise NotFoundError(msg)
        return group

    async def user(self, email: str) -> User:
        user = await self.repo.user_by_email(email)
        if user is None:
            msg = f"No user {email}. They must sign in to atlas once first."
            raise NotFoundError(msg)
        return user


type _Command = Callable[[_Context, argparse.Namespace], Awaitable[None]]


async def _groups(ctx: _Context, _args: argparse.Namespace) -> None:
    by_parent: dict[UUID | None, list[Group]] = {}
    for group in await ctx.admin.list_groups(ctx.actor):
        by_parent.setdefault(group.parent_id, []).append(group)

    def show(parent: UUID | None, depth: int) -> None:
        for group in by_parent.get(parent, []):
            _out(f"{'  ' * depth}{group.name}  ({group.id})")
            show(group.id, depth + 1)

    show(None, 0)


async def _add_member(ctx: _Context, args: argparse.Namespace) -> None:
    group = await ctx.group(args.group)
    user = await ctx.user(args.email)
    standing = "manager" if args.manager else "member"
    await ctx.admin.put_member(ctx.actor, group.id, user.id, standing)
    _out(f"{user.email} is now a {standing} of {group.name}")


async def _remove_member(ctx: _Context, args: argparse.Namespace) -> None:
    group = await ctx.group(args.group)
    user = await ctx.user(args.email)
    await ctx.admin.remove_member(ctx.actor, group.id, user.id)
    _out(f"{user.email} removed from {group.name}")


async def _grant(ctx: _Context, args: argparse.Namespace) -> None:
    kind, _, name = str(args.subject).partition(":")
    if kind == SUBJECT_GROUP:
        subject_id = (await ctx.group(name)).id
    elif kind == SUBJECT_USER:
        subject_id = (await ctx.user(name)).id
    else:
        msg = "The subject must be group:<name> or user:<email>."
        raise InvalidChangeError(msg)
    payload = GrantCreate.model_validate(
        {
            "subject_type": kind,
            "subject_id": subject_id,
            "effect": args.effect,
            "target": args.pattern,
            "reason": args.reason,
            "expires_at": args.expires,
        }
    )
    grant = await ctx.admin.create_grant(ctx.actor, payload)
    _out(f"granted {grant.id}: {grant.effect} {grant.target} to {args.subject}")


async def _revoke(ctx: _Context, args: argparse.Namespace) -> None:
    await ctx.admin.revoke_grant(ctx.actor, UUID(args.grant_id))
    _out(f"revoked {args.grant_id}")


async def _set_role(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    await ctx.admin.update_user(ctx.actor, user.id, UserUpdate(role=args.role))
    _out(f"{user.email} is now {args.role}")


async def _access(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    policy = await ctx.admin.effective_access(ctx.actor, user.id)
    state = "active" if policy.active else "disabled"
    _out(f"{user.email}: role {policy.role}, {state}")
    _out("capabilities: " + ", ".join(sorted(policy.capabilities)))
    for rule in policy.allow_rules:
        _out(f"allow {rule.pattern}  ({rule.origin}, grant {rule.grant_id})")
    for rule in policy.deny_rules:
        _out(f"deny  {rule.pattern}  ({rule.origin}, grant {rule.grant_id})")
    if args.resource:
        _out(f"{args.resource}: {policy.decide(args.resource).reason}")


_COMMANDS: dict[str, _Command] = {
    "groups": _groups,
    "add-member": _add_member,
    "remove-member": _remove_member,
    "grant": _grant,
    "revoke": _revoke,
    "set-role": _set_role,
    "access": _access,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.access.cli", description="Administer atlas access."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("groups", help="list groups as a tree")
    add = sub.add_parser("add-member", help="add a user to a group")
    add.add_argument("email")
    add.add_argument("group")
    add.add_argument("--manager", action="store_true")
    remove = sub.add_parser("remove-member", help="remove a user from a group")
    remove.add_argument("email")
    remove.add_argument("group")
    grant = sub.add_parser("grant", help="allow or deny a resource pattern")
    grant.add_argument("subject", help="group:<name> or user:<email>")
    grant.add_argument("effect", choices=["allow", "deny"])
    grant.add_argument("pattern", help="e.g. '*', 'deepsales/*', 'demo/order/revenue'")
    grant.add_argument("--reason", default="")
    grant.add_argument("--expires", default=None, help="ISO time with offset")
    revoke = sub.add_parser("revoke", help="delete a grant")
    revoke.add_argument("grant_id")
    role = sub.add_parser("set-role", help="change a user's role")
    role.add_argument("email")
    role.add_argument("role")
    show = sub.add_parser("access", help="explain a user's effective access")
    show.add_argument("email")
    show.add_argument("--resource", default=None)
    return parser


async def run(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    async with get_session_factory()() as db:
        repo = AccessRepository(db)
        admin = AccessAdmin(repo, AccessService(repo, shared_cache()))
        try:
            await _COMMANDS[args.command](_Context(admin, repo, Actor.cli()), args)
        except (AccessError, ValueError) as exc:  # ValueError covers bad UUIDs/input
            _out(f"error: {exc}")
            return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run ruff format app tests && uv run pytest tests/access/test_cli.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/access/cli.py backend/tests/access/test_cli.py
git commit -m "feat(access): admin CLI (audited as via=cli)"
```

---

### Task 12: Atlas enforcement: discovery filtering, execution checks, decision audit

**Files:**
- Create: `backend/app/atlas/policy.py`, `backend/tests/fakes.py`,
  `backend/tests/test_atlas_access.py`
- Modify: `backend/app/atlas/tools.py`, `backend/app/atlas/__init__.py`,
  `backend/tests/test_atlas_tools.py`, `backend/tests/test_deepsales_plugin.py`,
  `backend/tests/test_insights_service.py`

After this task the agent, chat API, insights wiring and MCP server no longer construct
`AtlasTools` correctly; Tasks 13 and 14 fix them. Run only the files named below until then.

- [ ] **Step 1: The test double and the failing tests**

```python
# backend/tests/fakes.py
"""Test doubles shared across test modules."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools


@dataclass(frozen=True)
class StaticPolicy:
    """ResourcePolicy double: '*', exact paths and 'prefix/*' patterns."""

    allowed: Sequence[str] = ("*",)

    def allows(self, resource: str) -> bool:
        return any(
            pattern in ("*", resource)
            or (pattern.endswith("/*") and resource.startswith(pattern[:-1]))
            for pattern in self.allowed
        )

    def deny_reason(self, resource: str) -> str:
        return "not in the test allowlist"


def make_tools(
    db: AsyncSession | None = None,
    registry: AtlasRegistry | None = None,
    *,
    allowed: Sequence[str] = ("*",),
    surface: str = "chat",
    user_id: UUID | None = None,
    session_id: UUID | None = None,
) -> AtlasTools:
    caller = AtlasCaller(
        user_id=user_id or uuid4(),
        auth_method="test",
        surface=surface,
        session_id=session_id,
    )
    return AtlasTools(caller, StaticPolicy(allowed), db=db, registry=registry)
```

```python
# backend/tests/test_atlas_access.py
"""Enforcement points 1, 2 and 5 (spec §6): discovery, execution, audit."""

from uuid import uuid4

from sqlmodel import col, select

from app.models.audit import AtlasAuditLog
from tests.fakes import make_tools

ORDERS_ONLY = ("demo/order/*",)
WEEK = {"start_date": "2026-01-01", "end_date": "2026-01-07"}


async def test_list_metrics_shows_only_allowed_items(db) -> None:
    result = await make_tools(db=db, allowed=ORDERS_ONLY).execute("list_metrics", {})
    demo = result["sources"][0]
    ids = {m["id"] for m in demo["metrics"]}
    assert "revenue" in ids
    assert "new_customers" not in ids
    assert demo["funnels"] == []


async def test_no_grants_means_an_empty_catalog(db) -> None:
    result = await make_tools(db=db, allowed=()).execute("list_metrics", {})
    assert result == {"sources": []}


async def test_search_hides_what_the_caller_cannot_see(db) -> None:
    result = await make_tools(db=db, allowed=ORDERS_ONLY).execute(
        "search_atlas", {"query": "checkout funnel revenue"}
    )
    found = {(r["kind"], r["id"]) for r in result["results"]}
    assert ("metric", "revenue") in found
    assert all(kind != "funnel" for kind, _ in found)


async def test_a_denied_metric_is_refused_and_audited_as_deny(db) -> None:
    user_id = uuid4()
    tools = make_tools(db=db, allowed=("demo/customer/*",), user_id=user_id)

    result = await tools.execute("query_metric", {"metric_id": "revenue", **WEEK})

    assert "isn't available to you" in result["error"]
    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert (row.decision, row.success) == ("deny", False)
    assert row.deny_reason == "not in the test allowlist"
    assert row.auth_method == "test"
    assert row.user_uid == str(user_id)


async def test_breakdowns_comparisons_and_funnels_are_checked(db) -> None:
    tools = make_tools(db=db, allowed=("demo/customer/*",))
    breakdown = await tools.execute("metric_breakdown", {"metric_id": "revenue", **WEEK})
    compare = await tools.execute(
        "compare_periods",
        {
            "metric_id": "revenue",
            "period_a_start": "2026-01-08",
            "period_a_end": "2026-01-14",
            "period_b_start": "2026-01-01",
            "period_b_end": "2026-01-07",
        },
    )
    funnel = await tools.execute("funnel_analyze", {"funnel_id": "checkout_funnel", **WEEK})
    for result in (breakdown, compare, funnel):
        assert "isn't available to you" in result["error"]


async def test_entities_are_visible_through_their_items(db) -> None:
    tools = make_tools(db=db, allowed=("demo/order/revenue",))
    entity = await tools.execute("describe_entity", {"entity_id": "order"})
    assert entity["metrics"] == ["revenue"]
    hidden = await tools.execute("describe_entity", {"entity_id": "customer"})
    assert "isn't available to you" in hidden["error"]


async def test_allowed_calls_are_audited_as_allow(db) -> None:
    user_id = uuid4()
    await make_tools(db=db, user_id=user_id).execute("list_metrics", {})
    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert row.decision == "allow"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_atlas_access.py -q`
Expected: FAIL with `ImportError: cannot import name 'AtlasCaller' from 'app.atlas'`.

- [ ] **Step 3: The atlas side of the contract**

```python
# backend/app/atlas/policy.py
"""What the atlas needs from an access policy (spec §6, enforcement points 1, 2, 5).

The atlas never imports app.access (ARCHITECTURE.md): the edges pass the caller's
evaluated Policy, which satisfies `ResourcePolicy` structurally.
Resource paths are `source/entity/item`; an entity alone is `source/entity`.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.atlas.models import EntityDef, FunnelDef, MetricDef


class ResourcePolicy(Protocol):
    def allows(self, resource: str) -> bool: ...

    def deny_reason(self, resource: str) -> str: ...


@dataclass(frozen=True, slots=True)
class AtlasCaller:
    """Who runs the tools, as recorded in the audit log."""

    user_id: UUID
    auth_method: str
    surface: str = "chat"  # 'chat' | 'mcp' | 'api'
    session_id: UUID | None = None


def metric_resource(metric: MetricDef) -> str:
    return f"{metric.source}/{metric.entity}/{metric.id}"


def funnel_resource(funnel: FunnelDef) -> str:
    return f"{funnel.source}/{funnel.entity}/{funnel.id}"


def entity_resource(entity: EntityDef) -> str:
    return f"{entity.source}/{entity.id}"
```

Replace `backend/app/atlas/__init__.py` with:

```python
from app.atlas.policy import AtlasCaller, ResourcePolicy
from app.atlas.registry import AtlasRegistry, get_registry
from app.atlas.tools import ATLAS_TOOL_SCHEMAS, AtlasTools

__all__ = [
    "ATLAS_TOOL_SCHEMAS",
    "AtlasCaller",
    "AtlasRegistry",
    "AtlasTools",
    "ResourcePolicy",
    "get_registry",
]
```

- [ ] **Step 4: Enforce in `AtlasTools`**

In `backend/app/atlas/tools.py`:

Replace the imports from `import time` through `logger = structlog.get_logger()` with:

```python
import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas.models import EntityDef, FunnelDef, MetricDef
from app.atlas.policy import (
    AtlasCaller,
    ResourcePolicy,
    entity_resource,
    funnel_resource,
    metric_resource,
)
from app.atlas.provenance import build_provenance
from app.atlas.registry import AtlasRegistry, get_registry
from app.models.audit import AtlasAuditLog
from app.sources import ConnectorError, ConnectorNotConfiguredError, get_connector

logger = structlog.get_logger()

SEARCH_LIMIT = 10
SEARCH_POOL = 50  # search wider, then drop what the caller may not see
ALLOW = "allow"
DENY = "deny"
MAX_DENY_REASON = 200
```

After the `AtlasToolError` class add:

```python
class AtlasAccessDeniedError(AtlasToolError):
    """The caller's policy denies a governed resource (spec §6, point 2)."""

    def __init__(self, label: str, reason: str) -> None:
        super().__init__(
            f"{label} isn't available to you. Ask an atlas admin if you need it."
        )
        self.reason = reason


@dataclass(frozen=True, slots=True)
class _Outcome:
    success: bool = True
    error: str | None = None
    decision: str = ALLOW
    deny_reason: str | None = None
```

Replace everything from `class AtlasTools:` down to (not including) the
`# ---- helpers ---` comment, that is the docstring, `__init__`, `registry`, `execute` and
`_audit`, with:

```python
class AtlasTools:
    """Tool executor for one caller: filtered by their policy, audited per call."""

    def __init__(
        self,
        caller: AtlasCaller,
        policy: ResourcePolicy,
        db: AsyncSession | None = None,
        registry: AtlasRegistry | None = None,
    ) -> None:
        self.caller = caller
        self._policy = policy
        self.db = db
        self._registry = registry

    @property
    def registry(self) -> AtlasRegistry:
        return self._registry if self._registry is not None else get_registry()

    def visible_metrics(self) -> dict[str, MetricDef]:
        """Metrics this caller may see (spec §6, enforcement point 1)."""
        return {
            mid: m
            for mid, m in self.registry.metrics.items()
            if self._policy.allows(metric_resource(m))
        }

    def visible_funnels(self) -> dict[str, FunnelDef]:
        return {
            fid: f
            for fid, f in self.registry.funnels.items()
            if self._policy.allows(funnel_resource(f))
        }

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch + audit. Returns a JSON-safe dict; errors become {'error': ...}."""
        handlers = {
            "list_metrics": self.list_metrics,
            "query_metric": self.query_metric,
            "metric_breakdown": self.metric_breakdown,
            "describe_entity": self.describe_entity,
            "funnel_analyze": self.funnel_analyze,
            "compare_periods": self.compare_periods,
            "search_atlas": self.search_atlas,
        }
        if tool not in handlers:
            return {"error": f"Unknown tool '{tool}'"}

        started = time.monotonic()
        outcome = _Outcome()
        try:
            result = await handlers[tool](**arguments)
        except AtlasAccessDeniedError as exc:
            outcome = _Outcome(False, str(exc), DENY, exc.reason[:MAX_DENY_REASON])
            result = {"error": str(exc)}
        except (AtlasToolError, ConnectorNotConfiguredError, ConnectorError) as exc:
            outcome = _Outcome(False, str(exc))
            result = {"error": str(exc)}
        except TypeError as exc:
            outcome = _Outcome(False, f"Invalid arguments: {exc}")
            result = {"error": f"Invalid arguments: {exc}"}
        except Exception as exc:  # unexpected — log loudly, keep the answer honest
            logger.exception("atlas.tool_failed", tool=tool)
            outcome = _Outcome(False, str(exc))
            result = {"error": f"Internal error executing {tool}"}

        elapsed_ms = int((time.monotonic() - started) * 1000)
        await self._audit(tool, arguments, outcome, elapsed_ms)
        return result

    async def _audit(
        self,
        tool: str,
        arguments: dict[str, Any],
        outcome: _Outcome,
        duration_ms: int,
    ) -> None:
        if self.db is None:
            return
        self.db.add(
            AtlasAuditLog(
                user_uid=str(self.caller.user_id),
                user_id=self.caller.user_id,
                auth_method=self.caller.auth_method,
                session_id=self.caller.session_id,
                surface=self.caller.surface,
                tool=tool,
                arguments=arguments,
                success=outcome.success,
                error=outcome.error,
                duration_ms=duration_ms,
                decision=outcome.decision,
                deny_reason=outcome.deny_reason,
            )
        )
        await self.db.commit()

    def _authorize(self, resource: str, label: str) -> None:
        if not self._policy.allows(resource):
            raise AtlasAccessDeniedError(label, self._policy.deny_reason(resource))

    def _entity_visible(self, entity: EntityDef) -> bool:
        return (
            self._policy.allows(entity_resource(entity))
            or any(self._policy.allows(metric_resource(m)) for m in entity.metrics)
            or any(self._policy.allows(funnel_resource(f)) for f in entity.funnels)
        )
```

In `_get_metric`, after the existing `if metric is None: raise ...` block and before
`return metric`, add:

```python
        self._authorize(metric_resource(metric), metric.name)
```

In `list_metrics`, change the two loops to iterate the visible items:

```python
        for m in self.visible_metrics().values():
```

```python
        for f in self.visible_funnels().values():
```

Replace `describe_entity` with:

```python
    async def describe_entity(self, entity_id: str) -> dict[str, Any]:
        entity = self.registry.entities.get(entity_id)
        if entity is None:
            raise AtlasToolError(
                f"No entity '{entity_id}' in the atlas. Use search_atlas."
            )
        if not self._entity_visible(entity):
            raise AtlasAccessDeniedError(
                entity.name, self._policy.deny_reason(entity_resource(entity))
            )
        metrics, funnels = self.visible_metrics(), self.visible_funnels()
        return {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "source": entity.source,
            "fields": entity.fields,
            "pii_fields": entity.pii_fields,
            "metrics": [m.id for m in entity.metrics if m.id in metrics],
            "funnels": [f.id for f in entity.funnels if f.id in funnels],
        }
```

In `funnel_analyze`, after the `if funnel is None: raise ...` block add:

```python
        self._authorize(funnel_resource(funnel), funnel.name)
```

Replace `search_atlas` with:

```python
    async def search_atlas(self, query: str) -> dict[str, Any]:
        entities = {
            e.id for e in self.registry.entities.values() if self._entity_visible(e)
        }
        visible: dict[str, Collection[str]] = {
            "metric": self.visible_metrics().keys(),
            "funnel": self.visible_funnels().keys(),
            "entity": entities,
        }
        results = [
            r
            for r in self.registry.search(query, limit=SEARCH_POOL)
            if r["id"] in visible.get(r["kind"], ())
        ][:SEARCH_LIMIT]
        return {
            "results": results,
            "hint": (
                "Nothing matched. Ask the user a clarifying question — do not guess "
                "or fabricate."
                if not results
                else None
            ),
        }
```

Delete the now-unused `from uuid import UUID` import if ruff reports it.

- [ ] **Step 5: Move the existing atlas tests to the new constructor**

```bash
cd backend
sed -i '' 's/AtlasTools(user_uid="u1", db=db)/make_tools(db=db)/' tests/test_atlas_tools.py
```

Then in `backend/tests/test_atlas_tools.py`: replace `from app.atlas.tools import AtlasTools` with
`from uuid import uuid4` (stdlib block), `from sqlmodel import col, select` (replacing
`from sqlmodel import select`) and `from tests.fakes import make_tools`; and replace
`test_every_execution_is_audited` with:

```python
async def test_every_execution_is_audited(db):
    user_id = uuid4()
    tools = make_tools(db=db, user_id=user_id)
    start, end = _range(2)
    await tools.execute(
        "query_metric", {"metric_id": "revenue", "start_date": start, "end_date": end}
    )
    await tools.execute(
        "query_metric", {"metric_id": "nope", "start_date": start, "end_date": end}
    )

    rows = (
        (
            await db.execute(
                select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.success for r in rows} == {True, False}
    assert all(r.tool == "query_metric" for r in rows)
    assert {r.decision for r in rows} == {"allow"}  # an unknown id is not a denial
```

In `backend/tests/test_deepsales_plugin.py`, replace the `AtlasTools(...)` construction with
`make_tools(registry=AtlasRegistry(plugins={"deepsales": SOURCE}))` and import `make_tools` from
`tests.fakes` (drop the `AtlasTools` import if unused).

In `backend/tests/test_insights_service.py`: import `from uuid import uuid4`,
`from app.atlas import AtlasCaller` and `from tests.fakes import StaticPolicy, make_tools`; change
the `ScriptedTools` super call to

```python
        super().__init__(
            AtlasCaller(user_id=uuid4(), auth_method="test", surface="api"),
            StaticPolicy(),
            registry=registry,
        )
```

and replace `AtlasTools(user_uid="u", surface="api")` and `AtlasTools(user_uid="u")` with
`make_tools(surface="api")`.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run ruff format app tests && uv run pytest tests/test_atlas_access.py tests/test_atlas_tools.py tests/test_deepsales_plugin.py tests/test_insights_service.py tests/test_registry.py -q`
Expected: all pass (the live DeepSales smoke test stays skipped without credentials).

- [ ] **Step 7: Commit**

```bash
git add backend/app/atlas backend/tests/fakes.py backend/tests/test_atlas_access.py \
  backend/tests/test_atlas_tools.py backend/tests/test_deepsales_plugin.py \
  backend/tests/test_insights_service.py
git commit -m "feat(atlas): policy-filtered discovery, checked execution, decision audit"
```

---

### Task 13: Agent: the turn takes `AtlasTools`; guardrails by `user_id`; honest denials

**Files:**
- Modify: `backend/app/agent/loop.py`, `backend/app/agent/guardrails.py`,
  `backend/app/agent/prompts.py`
- Test: `backend/tests/test_agent_loop.py`, `backend/tests/test_guardrails.py`,
  `backend/tests/test_prompts.py`

- [ ] **Step 1: Update the tests first**

In `backend/tests/test_agent_loop.py`:
- add `from uuid import uuid4` and `from tests.fakes import make_tools` to the imports;
- replace `_make_session` and add `_tools`:

```python
async def _make_session(db) -> ChatSession:
    session = ChatSession(user_id=uuid4(), user_email="u1@yougotagift.com")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


def _tools(db, session: ChatSession, allowed: tuple[str, ...] = ("*",)):
    return make_tools(
        db=db, user_id=session.user_id, session_id=session.id, allowed=allowed
    )
```

- move every call to the new signature:

```bash
sed -i '' 's/run_chat_turn("u1", session.id, /run_chat_turn(_tools(db, session), /' \
  tests/test_agent_loop.py
```

- append:

```python
async def test_clarify_cannot_offer_metrics_the_user_cannot_see(db):
    session = await _make_session(db)
    options = [
        {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
        {"label": "All revenue", "metric_id": "revenue"},
    ]
    client = FakeAnthropicClient(
        [_clarify_call("Which revenue?", options), _text("Which revenue?")]
    )
    tools = _tools(db, session, allowed=("demo/order/revenue",))

    events = await collect(
        run_chat_turn(tools, "how is revenue?", [], db, client=client)
    )

    offered = events[-1]["blocks"][0]["options"]
    assert [o["metric_id"] for o in offered] == [None, "revenue"]
```

Replace `backend/tests/test_guardrails.py` with:

```python
from uuid import uuid4

from app.agent.guardrails import check_input
from app.models.chat import ChatMessage, ChatSession


async def test_empty_message_blocked(db):
    verdict = await check_input("   ", uuid4(), db)
    assert not verdict.allowed


async def test_too_long_blocked(db):
    verdict = await check_input("x" * 5000, uuid4(), db)
    assert not verdict.allowed
    assert "too long" in verdict.reason.lower()


async def test_normal_message_allowed(db):
    verdict = await check_input("What was revenue last week?", uuid4(), db)
    assert verdict.allowed


async def test_daily_rate_limit(db):
    heavy = uuid4()
    session = ChatSession(user_id=heavy, user_email="h@yougotagift.com")
    db.add(session)
    await db.commit()
    for i in range(5):  # test env sets CHAT_DAILY_MESSAGE_LIMIT=5
        db.add(ChatMessage(session_id=session.id, role="user", content=f"q{i}"))
    await db.commit()

    verdict = await check_input("one more", heavy, db)
    assert not verdict.allowed
    assert "limit" in verdict.reason.lower()

    # other users are unaffected
    verdict = await check_input("hello", uuid4(), db)
    assert verdict.allowed
```

Append to `backend/tests/test_prompts.py`:

```python
def test_prompt_explains_missing_access_honestly() -> None:
    prompt = build_system_prompt()
    assert "isn't available" in prompt
    assert "atlas admin" in prompt
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_agent_loop.py tests/test_guardrails.py tests/test_prompts.py -q`
Expected: FAIL (old `run_chat_turn` and `check_input` signatures; no rule 10).

- [ ] **Step 3: Implement**

`backend/app/agent/guardrails.py`: add `from uuid import UUID`, change the signature to
`async def check_input(content: str, user_id: UUID, db: AsyncSession) -> GuardrailVerdict:` and the
owner filter to `col(ChatSession.user_id) == user_id,`.

`backend/app/agent/loop.py`:
- change `from app.atlas import ATLAS_TOOL_SCHEMAS, AtlasTools` (unchanged) and remove
  `from uuid import UUID` if it becomes unused;
- in `_TurnRecorder._clarify`, change the known ids to the caller's visible metrics:

```python
        block = build_clarify_block(arguments, set(self._tools.visible_metrics()))
```

- replace the `run_chat_turn` signature and its first lines with:

```python
async def run_chat_turn(
    tools: AtlasTools,
    content: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
    client: AnthropicClient | None = None,
) -> AsyncGenerator[Event, None]:
    """One chat turn for the caller bound to `tools` (their policy and audit identity)."""
    settings = get_settings()

    verdict = await check_input(content, tools.caller.user_id, db)
    if not verdict.allowed:
        yield {"type": "blocked", "reason": verdict.reason}
        return

    run_tool_loop = _select_provider(client)
    recorder = _TurnRecorder(tools)
```

  (delete the old `tools = AtlasTools(user_uid=...)` line), and in the `except` block log
  `session_id=str(tools.caller.session_id)`.

`backend/app/agent/prompts.py`: append rule 10 to `SYSTEM_PROMPT_TEMPLATE`, after rule 9:

```python
    "10. Access is per person. If list_metrics returns no sources, or a tool says "
    "something isn't available to the user, the user lacks access to it; it does "
    "not mean the data doesn't exist. Say so plainly, suggest asking an atlas "
    "admin for access, and don't look for the same data another way.\n"
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run ruff format app tests && uv run pytest tests/test_agent_loop.py tests/test_guardrails.py tests/test_prompts.py tests/test_openai_loop.py tests/test_answer_blocks.py -q`
Expected: all pass. (`test_openai_loop.py` uses the provider loop directly; if it calls
`run_chat_turn`, move it to the new signature the same way as `test_agent_loop.py`.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent backend/tests/test_agent_loop.py backend/tests/test_guardrails.py \
  backend/tests/test_prompts.py
git commit -m "feat(agent): turns run with the caller's tools; guardrails by user id; honest denials"
```

---

### Task 14: Edges: chat API, insights, MCP; retire the middleware shim

**Files:**
- Modify: `backend/app/api/chat.py`, `backend/app/insights/dependencies.py`,
  `backend/app/insights/router.py`, `backend/app/insights/service.py`, `backend/app/mcp/server.py`
- Delete: `backend/app/middleware/` (whole package), `backend/tests/test_middleware_shim.py`
- Test: `backend/tests/test_chat_api.py`, `backend/tests/test_insights_api.py`,
  `backend/tests/test_mcp_access.py` (create)

- [ ] **Step 1: Update and write the tests**

In `backend/tests/test_chat_api.py`:
- the fake turn takes the new signature:

```python
    async def fake_run_chat_turn(tools, content, history, db, client=None):
```

- in `test_session_crud`, delete the `assert created["user_uid"] == me["user_id"]` line;
- the foreign session in the isolation test becomes
  `ChatSession(user_id=uuid4(), user_email="x@yougotagift.com")` (add `from uuid import uuid4`);
- append:

```python
async def test_chat_needs_the_chat_capability(api, db):
    dev = await make_user(db, "dev@yougotagift.com")
    await add_grant(db, dev, "chat:use", effect="deny", kind="capability")
    resp = await api.get("/api/v1/chat/sessions")
    assert resp.status_code == 403
    assert "chat:use" in resp.json()["detail"]
```

  (import `make_user, add_grant` from `tests.access_helpers`).

In `backend/tests/test_insights_api.py`: make the `api` fixture call `await grant_all(db)` before
creating the client (import `grant_all` from `tests.access_helpers`), and append:

```python
async def test_without_grants_the_catalog_is_empty(db: AsyncSession) -> None:
    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        catalog = (await client.get("/api/v1/atlas/metrics")).json()
        overview = (await client.get("/api/v1/atlas/overview?days=7")).json()
    assert catalog == {"sources": []}
    assert overview["kpis"] == []
```

Create the MCP tests:

```python
# backend/tests/test_mcp_access.py
"""MCP until phase 4: a shared token that is required, and a service user's grants."""

from collections.abc import Callable, Iterator

import pytest
from httpx import ASGITransport, AsyncClient, Response
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import get_settings
from app.mcp import server
from tests.access_helpers import add_grant, make_user

SERVICE_EMAIL = "mcp-shared@atlas.internal"


async def _get(headers: dict[str, str] | None = None) -> Response:
    async def ok(_request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[Route("/", ok)],
        middleware=[Middleware(server.BearerTokenMiddleware)],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get("/", headers=headers or {})


@pytest.fixture
def mcp_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def set_token(value: str) -> None:
        monkeypatch.setenv("ATLAS_MCP_TOKEN", value)
        get_settings.cache_clear()

    yield set_token
    get_settings.cache_clear()


async def test_mcp_is_off_without_a_token(mcp_token: Callable[[str], None]) -> None:
    mcp_token("")
    assert (await _get()).status_code == 503


async def test_the_token_must_match(mcp_token: Callable[[str], None]) -> None:
    mcp_token("s3cret")
    assert (await _get({"Authorization": "Bearer wrong"})).status_code == 401
    assert (await _get({"Authorization": "Bearer s3cret"})).status_code == 200


async def test_tools_run_as_the_service_user_with_its_grants(db) -> None:
    assert await server.run_tool("list_metrics", {}) == server.NOT_READY
    service = await make_user(db, SERVICE_EMAIL, role="analyst", kind="service")
    assert await server.run_tool("list_metrics", {}) == {"sources": []}

    await add_grant(db, service, "demo/order/*")

    result = await server.run_tool("list_metrics", {})
    assert "revenue" in {m["id"] for m in result["sources"][0]["metrics"]}


async def test_a_service_user_without_mcp_use_is_refused(db) -> None:
    await make_user(db, SERVICE_EMAIL, role="viewer", kind="service")
    assert await server.run_tool("list_metrics", {}) == server.NO_MCP_ACCESS
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_chat_api.py tests/test_insights_api.py tests/test_mcp_access.py -q`
Expected: FAIL.

- [ ] **Step 3: Chat API**

In `backend/app/api/chat.py`:
- imports: add `from app.access import CHAT_USE, Policy, get_policy, require_capability` and
  `from app.atlas import AtlasCaller, AtlasTools`;
- the router requires the chat capability on every route:

```python
router = APIRouter(
    prefix="/api/v1/chat",
    tags=["chat"],
    dependencies=[Depends(require_capability(CHAT_USE))],
)
```

- in `create_session`, delete the `user_uid=str(principal.user_id),` line;
- `send_message` gains a `policy: Policy = Depends(get_policy),` parameter (after `principal`), and
  its stream builds the caller's tools:

```python
        async with get_session_factory()() as stream_db:
            caller = AtlasCaller(
                user_id=principal.user_id,
                auth_method=principal.auth_method,
                surface="chat",
                session_id=session_id,
            )
            tools = AtlasTools(caller, policy, db=stream_db)
            async for event in run_chat_turn(
                tools=tools,
                content=body.content,
                history=history,
                db=stream_db,
            ):
```

- [ ] **Step 4: Insights**

Replace `backend/app/insights/dependencies.py` with:

```python
"""FastAPI wiring for insights: the service runs as the caller, under their policy.

Kept out of router.py so the router never imports a database type (ARCHITECTURE §2.2).
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Policy, get_policy
from app.atlas import AtlasCaller, AtlasTools
from app.database import get_db
from app.identity import Principal, get_principal
from app.insights.service import InsightsService


def get_insights_service(
    principal: Principal = Depends(get_principal),
    policy: Policy = Depends(get_policy),
    db: AsyncSession = Depends(get_db),
) -> InsightsService:
    """Scope comes from the token (guardrail #4); every call is audited as "api"."""
    caller = AtlasCaller(
        user_id=principal.user_id, auth_method=principal.auth_method, surface="api"
    )
    return InsightsService(AtlasTools(caller, policy, db=db))
```

In `backend/app/insights/router.py`: import `from app.access import CHAT_USE, require_capability`
and declare the router as
`APIRouter(prefix="/api/v1/atlas", tags=["insights"], dependencies=[Depends(require_capability(CHAT_USE))])`.

In `backend/app/insights/service.py` (`overview`): replace
`metrics = self._tools.registry.metrics` with `metrics = self._tools.visible_metrics()`.

- [ ] **Step 5: MCP (decision D4)**

In `backend/app/mcp/server.py`:
- replace the module docstring's auth sentence with: "Auth until phase 4: the shared
  ATLAS_MCP_TOKEN is required (no token = MCP off), and every call runs as the MCP service user
  (MCP_SERVICE_EMAIL) under that user's grants.";
- imports: add `import hmac`, `from app.access import MCP_USE, PolicyUnavailableError, policy_for`,
  `from app.atlas import AtlasCaller, AtlasTools` (replacing the old `AtlasTools` import) and
  `from app.identity import service_principal`;
- replace `_run` with `run_tool` and its messages, and update every tool function to call
  `run_tool(...)` instead of `_run(...)`:

```python
NOT_READY = {"error": "MCP isn't set up on this server yet. Ask an atlas admin."}
NO_MCP_ACCESS = {"error": "This MCP connection's account doesn't include MCP access."}
UNAVAILABLE = {"error": "The access check is unavailable right now. Try again shortly."}


async def run_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one atlas tool as the MCP service user, under its policy (fail closed)."""
    async with get_session_factory()() as db:
        principal = await service_principal(db, get_settings().mcp_service_email)
        if principal is None:
            return dict(NOT_READY)
        try:
            policy = await policy_for(db, principal)
        except PolicyUnavailableError:
            return dict(UNAVAILABLE)
        if not policy.has(MCP_USE):
            return dict(NO_MCP_ACCESS)
        caller = AtlasCaller(
            user_id=principal.user_id,
            auth_method=principal.auth_method,
            surface="mcp",
        )
        return await AtlasTools(caller, policy, db=db).execute(tool, arguments)
```

- replace `BearerTokenMiddleware.dispatch` with:

```python
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        expected = get_settings().atlas_mcp_token
        if not expected:
            return JSONResponse(
                {"error": "MCP is off on this server (ATLAS_MCP_TOKEN is not set)."},
                status_code=503,
            )
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
```

- [ ] **Step 6: Retire the shim**

```bash
git rm -r backend/app/middleware backend/tests/test_middleware_shim.py
grep -rn "app.middleware" backend/app backend/tests || echo "no users left"
```

Expected: `no users left`.

- [ ] **Step 7: Run the whole backend suite**

Run: `uv run ruff format app tests && uv run pytest -q`
Expected: everything passes. If an old test still builds `ChatSession(user_uid=...)` or
`AtlasTools(user_uid=...)`, move it to `user_id=` / `make_tools(...)`.

- [ ] **Step 8: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "feat(api): chat, insights and MCP run under the caller's policy; shim removed"
```

---

### Task 15: Evals run under a policy; an honest-denial golden

**Files:**
- Modify: `evals/run_evals.py`, `evals/goldens/core_metrics.yaml`

- [ ] **Step 1: Add the golden (spec §13)**

Append to `evals/goldens/core_metrics.yaml`, and document the new field in its header comment
(`#   allow:               resource patterns the eval user may see (default ["*"])`):

```yaml
- id: denied-funnel-is-honest
  question: "How did the checkout funnel convert over the last 7 full days?"
  allow: ["demo/order/*"]
  expect_no_numbers: true
  expect_any: ["access", "admin"]
```

- [ ] **Step 2: Run each golden under its own policy**

In `evals/run_evals.py`:
- imports: add `from datetime import UTC, datetime`, `from uuid import UUID, uuid4`,
  `from app.access import GrantFacts, Policy, PolicyInputs, UserFacts, evaluate`,
  `from app.atlas import AtlasCaller, AtlasTools`, `from app.identity import ensure_service_user`;
- add above `_run_question`:

```python
EVAL_EMAIL = "evals@yougotagift.com"


def _policy(user_id: UUID, golden: Golden) -> Policy:
    """The eval user sees what the golden allows (default: everything)."""
    grants = [
        GrantFacts(uuid4(), "user", user_id, "allow", "resource", pattern, None)
        for pattern in golden.get("allow", ["*"])
    ]
    inputs = PolicyInputs(
        user=UserFacts(user_id, "viewer", "active", "ygg"),
        groups={},
        memberships={},
        grants=grants,
        policy_version=0,
    )
    return evaluate(inputs, datetime.now(UTC))
```

- replace `_run_question` with:

```python
async def _run_question(golden: Golden) -> Turn:
    async with get_session_factory()() as db:
        user = await ensure_service_user(db, EVAL_EMAIL, "Eval runner", "viewer")
        session = ChatSession(user_id=user.id, user_email=EVAL_EMAIL)
        db.add(session)
        await db.commit()
        await db.refresh(session)

        caller = AtlasCaller(
            user_id=user.id,
            auth_method="service",
            surface="chat",
            session_id=session.id,
        )
        tools = AtlasTools(caller, _policy(user.id, golden), db=db)
        turn = Turn()
        async for event in run_chat_turn(tools, golden["question"], [], db):
            _record(turn, event)
        return turn
```

- in `main`, call `turn = await _run_question(golden)`.

- [ ] **Step 3: Check and run**

Run: `cd backend && uv run ruff check ../evals && uv run pyright ../evals`
Expected: clean.

Run (needs `OPENAI_API_KEY` and a migrated, demo-seeded database):
`cd backend && uv run python ../evals/run_evals.py`
Expected: every golden passes, including `denied-funnel-is-honest`. If no key or database is
available, record that in the PR description; do not skip silently.

- [ ] **Step 4: Commit**

```bash
git add evals
git commit -m "test(evals): goldens run under a policy; honest-denial golden"
```

---

### Task 16: Contracts, strict typing, docs, `make dev-access`

**Files:**
- Modify: `backend/pyproject.toml`, `ARCHITECTURE.md`, `README.md`, `CLAUDE.md`,
  `backend/.env.example`, `Makefile`

- [ ] **Step 1: Import contracts and strict typing**

In `backend/pyproject.toml`:
- `[tool.pyright]`: `strict = ["app/insights", "app/identity", "app/access"]`;
- in the "Source plugins are leaves" contract replace `"app.middleware", "app.identity",` with
  `"app.identity", "app.access",`;
- replace the "Platform modules never depend on features" forbidden list with:

```toml
forbidden_modules = [
    "app.main", "app.api", "app.mcp", "app.insights", "app.agent", "app.atlas",
    "app.sources", "app.identity", "app.access",
]
```

- replace the "Agent and atlas never use HTTP-layer auth" contract with:

```toml
[[tool.importlinter.contracts]]
name = "Agent and atlas never import identity or access (they get a policy)"
type = "forbidden"
source_modules = ["app.agent", "app.atlas"]
forbidden_modules = ["app.identity", "app.access"]
```

- in "Identity depends only on platform modules", replace `"app.middleware",` with
  `"app.access",`;
- add:

```toml
[[tool.importlinter.contracts]]
name = "Access depends only on identity and platform modules"
type = "forbidden"
source_modules = ["app.access"]
forbidden_modules = [
    "app.main", "app.api", "app.mcp", "app.insights", "app.agent", "app.atlas",
    "app.sources",
]

[[tool.importlinter.contracts]]
name = "Access module layering (ARCHITECTURE.md §2.2)"
type = "layers"
containers = ["app.access"]
layers = [
    "router | cli",
    "dependencies",
    "admin",
    "service | startup",
    "repository",
    "models",
    "schemas",
    "cache | evaluator",
    "policy",
    "catalog | patterns | facts | errors",
]
```

Run: `uv run lint-imports && uv run pyright`
Expected: all contracts kept; 0 errors. Fix the code, never the contract. (Likely strict findings:
`model_dump` results typed `dict[str, Any]` already; `Row` unpacking in `list_members` may need
`.tuples()`.)

- [ ] **Step 2: Environment and Makefile**

`backend/.env.example`, after `ATLAS_MCP_TOKEN=`:

```bash
# MCP is off unless ATLAS_MCP_TOKEN is set. Until per-user MCP auth (phase 4),
# MCP calls run as this service user, under its own grants.
MCP_SERVICE_EMAIL=mcp-shared@atlas.internal
```

`Makefile`: add `dev-access` to `.PHONY` and, after `migrate`:

```make
dev-access: ## Local dev: give the dev user every resource (sign in once first)
	cd backend && uv run python -m app.access.cli grant user:dev@yougotagift.com allow '*' --reason "local development"
```

- [ ] **Step 3: Architecture and developer docs**

`ARCHITECTURE.md` §2.1: replace the identity line of the diagram with

```
identity: app.identity (who is calling)     access: app.access (what they may do and see)
          both depend only on platform; access may use identity; agent/atlas use neither
```

and replace the two identity rows of the rule table with:

```
| Identity imports only platform modules | "Identity depends only on platform modules" |
| Access imports only identity and platform modules | "Access depends only on identity and platform modules" |
| Agent and atlas take a policy object, never identity or access | "Agent and atlas never import identity or access" |
| Identity and access follow the §2.2 anatomy | "Identity module layering", "Access module layering" |
```

`ARCHITECTURE.md` §6: delete the `app.middleware` shim row and the `chat_sessions.user_uid` row;
replace the `atlas_audit_log.user_uid` row with

```
| `atlas_audit_log.user_uid` is a legacy text owner key (the log is append-only); `user_id` is the real owner since migration 0003 | Stop writing `user_uid` once nothing reads it |
| MCP uses one shared token and one service user | Per-user OAuth and PATs in auth phase 4 |
```

and update the strict row to `` `[tool.pyright].strict` covers new modules (`insights`, `identity`, `access`) ``.

`README.md`, in "Sign-in" (deployment section), add:

```markdown
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
```

`CLAUDE.md` "Development" (backend block), after the alembic lines:

```bash
make dev-access                    # local dev: grant the dev user all data (no admin bypass)
```

and extend guardrail 4 with one sentence: "Data access is evaluated server-side from groups and
grants (`backend/app/access`); the agent and atlas only ever receive the evaluated policy."

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/.env.example Makefile ARCHITECTURE.md README.md CLAUDE.md
git commit -m "chore(access): contracts, strict typing, docs and make dev-access"
```

---

### Task 17: Full gate, review, deploy

- [ ] **Step 1: The full gate**

Run (repo root): `make check`
Expected: exit 0. Backend and frontend green, coverage ≥ 80%, 9 import contracts kept.

- [ ] **Step 2: Migrations on PostgreSQL**

```bash
docker run -d --rm --name atlas-p2-pg -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \
  -e POSTGRES_DB=scratch -p 5434:5432 postgres:16-alpine
cd backend && TEST_PG_URL=postgresql+asyncpg://atlas:atlas@localhost:5434/scratch \
  uv run pytest tests/test_alembic_postgres.py -q
docker stop atlas-p2-pg
```

Expected: 2 passed (`compare_metadata == []` on head, including the access tables).

- [ ] **Step 3: Production code review**

Follow `.claude/skills/production-code-review/SKILL.md` against `origin/main...HEAD`. Give the
reviewer these focus points: fail-closed paths (policy unavailable, unknown user, unknown role or
capability, unknown effect); deny-wins and inheritance; every write bumping the version in the same
commit; no data reachable without a policy (chat, insights, MCP, evals); manager limits (D8);
tenant checks; SQL only through bound parameters. Fix every blocking finding, re-run
`make check`, and record the verdict in the PR description.

- [ ] **Step 4: Open the PR**

Push `feature/auth-policy` and open a PR to `main` that lists decisions D1–D8, the deploy steps
below, and the verification results.

- [ ] **Step 5: Deploy (only with the user's go-ahead)**

On EC2 (`ssh atlas`, repo in `~/ygg-atlas`), after the PR is merged:

1. Pre-check: `docker compose exec -T postgres psql -U atlas -d ygg_atlas -Atc "SELECT count(*) FROM chat_sessions WHERE user_id IS NULL"`
   must print `0` (migration 0003 refuses otherwise).
2. Back up: `docker compose exec -T postgres pg_dump -U atlas ygg_atlas | gzip > ~/atlas-backups/ygg_atlas-$(date -u +%Y%m%dT%H%M%SZ).sql.gz`.
3. Sync the code (the README rsync command) and run `docker compose up -d --build backend`.
   The container runs migration 0003 before starting.
4. Give the admins access (decision D2):

```bash
docker compose exec backend uv run --no-dev python -m app.access.cli add-member ashik@yougotagift.com atlas-admins --manager
docker compose exec backend uv run --no-dev python -m app.access.cli grant group:atlas-admins allow '*' --reason "bootstrap: atlas admins see all data"
docker compose exec backend uv run --no-dev python -m app.access.cli access ashik@yougotagift.com
```

5. Verify through the tunnel (`http://localhost:8080`): `/api/v1/me/access` shows
   `has_data_access: true` for the admin; a question in chat returns numbers with provenance; a
   colleague without grants gets an honest "no access yet" answer; `rbac_changes` has the CLI rows.
6. Tell session `ygg-atlas-8b` that `feature/auth-policy` is deployed (chat sessions no longer carry
   `user_uid`; the dashboard needs `chat:use` and shows only granted metrics).

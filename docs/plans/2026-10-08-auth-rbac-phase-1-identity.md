# Auth & RBAC Phase 1: Identity Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Before writing any code, follow `.claude/skills/engineering-standards/SKILL.md`; before
> calling a task done, `make check` must be green.

**Goal:** Every request to atlas resolves to a real, database-backed `Principal` (Google sign-in via
Firebase, auto-provisioned with no data access), schema changes move to Alembic, and chat sessions are
owned by atlas user ids.

**Architecture:** A new self-contained module `app/identity` (router → dependencies/bootstrap →
service/firebase → repository → models → schemas → principal/tokens/errors), enforced by an
import-linter layers contract. `get_principal` replaces `app.middleware.get_current_user`, which stays as
a thin deprecated shim so in-flight Hybrid Glass branches keep working. Alembic owns the schema with an
idempotent baseline (existing deployments upgrade in place).

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, firebase-admin, pytest + httpx, ruff,
pyright (strict for `app/identity`), import-linter.

**Spec:** `docs/specs/2026-10-08-auth-rbac-design.md` §3 (authentication), §7 (`users`), §11 steps 1 and 3,
§12, §14 phase 1. Later phases (policy, row/field, MCP auth, admin UI) get their own plans.

**Working directory:** worktree `/Users/ashikbabu/Projects/ygg-atlas-wt-auth`, branch
`feature/auth-identity`, based on `feature/hybrid-glass` @ `47a7200` (Hybrid Glass wave 1: answer
blocks, insights, glass shell). All backend commands run from `backend/`.

**Coordination (Hybrid Glass):** this branch builds on wave 1, so it merges to `main` after (or
together with) `feature/hybrid-glass`. Keep wave 1's work intact: `app.insights` (router, contracts,
strict typing), `ChatMessage.blocks`, the agent `Toolset`. `app.insights.dependencies` still imports
`app.middleware.get_current_user`; the shim in Task 11 keeps it working unchanged. Wave 2 is
frontend-only. Do not edit `app/agent/`, `app/insights/` or `tests/test_agent_loop.py` in this phase.

---

## File map

| File | Responsibility |
|---|---|
| `backend/app/config.py` (modify) | `environment`, `bootstrap_admins`, `session_max_age_hours`, production guard |
| `backend/app/identity/__init__.py` | Public interface: `Principal`, `get_principal`, `identity_router`, `bootstrap_admins` |
| `backend/app/identity/principal.py` | `Principal` dataclass (the authenticated caller) |
| `backend/app/identity/tokens.py` | `VerifiedToken`, `TokenVerifier` protocol, `InvalidTokenError` |
| `backend/app/identity/errors.py` | `UnauthenticatedError` (401), `ForbiddenError` (403) |
| `backend/app/identity/models.py` | `User` table, `UserStatus`, `UserKind` |
| `backend/app/identity/schemas.py` | `MeOut` response |
| `backend/app/identity/repository.py` | `UserRepository`: all `users` DB access |
| `backend/app/identity/service.py` | `IdentityService`: web principal resolution, dev user, disable |
| `backend/app/identity/firebase.py` | `FirebaseVerifier`: the only firebase_admin adapter |
| `backend/app/identity/dependencies.py` | FastAPI wiring: `get_principal`, `get_token_verifier`, `get_identity_service` |
| `backend/app/identity/bootstrap.py` | `bootstrap_admins`: idempotent admin creation at startup |
| `backend/app/identity/router.py` | `GET /api/v1/me` |
| `backend/app/middleware/__init__.py` (rewrite) | Deprecated shim: `AuthUser`, `get_current_user` over `get_principal` |
| `backend/app/middleware/firebase_auth.py` (delete) | Replaced by `identity/firebase.py` + `identity/dependencies.py` |
| `backend/app/models/chat.py` (modify) | `ChatSession.user_id` FK |
| `backend/app/api/chat.py` (modify) | Ownership and listing by `principal.user_id` |
| `backend/app/main.py` (modify) | No more `create_all`; bootstrap admins; mount `/api/v1/me` |
| `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako` | Alembic setup (async) |
| `backend/migrations/versions/0001_baseline.py` | Idempotent baseline of today's three tables, including `chat_messages.blocks` |
| `backend/migrations/versions/0002_users.py` | `users` table, `chat_sessions.user_id`, backfill |
| `backend/app/models/migrations.py`, `backend/tests/test_migrations.py` (delete) | Track C's temporary `ensure_blocks_column`, superseded by the baseline (spec §11.1) |
| `backend/tests/identity/…` | Unit and API tests for the module |
| `backend/tests/test_alembic.py` | Upgrade from empty DB, upgrade over legacy data, drift check |
| `backend/.dockerignore`, `frontend/.dockerignore` | Keep `.env*` (secrets, auth bypass) out of images |
| `backend/Dockerfile`, `Makefile`, `backend/.env.example`, `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `backend/pyproject.toml` | Wiring, contracts and docs |

---

### Task 1: Settings — environment, bootstrap admins, session age, production guard

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_config.py
"""Settings invariants that protect production."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_auth_bypass_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        Settings(_env_file=None, environment="production", auth_disabled=True)


def test_auth_bypass_allowed_in_development() -> None:
    settings = Settings(_env_file=None, environment="development", auth_disabled=True)
    assert settings.auth_disabled


def test_bootstrap_admins_are_normalised() -> None:
    settings = Settings(
        _env_file=None, bootstrap_admins=" Ashik@YouGotAGift.com, ,ops@yougotagift.com "
    )
    assert settings.bootstrap_admin_list == [
        "ashik@yougotagift.com",
        "ops@yougotagift.com",
    ]


def test_session_max_age_defaults_to_24_hours() -> None:
    assert Settings(_env_file=None).session_max_age_hours == 24
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`environment`, `bootstrap_admin_list`, `session_max_age_hours` don't exist).

- [ ] **Step 3: Implement**

In `backend/app/config.py`, change the imports and add the fields, property and validator:

```python
from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Add inside `class Settings`, directly after `auth_disabled: bool = False`:

```python
    environment: Literal["development", "test", "production"] = "development"
    # Comma-separated emails made admin at startup (idempotent). Spec §3.3.
    bootstrap_admins: str = ""
    # Web sessions are capped server-side from the token's auth_time. Spec §3.1.
    session_max_age_hours: int = 24
```

Add after the `cors_origin_list` property:

```python
    @property
    def bootstrap_admin_list(self) -> list[str]:
        return [
            e.strip().lower() for e in self.bootstrap_admins.split(",") if e.strip()
        ]

    @model_validator(mode="after")
    def _forbid_auth_bypass_in_production(self) -> Self:
        if self.environment == "production" and self.auth_disabled:
            msg = "AUTH_DISABLED=true is not allowed when ENVIRONMENT=production"
            raise ValueError(msg)
        return self
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): environment, bootstrap admins, session age, production auth guard"
```

---

### Task 2: Identity value types — Principal, tokens, errors

**Files:**
- Create: `backend/app/identity/principal.py`, `backend/app/identity/tokens.py`, `backend/app/identity/errors.py`
- Test: `backend/tests/identity/__init__.py` (empty), `backend/tests/identity/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/identity/test_types.py
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.identity.principal import Principal
from app.identity.tokens import VerifiedToken


def test_principal_is_immutable() -> None:
    principal = Principal(
        user_id=uuid4(),
        email="a@yougotagift.com",
        display_name="A",
        role="viewer",
        kind="human",
        tenant="ygg",
        auth_method="web",
    )
    with pytest.raises(FrozenInstanceError):
        principal.role = "admin"  # type: ignore[misc]


def test_verified_token_fields() -> None:
    token = VerifiedToken(
        uid="fb-1", email="a@yougotagift.com", email_verified=True, name="A", auth_time=1
    )
    assert token.email == "a@yougotagift.com"
```

Note: the `# type: ignore[misc]` is required for the test to assign to a frozen field on purpose.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/identity/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.identity'`.

- [ ] **Step 3: Implement**

```python
# backend/app/identity/principal.py
"""The authenticated caller of one request. Built only by the identity service."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

AuthMethod = Literal["web", "oauth", "pat", "service", "dev"]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    email: str
    display_name: str
    role: str
    kind: str
    tenant: str
    auth_method: AuthMethod
```

```python
# backend/app/identity/tokens.py
"""Token verification contract. Implemented by identity.firebase; faked in tests."""

from dataclasses import dataclass
from typing import Protocol


class InvalidTokenError(Exception):
    """The bearer token is malformed, expired, revoked or not for this project."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    uid: str
    email: str
    email_verified: bool
    name: str
    auth_time: int  # epoch seconds of the original sign-in


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedToken: ...

    async def revoke(self, firebase_uid: str) -> None: ...
```

```python
# backend/app/identity/errors.py
"""Identity failures, mapped to HTTP status codes by identity.dependencies."""


class UnauthenticatedError(Exception):
    """401: the caller is not (or no longer) signed in."""


class ForbiddenError(Exception):
    """403: the caller is known but may not use atlas."""
```

Create an empty `backend/app/identity/__init__.py` for now (filled in Task 8) and an empty
`backend/tests/identity/__init__.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/identity/test_types.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity backend/tests/identity
git commit -m "feat(identity): Principal, token and error types"
```

---

### Task 3: `users` table and repository

**Files:**
- Create: `backend/app/identity/models.py`, `backend/app/identity/repository.py`
- Modify: `backend/tests/conftest.py` (register identity tables for `create_all`)
- Test: `backend/tests/identity/test_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/identity/test_repository.py
from app.identity.models import User, UserStatus
from app.identity.repository import UserRepository


async def test_save_and_lookup_by_email_and_firebase_uid(db) -> None:
    users = UserRepository(db)
    saved = await users.save(User(email="sara@yougotagift.com", firebase_uid="fb-sara"))

    assert (await users.get(saved.id)) is not None
    assert (await users.get_by_email("SARA@yougotagift.com")).id == saved.id
    assert (await users.get_by_firebase_uid("fb-sara")).id == saved.id
    assert saved.status == UserStatus.ACTIVE
    assert saved.role == "viewer"
    assert saved.tenant == "ygg"


async def test_lookups_return_none_when_missing(db) -> None:
    users = UserRepository(db)
    assert await users.get_by_email("nobody@yougotagift.com") is None
    assert await users.get_by_firebase_uid("fb-none") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/identity/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.identity.models'`.

- [ ] **Step 3: Implement the model**

```python
# backend/app/identity/models.py
"""The users table: one row per human or service identity (spec §7)."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP
from sqlmodel import Field, SQLModel

DEFAULT_ROLE = "viewer"
DEFAULT_TENANT = "ygg"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class UserKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    firebase_uid: str | None = Field(
        default=None, unique=True, index=True, max_length=128
    )
    display_name: str = Field(default="", max_length=200)
    status: str = Field(default=UserStatus.ACTIVE, max_length=16)
    kind: str = Field(default=UserKind.HUMAN, max_length=16)
    role: str = Field(default=DEFAULT_ROLE, max_length=32)
    owner_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    tenant: str = Field(default=DEFAULT_TENANT, max_length=64)
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    last_seen_at: datetime | None = Field(
        default=None, sa_type=TIMESTAMP(timezone=True)
    )
```

- [ ] **Step 4: Implement the repository**

```python
# backend/app/identity/repository.py
"""All database access for users. No business decisions here."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.identity.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.firebase_uid) == firebase_uid)
        )
        return result.scalar_one_or_none()

    async def save(self, user: User) -> User:
        user.email = user.email.strip().lower()
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        return user
```

- [ ] **Step 5: Register identity tables in the test schema**

`ChatSession.user_id` (Task 10) references `users.id`, so `create_all` must always see the `users`
table. In `backend/tests/conftest.py`, add after the existing `from app.database import …` line:

```python
import app.identity.models  # noqa: F401  # registers the users table for create_all
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/identity/test_repository.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/identity/models.py backend/app/identity/repository.py \
  backend/tests/identity/test_repository.py backend/tests/conftest.py
git commit -m "feat(identity): users table and repository"
```

---

### Task 4: Identity service — web principal resolution

**Files:**
- Create: `backend/app/identity/service.py`
- Test: `backend/tests/identity/test_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/identity/test_service.py
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.identity.errors import ForbiddenError, UnauthenticatedError
from app.identity.models import User, UserStatus
from app.identity.repository import UserRepository
from app.identity.service import IdentityService
from app.identity.tokens import VerifiedToken

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _token(
    email: str = "sara@yougotagift.com",
    uid: str = "fb-sara",
    verified: bool = True,
    signed_in: datetime = NOW - timedelta(hours=1),
) -> VerifiedToken:
    return VerifiedToken(
        uid=uid,
        email=email,
        email_verified=verified,
        name="Sara Ali",
        auth_time=int(signed_in.timestamp()),
    )


def _service(db) -> IdentityService:
    settings = Settings(_env_file=None, allowed_email_domain="yougotagift.com")
    return IdentityService(UserRepository(db), settings, clock=lambda: NOW)


async def test_first_sign_in_creates_viewer_with_no_extra_rights(db) -> None:
    principal = await _service(db).resolve_web(_token())

    assert principal.email == "sara@yougotagift.com"
    assert principal.role == "viewer"
    assert principal.auth_method == "web"
    stored = await UserRepository(db).get(principal.user_id)
    assert stored.firebase_uid == "fb-sara"
    assert stored.display_name == "Sara Ali"


async def test_second_sign_in_reuses_the_same_user(db) -> None:
    first = await _service(db).resolve_web(_token())
    second = await _service(db).resolve_web(_token())
    assert first.user_id == second.user_id


async def test_pre_created_user_is_linked_by_email(db) -> None:
    users = UserRepository(db)
    pre = await users.save(User(email="sara@yougotagift.com", role="admin"))

    principal = await _service(db).resolve_web(_token())

    assert principal.user_id == pre.id
    assert principal.role == "admin"
    assert (await users.get(pre.id)).firebase_uid == "fb-sara"


async def test_other_domain_is_forbidden(db) -> None:
    with pytest.raises(ForbiddenError, match="@yougotagift.com"):
        await _service(db).resolve_web(_token(email="x@gmail.com"))


async def test_unverified_email_is_forbidden(db) -> None:
    with pytest.raises(ForbiddenError):
        await _service(db).resolve_web(_token(verified=False))


async def test_session_older_than_24h_must_sign_in_again(db) -> None:
    old = _token(signed_in=NOW - timedelta(hours=25))
    with pytest.raises(UnauthenticatedError, match="Sign in again"):
        await _service(db).resolve_web(old)


async def test_disabled_user_is_forbidden(db) -> None:
    await UserRepository(db).save(
        User(email="sara@yougotagift.com", status=UserStatus.DISABLED)
    )
    with pytest.raises(ForbiddenError, match="disabled"):
        await _service(db).resolve_web(_token())


async def test_last_seen_is_recorded(db) -> None:
    principal = await _service(db).resolve_web(_token())
    stored = await UserRepository(db).get(principal.user_id)
    assert stored.last_seen_at is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/identity/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.identity.service'`.

- [ ] **Step 3: Implement**

```python
# backend/app/identity/service.py
"""Identity use cases: who is calling, and may they use atlas at all.

Data access goes through UserRepository; nothing here knows about HTTP.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog

from app.config import Settings
from app.identity.errors import ForbiddenError, UnauthenticatedError
from app.identity.models import User, UserStatus
from app.identity.principal import AuthMethod, Principal
from app.identity.repository import UserRepository
from app.identity.tokens import VerifiedToken

logger = structlog.get_logger()

LAST_SEEN_INTERVAL = timedelta(minutes=5)
DEV_ROLE = "admin"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every stored timestamp is UTC (CLAUDE.md)."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def to_principal(user: User, auth_method: AuthMethod) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        kind=user.kind,
        tenant=user.tenant,
        auth_method=auth_method,
    )


class IdentityService:
    def __init__(
        self,
        users: UserRepository,
        settings: Settings,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._users = users
        self._settings = settings
        self._clock = clock

    async def resolve_web(self, token: VerifiedToken) -> Principal:
        """Turn a verified Google sign-in into a Principal, creating the user once."""
        self._check_domain(token)
        self._check_session_age(token)
        user = await self._find_or_create(token)
        if user.status != UserStatus.ACTIVE:
            logger.warning("identity.disabled_user", user_id=str(user.id))
            msg = "Your atlas access is disabled. Contact an admin."
            raise ForbiddenError(msg)
        await self._touch(user)
        return to_principal(user, "web")

    def _check_domain(self, token: VerifiedToken) -> None:
        domain = self._settings.allowed_email_domain.lower()
        if not token.email_verified or not token.email.endswith(f"@{domain}"):
            logger.warning("identity.domain_rejected")
            msg = f"Use your @{domain} account."
            raise ForbiddenError(msg)

    def _check_session_age(self, token: VerifiedToken) -> None:
        signed_in = datetime.fromtimestamp(token.auth_time, tz=UTC)
        max_age = timedelta(hours=self._settings.session_max_age_hours)
        if self._clock() - signed_in > max_age:
            msg = "Your session has expired. Sign in again."
            raise UnauthenticatedError(msg)

    async def _find_or_create(self, token: VerifiedToken) -> User:
        user = await self._users.get_by_firebase_uid(token.uid)
        if user is not None:
            return user
        user = await self._users.get_by_email(token.email)
        if user is None:
            user = User(email=token.email, display_name=token.name)
            logger.info("identity.user_created", email_domain=token.email.split("@")[1])
        user.firebase_uid = token.uid
        if not user.display_name:
            user.display_name = token.name
        return await self._users.save(user)

    async def _touch(self, user: User) -> None:
        now = self._clock()
        last = user.last_seen_at
        if last is None or now - _as_utc(last) >= LAST_SEEN_INTERVAL:
            user.last_seen_at = now
            await self._users.save(user)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/identity/test_service.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/service.py backend/tests/identity/test_service.py
git commit -m "feat(identity): resolve web principals (domain, 24h session, status, provisioning)"
```

---

### Task 5: Dev principal and disabling users

**Files:**
- Modify: `backend/app/identity/service.py`
- Test: `backend/tests/identity/test_service_admin.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/identity/test_service_admin.py
from app.config import Settings
from app.identity.models import User, UserStatus
from app.identity.repository import UserRepository
from app.identity.service import IdentityService
from app.identity.tokens import VerifiedToken


class RecordingVerifier:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    async def verify(self, token: str) -> VerifiedToken:
        raise AssertionError("not used")

    async def revoke(self, firebase_uid: str) -> None:
        self.revoked.append(firebase_uid)


def _service(db) -> IdentityService:
    return IdentityService(UserRepository(db), Settings(_env_file=None))


async def test_dev_user_is_created_once_as_admin(db) -> None:
    first = await _service(db).ensure_dev_user()
    second = await _service(db).ensure_dev_user()

    assert first.user_id == second.user_id
    assert first.email == "dev@yougotagift.com"
    assert first.role == "admin"
    assert first.auth_method == "dev"


async def test_disable_user_blocks_and_revokes_firebase_sessions(db) -> None:
    user = await UserRepository(db).save(
        User(email="sara@yougotagift.com", firebase_uid="fb-sara")
    )
    verifier = RecordingVerifier()

    disabled = await _service(db).disable_user(user.id, verifier)

    assert disabled.status == UserStatus.DISABLED
    assert verifier.revoked == ["fb-sara"]


async def test_disable_user_without_firebase_link_skips_revocation(db) -> None:
    user = await UserRepository(db).save(User(email="svc@yougotagift.com"))
    verifier = RecordingVerifier()

    await _service(db).disable_user(user.id, verifier)

    assert verifier.revoked == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/identity/test_service_admin.py -v`
Expected: FAIL with `AttributeError: 'IdentityService' object has no attribute 'ensure_dev_user'`.

- [ ] **Step 3: Implement**

In `backend/app/identity/service.py`, add to the imports:

```python
from uuid import UUID

from app.identity.tokens import TokenVerifier, VerifiedToken
```

(replace the existing `from app.identity.tokens import VerifiedToken` line), and add these methods to
`IdentityService` after `resolve_web`:

```python
    async def ensure_dev_user(self) -> Principal:
        """Local development only (AUTH_DISABLED): one admin user, created once."""
        email = f"dev@{self._settings.allowed_email_domain.lower()}"
        user = await self._users.get_by_email(email)
        if user is None:
            user = await self._users.save(
                User(email=email, display_name="Dev User", role=DEV_ROLE)
            )
        return to_principal(user, "dev")

    async def disable_user(self, user_id: UUID, verifier: TokenVerifier) -> User:
        """Block the user on the next request and end their Firebase sessions."""
        user = await self._users.get(user_id)
        if user is None:
            msg = f"No user {user_id}"
            raise LookupError(msg)
        user.status = UserStatus.DISABLED
        user = await self._users.save(user)
        if user.firebase_uid:
            await verifier.revoke(user.firebase_uid)
        logger.info("identity.user_disabled", user_id=str(user.id))
        return user
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/identity -v`
Expected: all identity tests pass (2 + 2 + 8 + 3).

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/service.py backend/tests/identity/test_service_admin.py
git commit -m "feat(identity): dev principal and disable-with-revocation"
```

---

### Task 6: Firebase adapter

**Files:**
- Create: `backend/app/identity/firebase.py`
- Test: `backend/tests/identity/test_firebase.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/identity/test_firebase.py
"""The adapter maps firebase_admin results and failures without network calls."""

import pytest
from firebase_admin import auth as fb_auth

from app.identity import firebase
from app.identity.tokens import InvalidTokenError


async def test_verify_maps_claims(monkeypatch) -> None:
    def fake_verify(token: str, app: object) -> dict[str, object]:
        assert token == "good"
        return {
            "uid": "fb-1",
            "email": "Sara@YouGotAGift.com",
            "email_verified": True,
            "name": "Sara",
            "auth_time": 1_700_000_000,
        }

    monkeypatch.setattr(fb_auth, "verify_id_token", fake_verify)
    monkeypatch.setattr(firebase, "_app", lambda project_id: object())

    token = await firebase.FirebaseVerifier("proj").verify("good")

    assert token.uid == "fb-1"
    assert token.email == "sara@yougotagift.com"
    assert token.email_verified is True
    assert token.auth_time == 1_700_000_000


async def test_verify_turns_sdk_errors_into_invalid_token(monkeypatch) -> None:
    def fake_verify(token: str, app: object) -> dict[str, object]:
        raise ValueError("malformed")

    monkeypatch.setattr(fb_auth, "verify_id_token", fake_verify)
    monkeypatch.setattr(firebase, "_app", lambda project_id: object())

    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier("proj").verify("bad")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/identity/test_firebase.py -v`
Expected: FAIL with `ImportError: cannot import name 'firebase'`.

- [ ] **Step 3: Implement**

```python
# backend/app/identity/firebase.py
# pyright: basic
# Adapter over the untyped firebase_admin SDK; strict typing stops at this boundary.
"""The only module that talks to Firebase. Blocking SDK calls run in a thread."""

import asyncio
from functools import cache
from typing import Any

import firebase_admin
from firebase_admin import auth as fb_auth

from app.identity.tokens import InvalidTokenError, VerifiedToken


@cache
def _app(project_id: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        options = {"projectId": project_id} if project_id else None
        return firebase_admin.initialize_app(options=options)


class FirebaseVerifier:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def verify(self, token: str) -> VerifiedToken:
        try:
            claims: dict[str, Any] = await asyncio.to_thread(
                fb_auth.verify_id_token, token, _app(self._project_id)
            )
        except (ValueError, fb_auth.InvalidIdTokenError, fb_auth.CertificateFetchError):
            msg = "Invalid or expired token"
            raise InvalidTokenError(msg) from None
        return VerifiedToken(
            uid=str(claims["uid"]),
            email=str(claims.get("email", "")).strip().lower(),
            email_verified=bool(claims.get("email_verified", False)),
            name=str(claims.get("name", "")),
            auth_time=int(claims.get("auth_time", 0)),
        )

    async def revoke(self, firebase_uid: str) -> None:
        await asyncio.to_thread(
            fb_auth.revoke_refresh_tokens, firebase_uid, _app(self._project_id)
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/identity/test_firebase.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/firebase.py backend/tests/identity/test_firebase.py
git commit -m "feat(identity): firebase adapter (threaded SDK calls, typed results)"
```

---

### Task 7: FastAPI wiring — get_principal

**Files:**
- Create: `backend/app/identity/dependencies.py`
- Test: `backend/tests/identity/test_dependencies.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/identity/test_dependencies.py
"""get_principal through a real FastAPI app, with Firebase faked."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.identity.dependencies import get_principal, get_token_verifier
from app.identity.principal import Principal
from app.identity.tokens import InvalidTokenError, VerifiedToken


class FakeVerifier:
    def __init__(self, email: str = "sara@yougotagift.com") -> None:
        self.email = email

    async def verify(self, token: str) -> VerifiedToken:
        if token != "good":
            raise InvalidTokenError("bad")
        return VerifiedToken(
            uid="fb-sara",
            email=self.email,
            email_verified=True,
            name="Sara",
            auth_time=int(datetime.now(UTC).timestamp()),
        )

    async def revoke(self, firebase_uid: str) -> None:
        return None


def _app(auth_disabled: bool, verifier: FakeVerifier) -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(principal: Principal = Depends(get_principal)) -> dict[str, str]:
        return {"email": principal.email, "method": principal.auth_method}

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, auth_disabled=auth_disabled
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    return app


@pytest_asyncio.fixture
async def client_factory(db) -> AsyncIterator[object]:
    clients: list[AsyncClient] = []

    def make(auth_disabled: bool = False, email: str = "sara@yougotagift.com"):
        transport = ASGITransport(app=_app(auth_disabled, FakeVerifier(email)))
        client = AsyncClient(transport=transport, base_url="http://test")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


async def test_valid_token_resolves_principal(client_factory) -> None:
    resp = await client_factory().get("/who", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 200
    assert resp.json() == {"email": "sara@yougotagift.com", "method": "web"}


async def test_missing_token_is_401(client_factory) -> None:
    resp = await client_factory().get("/who")
    assert resp.status_code == 401


async def test_invalid_token_is_401(client_factory) -> None:
    resp = await client_factory().get("/who", headers={"Authorization": "Bearer bad"})
    assert resp.status_code == 401


async def test_wrong_domain_is_403(client_factory) -> None:
    client = client_factory(email="x@gmail.com")
    resp = await client.get("/who", headers={"Authorization": "Bearer good"})
    assert resp.status_code == 403


async def test_auth_disabled_returns_dev_principal(client_factory) -> None:
    resp = await client_factory(auth_disabled=True).get("/who")
    assert resp.json() == {"email": "dev@yougotagift.com", "method": "dev"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/identity/test_dependencies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.identity.dependencies'`.

- [ ] **Step 3: Implement**

```python
# backend/app/identity/dependencies.py
"""FastAPI wiring for identity. Maps identity errors to HTTP status codes."""

from functools import cache

import structlog
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.identity.errors import ForbiddenError, UnauthenticatedError
from app.identity.firebase import FirebaseVerifier
from app.identity.principal import Principal
from app.identity.repository import UserRepository
from app.identity.service import IdentityService
from app.identity.tokens import InvalidTokenError, TokenVerifier

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@cache
def _firebase_verifier(project_id: str) -> FirebaseVerifier:
    return FirebaseVerifier(project_id)


def get_token_verifier(settings: Settings = Depends(get_settings)) -> TokenVerifier:
    return _firebase_verifier(settings.firebase_project_id)


def get_identity_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IdentityService:
    return IdentityService(UserRepository(db), settings)


async def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    verifier: TokenVerifier = Depends(get_token_verifier),
    service: IdentityService = Depends(get_identity_service),
) -> Principal:
    """The single entry point: every route that needs a caller depends on this."""
    if settings.auth_disabled:
        return await service.ensure_dev_user()
    if credentials is None:
        raise HTTPException(401, "Missing bearer token", headers=_CHALLENGE)
    try:
        token = await verifier.verify(credentials.credentials)
    except InvalidTokenError:
        logger.warning("identity.token_invalid")
        raise HTTPException(401, "Invalid or expired token", headers=_CHALLENGE) from None
    try:
        return await service.resolve_web(token)
    except UnauthenticatedError as exc:
        raise HTTPException(401, str(exc), headers=_CHALLENGE) from None
    except ForbiddenError as exc:
        raise HTTPException(403, str(exc)) from None
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/identity/test_dependencies.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity/dependencies.py backend/tests/identity/test_dependencies.py
git commit -m "feat(identity): get_principal dependency with 401/403 mapping"
```

---

### Task 8: Bootstrap admins, `/me`, public interface

**Files:**
- Create: `backend/app/identity/bootstrap.py`, `backend/app/identity/schemas.py`, `backend/app/identity/router.py`
- Modify: `backend/app/identity/__init__.py`
- Test: `backend/tests/identity/test_bootstrap.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/identity/test_bootstrap.py
from app.identity import bootstrap_admins
from app.identity.models import User
from app.identity.repository import UserRepository


async def test_creates_missing_admins_and_upgrades_existing(db) -> None:
    users = UserRepository(db)
    await users.save(User(email="ops@yougotagift.com", role="viewer"))

    changed = await bootstrap_admins(
        db, ["ashik@yougotagift.com", "ops@yougotagift.com"]
    )

    assert changed == 2
    assert (await users.get_by_email("ashik@yougotagift.com")).role == "admin"
    assert (await users.get_by_email("ops@yougotagift.com")).role == "admin"


async def test_is_idempotent(db) -> None:
    await bootstrap_admins(db, ["ashik@yougotagift.com"])
    assert await bootstrap_admins(db, ["ashik@yougotagift.com"]) == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/identity/test_bootstrap.py -v`
Expected: FAIL with `ImportError: cannot import name 'bootstrap_admins' from 'app.identity'`.

- [ ] **Step 3: Implement**

```python
# backend/app/identity/bootstrap.py
"""Startup bootstrap: the only way to create the first admins (spec §3.3)."""

from collections.abc import Iterable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User
from app.identity.repository import UserRepository

logger = structlog.get_logger()

ADMIN_ROLE = "admin"


async def bootstrap_admins(db: AsyncSession, emails: Iterable[str]) -> int:
    """Create or upgrade each email to admin. Returns how many rows changed."""
    users = UserRepository(db)
    changed = 0
    for email in emails:
        user = await users.get_by_email(email)
        if user is None:
            await users.save(User(email=email, role=ADMIN_ROLE))
            changed += 1
        elif user.role != ADMIN_ROLE:
            user.role = ADMIN_ROLE
            await users.save(user)
            changed += 1
    if changed:
        logger.info("identity.bootstrap_admins", changed=changed)
    return changed
```

```python
# backend/app/identity/schemas.py
"""Response shapes for identity routes (separate from the users table)."""

from uuid import UUID

from pydantic import BaseModel

from app.identity.principal import Principal


class MeOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: str
    kind: str
    tenant: str
    auth_method: str

    @classmethod
    def from_principal(cls, principal: Principal) -> "MeOut":
        return cls(
            user_id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            role=principal.role,
            kind=principal.kind,
            tenant=principal.tenant,
            auth_method=principal.auth_method,
        )
```

```python
# backend/app/identity/router.py
"""Identity routes. Thin: resolve the principal, return a schema."""

from fastapi import APIRouter, Depends

from app.identity.dependencies import get_principal
from app.identity.principal import Principal
from app.identity.schemas import MeOut

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(get_principal)) -> MeOut:
    return MeOut.from_principal(principal)
```

```python
# backend/app/identity/__init__.py
"""Identity: who is calling. Other modules import only from here."""

from app.identity.bootstrap import bootstrap_admins
from app.identity.dependencies import get_principal
from app.identity.principal import Principal
from app.identity.router import router as identity_router

__all__ = ["Principal", "bootstrap_admins", "get_principal", "identity_router"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/identity -v`
Expected: all identity tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/identity backend/tests/identity/test_bootstrap.py
git commit -m "feat(identity): bootstrap admins, /me route, public interface"
```

---

### Task 9: Alembic with an idempotent baseline

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`,
  `backend/migrations/versions/0001_baseline.py`
- Test: `backend/tests/test_alembic.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_alembic.py
"""Alembic owns the schema: it must build exactly what the models declare."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).parents[1]


def _config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _tables(sync_url: str) -> set[str]:
    engine = sa.create_engine(sync_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_from_empty_creates_baseline_tables(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "0001")
    assert {"chat_sessions", "chat_messages", "atlas_audit_log"} <= _tables(
        f"sqlite:///{db}"
    )


def test_baseline_is_idempotent_over_existing_tables(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE chat_sessions (id CHAR(32) PRIMARY KEY)"))
        conn.execute(
            sa.text("CREATE TABLE chat_messages (id CHAR(32) PRIMARY KEY, content TEXT)")
        )
    engine.dispose()

    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "0001")

    assert {"chat_sessions", "chat_messages", "atlas_audit_log"} <= _tables(
        f"sqlite:///{db}"
    )
    engine = sa.create_engine(f"sqlite:///{db}")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("chat_messages")}
    engine.dispose()
    assert "blocks" in columns  # pre-Track-C databases gain the answer blocks column
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_alembic.py -v`
Expected: FAIL (no `alembic.ini`).

- [ ] **Step 3: Create Alembic config**

```ini
# backend/alembic.ini
[alembic]
script_location = migrations
prepend_sys_path = .
# The URL comes from app settings (DATABASE_URL) unless a caller sets sqlalchemy.url.

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

```python
# backend/migrations/env.py
"""Alembic environment: async engine, URL from app settings, SQLModel metadata."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

import app.identity.models  # noqa: F401  # registers the users table on the metadata
import app.models  # noqa: F401  # registers chat and audit tables on the metadata
from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
```

```mako
## backend/migrations/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Write the idempotent baseline**

```python
# backend/migrations/versions/0001_baseline.py
"""Baseline: the schema create_all produced before Alembic (chat + audit + blocks).

Idempotent: deployments that already have these tables (from create_all) upgrade
without error, so no manual `alembic stamp` is needed.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _existing()
    if "chat_sessions" not in existing:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_uid", sa.String(), nullable=False),
            sa.Column("user_email", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("created_at", TS, nullable=False),
            sa.Column("updated_at", TS, nullable=False),
        )
        op.create_index("ix_chat_sessions_user_uid", "chat_sessions", ["user_uid"])
    if "chat_messages" not in existing:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Uuid(),
                sa.ForeignKey("chat_sessions.id"),
                nullable=False,
            ),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.String(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("token_usage", sa.JSON(), nullable=True),
            sa.Column("feedback_rating", sa.String(), nullable=True),
            sa.Column("feedback_category", sa.String(), nullable=True),
            sa.Column("blocks", sa.JSON(), nullable=True),
            sa.Column("created_at", TS, nullable=False),
        )
        op.create_index(
            "ix_chat_messages_session_id", "chat_messages", ["session_id"]
        )
    elif "blocks" not in _columns("chat_messages"):
        # Databases built by create_all before Track C's answer blocks (spec §11.1).
        with op.batch_alter_table("chat_messages") as batch:
            batch.add_column(sa.Column("blocks", sa.JSON(), nullable=True))
    if "atlas_audit_log" not in existing:
        op.create_table(
            "atlas_audit_log",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_uid", sa.String(), nullable=False),
            sa.Column("session_id", sa.Uuid(), nullable=True),
            sa.Column("surface", sa.String(), nullable=False),
            sa.Column("tool", sa.String(), nullable=False),
            sa.Column("arguments", sa.JSON(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", TS, nullable=False),
        )
        op.create_index("ix_atlas_audit_log_user_uid", "atlas_audit_log", ["user_uid"])
        op.create_index(
            "ix_atlas_audit_log_session_id", "atlas_audit_log", ["session_id"]
        )


def downgrade() -> None:
    op.drop_table("atlas_audit_log")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_alembic.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic.ini backend/migrations backend/tests/test_alembic.py
git commit -m "feat(db): Alembic with an idempotent baseline of the existing schema"
```

---

### Task 10: Migration 0002 — users, `chat_sessions.user_id`, backfill

**Files:**
- Create: `backend/migrations/versions/0002_users.py`
- Modify: `backend/app/models/chat.py`
- Test: `backend/tests/test_alembic.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alembic.py`:

```python
from uuid import uuid4

from sqlmodel import SQLModel

import app.identity.models  # noqa: F401  # registers users on the metadata
import app.models  # noqa: F401  # registers chat and audit tables


def test_backfill_links_legacy_sessions_to_users(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    config = _config(f"sqlite+aiosqlite:///{db}")
    command.upgrade(config, "0001")
    engine = sa.create_engine(f"sqlite:///{db}")
    sessions = sa.table(
        "chat_sessions",
        sa.column("id", sa.Uuid()),
        sa.column("user_uid", sa.String()),
        sa.column("user_email", sa.String()),
        sa.column("title", sa.String()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
        sa.column("updated_at", sa.TIMESTAMP(timezone=True)),
    )
    now = sa.func.current_timestamp()
    with engine.begin() as conn:
        for uid, email in [
            ("fb-sara", "Sara@yougotagift.com"),
            ("fb-sara", "Sara@yougotagift.com"),
            ("dev-user", "dev@yougotagift.com"),
        ]:
            conn.execute(
                sessions.insert().values(
                    id=uuid4(), user_uid=uid, user_email=email, title="t",
                    created_at=now, updated_at=now,
                )
            )

    command.upgrade(config, "0002")

    with engine.connect() as conn:
        users = conn.execute(sa.text("SELECT email, firebase_uid FROM users")).all()
        linked = conn.execute(
            sa.text("SELECT COUNT(*) FROM chat_sessions WHERE user_id IS NOT NULL")
        ).scalar_one()
        owners = conn.execute(
            sa.text("SELECT DISTINCT user_uid FROM chat_sessions")
        ).scalars().all()
    engine.dispose()

    assert sorted(users) == [
        ("dev@yougotagift.com", None),
        ("sara@yougotagift.com", "fb-sara"),
    ]
    assert linked == 3
    assert "fb-sara" not in owners  # owner key now holds the atlas user id


def test_head_matches_model_columns(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    command.upgrade(_config(f"sqlite+aiosqlite:///{db}"), "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    inspector = sa.inspect(engine)
    try:
        for table in ("users", "chat_sessions", "chat_messages", "atlas_audit_log"):
            migrated = {c["name"] for c in inspector.get_columns(table)}
            declared = set(SQLModel.metadata.tables[table].columns.keys())
            assert migrated == declared, table
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_alembic.py -v`
Expected: FAIL (no revision `0002`; no `users` in metadata columns comparison).

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/chat.py`, inside `class ChatSession`, add after `user_uid`:

```python
    # Owner (atlas users.id). user_uid holds the same id as text for components that
    # still key on strings (guardrails, audit) until phase 2 passes a Principal.
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
```

- [ ] **Step 4: Write the migration**

```python
# backend/migrations/versions/0002_users.py
"""Users table; chat sessions owned by atlas user ids (spec §7, §11.3).

Backfill: one user per distinct legacy owner (by email); sessions get user_id, and
user_uid is rewritten to the atlas user id so guardrails and audit stay consistent.

Revision ID: 0002
Revises: 0001
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.TIMESTAMP(timezone=True)
LEGACY_DEV_UID = "dev-user"

_users = sa.table(
    "users",
    sa.column("id", sa.Uuid()),
    sa.column("email", sa.String()),
    sa.column("firebase_uid", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column("status", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("role", sa.String()),
    sa.column("tenant", sa.String()),
    sa.column("created_at", TS),
)
_sessions = sa.table(
    "chat_sessions",
    sa.column("user_uid", sa.String()),
    sa.column("user_email", sa.String()),
    sa.column("user_id", sa.Uuid()),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("firebase_uid", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("tenant", sa.String(length=64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)
    with op.batch_alter_table("chat_sessions") as batch:
        batch.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_chat_sessions_user_id", ["user_id"])
        batch.create_foreign_key(
            "fk_chat_sessions_user_id_users", "users", ["user_id"], ["id"]
        )
    _backfill()


def _backfill() -> None:
    conn = op.get_bind()
    owners = conn.execute(
        sa.select(_sessions.c.user_uid, _sessions.c.user_email)
        .where(_sessions.c.user_id.is_(None))
        .distinct()
    ).all()
    by_email: dict[str, object] = {}
    for legacy_uid, raw_email in owners:
        email = (raw_email or f"{legacy_uid}@unknown.invalid").strip().lower()
        user_id = by_email.get(email)
        if user_id is None:
            user_id = uuid4()
            by_email[email] = user_id
            conn.execute(
                _users.insert().values(
                    id=user_id,
                    email=email,
                    firebase_uid=None if legacy_uid == LEGACY_DEV_UID else legacy_uid,
                    display_name="",
                    status="active",
                    kind="human",
                    role="viewer",
                    tenant="ygg",
                    created_at=sa.func.current_timestamp(),
                )
            )
        conn.execute(
            _sessions.update()
            .where(_sessions.c.user_uid == legacy_uid)
            .where(_sessions.c.user_id.is_(None))
            .values(user_id=user_id, user_uid=str(user_id))
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_constraint("fk_chat_sessions_user_id_users", type_="foreignkey")
        batch.drop_index("ix_chat_sessions_user_id")
        batch.drop_column("user_id")
    op.drop_table("users")
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_alembic.py -v`
Expected: 4 passed. If `test_head_matches_model_columns` fails, the migration and the model disagree:
fix the migration, never the test.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0002_users.py backend/app/models/chat.py \
  backend/tests/test_alembic.py
git commit -m "feat(db): users table, chat_sessions.user_id and legacy backfill"
```

---

### Task 11: Chat owned by atlas users; deprecated middleware shim

**Files:**
- Modify: `backend/app/api/chat.py`, `backend/tests/test_chat_api.py`
- Rewrite: `backend/app/middleware/__init__.py`
- Delete: `backend/app/middleware/firebase_auth.py`
- Test: `backend/tests/test_middleware_shim.py`

- [ ] **Step 1: Update the chat API tests (failing first)**

In `backend/tests/test_chat_api.py`, replace the second assertion block of `test_session_crud`:

```python
    assert created["title"] == "Weekly numbers"
    me = (await api.get("/api/v1/me")).json()
    assert created["user_id"] == me["user_id"]
    assert created["user_uid"] == me["user_id"]  # owner key mirrors the atlas id
```

(this replaces the line `assert created["user_uid"] == "dev-user"`).

Create the shim test:

```python
# backend/tests/test_middleware_shim.py
"""The deprecated app.middleware shim must keep in-flight callers working."""

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware import AuthUser, get_current_user


async def test_shim_returns_atlas_user_id_and_email(db) -> None:
    app = FastAPI()

    @app.get("/legacy")
    async def legacy(user: AuthUser = Depends(get_current_user)) -> dict[str, str]:
        return {"uid": user.uid, "email": user.email}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/legacy")).json()

    assert body["email"] == "dev@yougotagift.com"
    assert len(body["uid"]) == 36  # an atlas user id (UUID), not "dev-user"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_chat_api.py tests/test_middleware_shim.py -v`
Expected: FAIL (`/api/v1/me` not mounted yet → 404; shim still returns `dev-user`).

- [ ] **Step 3: Rewrite the middleware package as a shim**

Delete `backend/app/middleware/firebase_auth.py`. Replace `backend/app/middleware/__init__.py`:

```python
"""DEPRECATED compatibility shim. Use `from app.identity import Principal, get_principal`.

Kept so `app.insights` (Hybrid Glass Track E) keeps working without edits from this
branch. Removal is tracked in ARCHITECTURE.md §6.
"""

from dataclasses import dataclass

from fastapi import Depends

from app.identity import Principal, get_principal


@dataclass(frozen=True)
class AuthUser:
    uid: str  # the atlas user id as text
    email: str


async def get_current_user(principal: Principal = Depends(get_principal)) -> AuthUser:
    return AuthUser(uid=str(principal.user_id), email=principal.email)


__all__ = ["AuthUser", "get_current_user"]
```

- [ ] **Step 4: Move chat to the Principal**

In `backend/app/api/chat.py` (it already imports `col` from sqlmodel):

Replace the import line `from app.middleware import AuthUser, get_current_user` with:

```python
from app.identity import Principal, get_principal
```

Replace `_owned_session` with:

```python
async def _owned_session(
    session_id: UUID, principal: Principal, db: AsyncSession
) -> ChatSession:
    session = (
        await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    if session is None or session.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
```

In every route, replace the parameter `user: AuthUser = Depends(get_current_user)` with
`principal: Principal = Depends(get_principal)`, and each `_owned_session(..., user, db)` call with
`_owned_session(..., principal, db)`.

In `create_session`, replace the `ChatSession(...)` construction with:

```python
    session = ChatSession(
        user_id=principal.user_id,
        user_uid=str(principal.user_id),
        user_email=principal.email,
        title=body.title or "New chat",
    )
```

In `list_sessions`, replace `.where(ChatSession.user_uid == user.uid)` with:

```python
        .where(col(ChatSession.user_id) == principal.user_id)
```

In `send_message`'s stream, replace `user_uid=user.uid,` with:

```python
                user_uid=str(principal.user_id),
```

- [ ] **Step 5: Mount `/me` (needed by the chat test)**

In `backend/app/main.py`, add `from app.identity import identity_router` next to the other `app.`
imports and `app.include_router(identity_router)` directly after `app.include_router(chat_router)`.
(The lifespan changes come in Task 12.)

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/test_chat_api.py tests/test_middleware_shim.py -v`
Expected: all pass, including `test_session_isolation_404_for_foreign_session` (a session with no
`user_id` is never visible).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/chat.py backend/app/main.py backend/app/middleware \
  backend/tests/test_chat_api.py backend/tests/test_middleware_shim.py
git commit -m "feat(chat): sessions owned by atlas users; middleware becomes a deprecated shim"
```

---

### Task 12: Startup — Alembic owns the schema, bootstrap admins

**Files:**
- Modify: `backend/app/main.py`, `backend/Dockerfile`, `Makefile`
- Create: `backend/.dockerignore`, `frontend/.dockerignore`
- Delete: `backend/app/models/migrations.py`, `backend/tests/test_migrations.py` (baseline 0001 now owns `blocks`)
- Test: `backend/tests/test_startup.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_startup.py
"""Startup applies bootstrap admins and no longer creates tables itself."""

import inspect

from app import main
from app.identity.repository import UserRepository


async def test_startup_applies_bootstrap_admins(db, monkeypatch) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMINS", "boss@yougotagift.com")
    main.get_settings.cache_clear()
    try:
        await main.apply_bootstrap_admins()
    finally:
        main.get_settings.cache_clear()

    user = await UserRepository(db).get_by_email("boss@yougotagift.com")
    assert user is not None
    assert user.role == "admin"


def test_lifespan_leaves_schema_to_alembic() -> None:
    source = inspect.getsource(main.lifespan)
    assert "create_all" not in source
    assert "ensure_blocks_column" not in source
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_startup.py -v`
Expected: FAIL (no bootstrap; `create_all` still in the lifespan).

- [ ] **Step 3: Update the lifespan**

In `backend/app/main.py`: remove `from sqlmodel import SQLModel`, `from app.database import get_engine`
and `from app.models.migrations import ensure_blocks_column`; add
`from app.database import get_session_factory`; change `from app.identity import identity_router` to
`from app.identity import bootstrap_admins, identity_router`. Keep `insights_router`. Delete
`backend/app/models/migrations.py` and `backend/tests/test_migrations.py`. Replace the lifespan with:

```python
async def apply_bootstrap_admins() -> None:
    async with get_session_factory()() as db:
        await bootstrap_admins(db, get_settings().bootstrap_admin_list)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Schema is owned by Alembic: `alembic upgrade head` runs before the app starts.
    await apply_bootstrap_admins()
    logger.info("startup.complete")
    if mcp is not None:
        # The mounted streamable-HTTP app requires its session manager running.
        async with mcp.session_manager.run():
            yield
    else:
        yield
```

- [ ] **Step 4: Run migrations before the server, and keep secrets out of images**

`backend/Dockerfile` — replace the `CMD` line:

```dockerfile
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && exec uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8081"]
```

Create `backend/.dockerignore`:

```
.env
.env.*
!.env.example
.venv
__pycache__
.pytest_cache
.ruff_cache
.coverage
htmlcov
tests
```

Create `frontend/.dockerignore` (a baked `.env.local` with `VITE_AUTH_DISABLED=true` would ship a
production bundle with login bypassed; `frontend/.env` stays, as it may carry the public Firebase web
config the build needs):

```
.env.local
.env.*.local
node_modules
dist
coverage
```

In the root `Makefile`, add `migrate` to the `.PHONY` line and add this target after `install`:

```make
migrate: ## Apply database migrations (backend/.env DATABASE_URL)
	cd backend && uv run alembic upgrade head
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_startup.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/Dockerfile backend/.dockerignore \
  frontend/.dockerignore Makefile backend/tests/test_startup.py \
  backend/app/models/migrations.py backend/tests/test_migrations.py
git commit -m "feat(startup): Alembic owns the schema (retires ensure_blocks_column), bootstrap admins"
```

---

### Task 13: Architecture contracts, strict typing, docs

**Files:**
- Modify: `backend/pyproject.toml`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md`, `backend/.env.example`

- [ ] **Step 1: Contracts and strict typing**

In `backend/pyproject.toml`:

In `[tool.pyright]`, extend the ratchet: `strict = ["app/insights", "app/identity"]`.

In the "Source plugins are leaves" contract, add `"app.identity"` to `forbidden_modules`.

Replace the "Platform modules never depend on features" contract with:

```toml
[[tool.importlinter.contracts]]
name = "Platform modules never depend on features"
type = "forbidden"
source_modules = ["app.config", "app.database", "app.models"]
forbidden_modules = [
    "app.main", "app.api", "app.mcp", "app.insights", "app.agent", "app.atlas",
    "app.sources", "app.identity", "app.middleware",
]
```

Replace the "Agent and atlas never use HTTP-layer auth" contract with:

```toml
[[tool.importlinter.contracts]]
name = "Agent and atlas never use HTTP-layer auth"
type = "forbidden"
source_modules = ["app.agent", "app.atlas"]
forbidden_modules = [
    "app.middleware",
    "app.identity.router",
    "app.identity.dependencies",
    "app.identity.firebase",
]
```

Add two contracts:

```toml
[[tool.importlinter.contracts]]
name = "Identity depends only on platform modules"
type = "forbidden"
source_modules = ["app.identity"]
forbidden_modules = [
    "app.main", "app.api", "app.mcp", "app.insights", "app.agent", "app.atlas",
    "app.sources", "app.middleware",
]

[[tool.importlinter.contracts]]
name = "Identity module layering (ARCHITECTURE.md §2.2)"
type = "layers"
containers = ["app.identity"]
layers = [
    "router",
    "dependencies | bootstrap",
    "service | firebase",
    "repository",
    "models",
    "schemas",
    "principal | tokens | errors",
]
```

Run: `uv run lint-imports && uv run pyright`
Expected: all contracts kept; 0 errors. Fix the code (never the contract) if anything breaks.

- [ ] **Step 2: Environment example**

In `backend/.env.example`, after `AUTH_DISABLED=false` add:

```bash
# development | test | production. Production refuses to start with AUTH_DISABLED=true.
ENVIRONMENT=development
# Comma-separated emails made admin at startup (idempotent).
BOOTSTRAP_ADMINS=
# Web sessions are capped server-side from the sign-in time.
SESSION_MAX_AGE_HOURS=24
```

- [ ] **Step 3: Architecture and developer docs**

In `ARCHITECTURE.md` §2.1, replace the platform line of the diagram with:

```
platform: app.models · app.database · app.config   (+ app.core, new)
identity: app.identity (who is calling; depends only on platform)   · app.middleware = deprecated shim
```

In `ARCHITECTURE.md` §6 (known debt): delete the row "No per-module layering contract yet"; replace the
row about `app/config.py`, `app/database.py` and `app/middleware/` with:

```
| `app/config.py` and `app/database.py` predate `app/core` | Move into `app/core/` when next modified |
| `app.middleware` is a deprecated shim over `app.identity` | Remove once `app.insights.dependencies` imports `get_principal` |
| `chat_sessions.user_uid` mirrors `user_id` as text for guardrails and audit | Drop in auth phase 2, when guardrails and atlas tools take a `Principal` |
```

Delete the `chat_messages.blocks` startup-ALTER row (baseline 0001 owns the column now). Update the
`app/api/chat.py` row's target to: "Split into `app/chat/{router,service,repository}` on the next chat
change".

In `CLAUDE.md` "Development" (backend block), add after `uv run uvicorn …`:

```bash
uv run alembic upgrade head        # apply migrations (also run by the Docker image at start)
uv run alembic revision -m "..."   # new migration in migrations/versions/
```

In `README.md` "Deployment (AWS EC2)", add after the `docker compose up -d --build` line:

```
Migrations run automatically when the backend container starts (`alembic upgrade head`). The baseline
is idempotent, so an existing database created by the old `create_all` upgrades in place. Keep
`ENVIRONMENT=development` on the box until Firebase sign-in is configured; production refuses to start
with `AUTH_DISABLED=true`.
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/.env.example ARCHITECTURE.md CLAUDE.md README.md
git commit -m "chore(identity): contracts, strict typing, env and docs"
```

---

### Task 14: Full gate and review

- [ ] **Step 1: Run the complete gate**

Run (repo root): `make check`
Expected: exit 0. Ruff and Prettier clean, Pyright 0 errors (strict on `app/identity`), all import
contracts kept, all tests pass, coverage ≥ 80%.

- [ ] **Step 2: Verify migrations on Postgres-shaped data locally**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:////tmp/ygg-phase1.db uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head`
Expected: no errors in either direction.

- [ ] **Step 3: Production code review**

Follow `.claude/skills/production-code-review/SKILL.md` against `fe60bf3..HEAD`. Fix every blocking
finding, re-run `make check`, and record the verdict in the final commit message or PR description.

- [ ] **Step 4: Rebase checkpoint (coordination)**

If `feature/hybrid-glass` has moved past `47a7200`, rebase onto it and re-run `make check`. Ask session
`ygg-atlas-8b` before touching any file wave 2 changed. Merge to `main` only after `feature/hybrid-glass`
(the user decides when).

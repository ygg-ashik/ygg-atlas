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
    provider: str = "google.com",
) -> VerifiedToken:
    return VerifiedToken(
        uid=uid,
        email=email,
        email_verified=verified,
        name="Sara Ali",
        auth_time=int(signed_in.timestamp()),
        sign_in_provider=provider,
    )


def _service(db) -> IdentityService:
    settings = Settings.model_validate(
        {"environment": "test", "allowed_email_domain": "yougotagift.com"}
    )
    return IdentityService(UserRepository(db), settings, clock=lambda: NOW)


async def test_first_sign_in_creates_viewer_with_no_extra_rights(db) -> None:
    principal = await _service(db).resolve_web(_token())

    assert principal.email == "sara@yougotagift.com"
    assert principal.role == "viewer"
    assert principal.auth_method == "web"
    stored = await UserRepository(db).get(principal.user_id)
    assert stored is not None
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
    linked = await users.get(pre.id)
    assert linked is not None
    assert linked.firebase_uid == "fb-sara"


async def test_other_domain_is_forbidden(db) -> None:
    with pytest.raises(ForbiddenError, match=r"@yougotagift\.com"):
        await _service(db).resolve_web(_token(email="x@gmail.com"))


async def test_lookalike_domain_is_forbidden(db) -> None:
    with pytest.raises(ForbiddenError):
        await _service(db).resolve_web(_token(email="x@evil-yougotagift.com"))


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
    assert stored is not None
    assert stored.last_seen_at is not None


async def test_non_google_sign_in_is_forbidden(db) -> None:
    # Email-link or password sign-in would bypass Workspace SSO, 2FA and offboarding.
    with pytest.raises(ForbiddenError, match="Google"):
        await _service(db).resolve_web(_token(provider="password"))


async def test_disabled_user_row_is_not_relinked(db) -> None:
    users = UserRepository(db)
    disabled = await users.save(
        User(
            email="sara@yougotagift.com",
            firebase_uid="fb-old",
            status=UserStatus.DISABLED,
        )
    )
    with pytest.raises(ForbiddenError):
        await _service(db).resolve_web(_token(uid="fb-new"))
    stored = await users.get(disabled.id)
    assert stored is not None
    assert stored.firebase_uid == "fb-old"


async def test_relinks_a_recreated_google_account_by_email(db) -> None:
    users = UserRepository(db)
    existing = await users.save(
        User(email="sara@yougotagift.com", firebase_uid="fb-old")
    )
    principal = await _service(db).resolve_web(_token(uid="fb-new"))
    assert principal.user_id == existing.id
    stored = await users.get(existing.id)
    assert stored is not None
    assert stored.firebase_uid == "fb-new"

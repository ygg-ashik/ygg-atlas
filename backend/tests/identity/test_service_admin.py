from uuid import uuid4

import pytest

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
    return IdentityService(
        UserRepository(db), Settings.model_validate({"environment": "test"})
    )


async def test_dev_user_is_created_once_as_viewer(db) -> None:
    first = await _service(db).ensure_dev_user()
    second = await _service(db).ensure_dev_user()

    assert first.user_id == second.user_id
    assert first.email == "dev@yougotagift.com"
    assert first.role == "viewer"  # admin only via BOOTSTRAP_ADMINS
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


async def test_disable_unknown_user_raises(db) -> None:
    with pytest.raises(LookupError):
        await _service(db).disable_user(uuid4(), RecordingVerifier())

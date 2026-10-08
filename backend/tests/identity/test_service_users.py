from structlog.testing import capture_logs

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


async def test_ensure_service_user_warns_when_the_email_belongs_to_a_human(
    db,
) -> None:
    human = await UserRepository(db).save(User(email=EMAIL))

    with capture_logs() as logs:
        returned = await ensure_service_user(db, EMAIL, "MCP (shared token)", "analyst")

    assert returned.id == human.id
    assert returned.kind == UserKind.HUMAN
    events = [log for log in logs if log["event"] == "identity.service_email_taken"]
    assert len(events) == 1
    assert events[0]["user_id"] == str(human.id)

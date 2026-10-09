"""PolicyUnavailableError: internal reasons are logged, never sent to clients."""

import json

import pytest
from sqlalchemy import delete
from structlog.testing import capture_logs

from app.access.dependencies import access_error_handler
from app.access.errors import PolicyUnavailableError
from app.access.models import PolicyState
from app.access.repository import AccessRepository
from app.access.schemas import GroupCreate
from tests.access_helpers import actor_with, admin_for

PUBLIC = "The access check is unavailable right now."


def test_the_client_message_is_business_language() -> None:
    exc = PolicyUnavailableError("policy_state has no row")
    assert str(exc) == PUBLIC
    assert exc.reason == "policy_state has no row"


async def test_the_handler_logs_the_reason_and_hides_it() -> None:
    with capture_logs() as logs:
        response = await access_error_handler(
            None,  # pyright: ignore[reportArgumentType]  # unused by the handler
            PolicyUnavailableError("policy_state has no row"),
        )
    assert response.status_code == 503
    body = json.loads(bytes(response.body))
    assert body == {"detail": PUBLIC}
    assert "policy_state" not in body["detail"]
    events = [e for e in logs if e["event"] == "access.policy_unavailable"]
    assert events
    assert events[0]["reason"] == "policy_state has no row"


async def test_every_repository_raise_site_hides_policy_state(db) -> None:
    actor = await actor_with(db)
    await db.execute(delete(PolicyState))
    await db.commit()
    repo = AccessRepository(db)

    for call in (repo.policy_version, repo.lock_for_write, repo.bump_version):
        with pytest.raises(PolicyUnavailableError) as raised:
            await call()
        assert "policy_state" not in str(raised.value)
        assert "policy_state" in raised.value.reason
    await db.rollback()

    with pytest.raises(PolicyUnavailableError) as raised:
        await admin_for(db).create_group(actor, GroupCreate(name="growth"))
    assert str(raised.value) == PUBLIC

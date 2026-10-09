"""Disabling a user revokes every token they hold (D18, C5); the bearer door refuses
a disabled user even when that revocation fails."""

from uuid import uuid4

import pytest
from sqlmodel import col, select

from app.access.schemas import UserUpdate
from app.identity.api_tokens import (
    EVENT_TOKENS_REVOKED_ALL,
    REVOKED_USER_DISABLED,
    TokenKind,
)
from app.identity.credentials import TokenService, authenticate_bearer
from app.identity.errors import ForbiddenError
from app.identity.models import CredentialEvent
from app.identity.repository import CredentialRepository
from tests.access_helpers import actor_with, admin_for, make_user
from tests.identity.credential_helpers import insert_token, make_client


async def _sara_with_tokens(db):
    sara = await make_user(db, "sara@yougotagift.com")
    client = await make_client(db)
    family = uuid4()
    pat, pat_raw = await insert_token(db, sara, TokenKind.PAT)
    access, _ = await insert_token(
        db, sara, TokenKind.OAUTH_ACCESS, client_id=client.client_id, family_id=family
    )
    refresh, _ = await insert_token(
        db, sara, TokenKind.OAUTH_REFRESH, client_id=client.client_id, family_id=family
    )
    return sara, [pat, access, refresh], pat_raw


async def test_disabling_a_user_revokes_all_their_tokens(db) -> None:
    actor = await actor_with(db)
    sara, tokens, _ = await _sara_with_tokens(db)

    await admin_for(db).update_user(actor, sara.id, UserUpdate(status="disabled"))

    creds = CredentialRepository(db)
    for token in tokens:
        row = await creds.token(token.id, fresh=True)
        assert row is not None
        assert row.revoked_at is not None
        assert row.revoked_reason == REVOKED_USER_DISABLED
    events = (
        (
            await db.execute(
                select(CredentialEvent).where(
                    col(CredentialEvent.event) == EVENT_TOKENS_REVOKED_ALL
                )
            )
        )
        .scalars()
        .all()
    )
    (event,) = events
    assert event.user_id == sara.id
    assert event.actor_user_id == actor.user_id
    assert event.via == "api"
    assert event.details == {"count": 3, "reason": REVOKED_USER_DISABLED}


async def test_role_change_does_not_revoke_tokens(db) -> None:
    actor = await actor_with(db)
    sara, tokens, _ = await _sara_with_tokens(db)

    await admin_for(db).update_user(actor, sara.id, UserUpdate(role="analyst"))

    creds = CredentialRepository(db)
    for token in tokens:
        row = await creds.token(token.id, fresh=True)
        assert row is not None
        assert row.revoked_at is None


async def test_disabled_user_is_refused_even_if_revocation_failed(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = await actor_with(db)
    sara, tokens, pat_raw = await _sara_with_tokens(db)

    async def _boom(self: TokenService, *args: object, **kwargs: object) -> int:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(TokenService, "revoke_all_tokens", _boom)

    user = await admin_for(db).update_user(
        actor, sara.id, UserUpdate(status="disabled")
    )

    assert user.status == "disabled"
    row = await CredentialRepository(db).token(tokens[0].id, fresh=True)
    assert row is not None
    assert row.revoked_at is None
    with pytest.raises(ForbiddenError):
        await authenticate_bearer(db, pat_raw)

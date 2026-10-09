"""TokenService: personal and service tokens, revocation, connected apps (D3, D15)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity import UNNAMED_CLIENT, oauth
from app.identity.api_tokens import (
    EVENT_FAMILY_REVOKED,
    EVENT_TOKEN_CREATED,
    EVENT_TOKEN_REVOKED,
    EVENT_TOKENS_REVOKED_ALL,
    MAX_LIVE_PATS,
    REVOKED_APP_DISCONNECTED,
    REVOKED_BY_ADMIN,
    REVOKED_BY_USER,
    REVOKED_ROTATED,
    REVOKED_USER_DISABLED,
    CredentialActor,
    TokenKind,
    hash_secret,
)
from app.identity.credentials import (
    TokenService,
    authenticate_bearer,
    revoke_user_tokens,
    tenant_of_user,
)
from app.identity.errors import (
    CredentialLimitError,
    CredentialNotFoundError,
    CredentialRuleError,
)
from app.identity.models import ApiToken, CredentialEvent, User
from app.identity.repository import CredentialRepository
from app.identity.tokens import InvalidTokenError
from tests.access_helpers import make_user
from tests.identity.credential_helpers import (
    assert_no_secret,
    insert_token,
    make_client,
)

DEFAULT_DAYS = 90
MAX_DAYS = 365
FIXED = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


async def _human(db: AsyncSession, *, status: str = "active") -> User:
    return await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", status=status)


async def _service(db: AsyncSession, *, status: str = "active") -> User:
    return await make_user(
        db, f"svc-{uuid4().hex[:8]}@atlas.internal", kind="service", status=status
    )


def _api(user: User) -> CredentialActor:
    return CredentialActor(user_id=user.id, via="api")


async def _pat(
    service: TokenService,
    user: User,
    *,
    name: str = "laptop",
    days: int | None = None,
    max_days: int = MAX_DAYS,
):
    return await service.create_pat(
        user.id,
        name=name,
        expires_in_days=days,
        actor=_api(user),
        default_days=DEFAULT_DAYS,
        max_days=max_days,
    )


async def _events(db: AsyncSession, event: str) -> list[CredentialEvent]:
    result = await db.execute(
        select(CredentialEvent).where(col(CredentialEvent.event) == event)
    )
    return list(result.scalars().all())


async def _reload(db: AsyncSession, token_id: UUID) -> ApiToken:
    row = await CredentialRepository(db).token(token_id, fresh=True)
    assert row is not None
    return row


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def test_create_pat_stores_only_the_hash(db) -> None:
    user = await _human(db)
    with capture_logs() as logs:
        issued = await _pat(TokenService(db), user, name="  laptop  ")

    raw = issued.raw
    assert raw.startswith("atl_pat_")
    row = await _reload(db, issued.token.id)
    assert row.token_hash == hash_secret(raw)
    assert row.prefix == raw[:14]
    assert row.name == "laptop"
    assert row.created_by == user.id
    assert row.kind == TokenKind.PAT
    (event,) = await _events(db, EVENT_TOKEN_CREATED)
    assert event.token_id == row.id
    assert event.user_id == user.id
    assert event.actor_user_id == user.id
    assert event.via == "api"
    assert event.details == {
        "kind": "pat",
        "name": "laptop",
        "prefix": raw[:14],
        "via": "api",
    }
    assert_no_secret(
        raw,
        row.model_dump(),
        event.model_dump(),
        repr(issued),
        repr(row),
        logs,
    )
    bearer = await authenticate_bearer(db, raw)
    assert bearer.principal.token_id == row.id


async def test_create_pat_defaults_to_90_days_and_caps_at_365(db) -> None:
    user = await _human(db)
    service = TokenService(db, clock=lambda: FIXED)

    default = await _pat(service, user)
    longest = await _pat(service, user, days=365, name="long")

    assert _utc(default.token.expires_at) == FIXED + timedelta(days=90)
    assert _utc(longest.token.expires_at) == FIXED + timedelta(days=365)
    with pytest.raises(CredentialRuleError):
        await _pat(service, user, days=366, max_days=400)


@pytest.mark.parametrize(("days", "max_days"), [(0, 365), (-1, 365), (31, 30)])
async def test_pat_days_out_of_range(db, days: int, max_days: int) -> None:
    user = await _human(db)
    with pytest.raises(CredentialRuleError):
        await _pat(TokenService(db), user, days=days, max_days=max_days)


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_pat_name_must_be_1_to_100_characters(db, name: str) -> None:
    user = await _human(db)
    with pytest.raises(CredentialRuleError):
        await _pat(TokenService(db), user, name=name)


async def test_eleventh_live_pat_is_refused(db) -> None:
    user = await _human(db)
    await insert_token(db, user, TokenKind.PAT, revoked_reason=REVOKED_BY_USER)
    await insert_token(db, user, TokenKind.PAT, expires_in=timedelta(seconds=-1))
    service = TokenService(db)
    for index in range(MAX_LIVE_PATS):
        await _pat(service, user, name=f"pat {index}")

    with pytest.raises(CredentialLimitError):
        await _pat(service, user, name="one too many")
    assert len(await _events(db, EVENT_TOKEN_CREATED)) == MAX_LIVE_PATS


async def test_pat_needs_an_active_human(db) -> None:
    service = TokenService(db)
    disabled = await _human(db, status="disabled")
    robot = await _service(db)
    for target in (disabled, robot):
        with pytest.raises(CredentialRuleError):
            await _pat(service, target)
    with pytest.raises(CredentialRuleError):
        await service.create_pat(
            uuid4(),
            name="ghost",
            expires_in_days=None,
            actor=CredentialActor(None, "cli"),
            default_days=DEFAULT_DAYS,
            max_days=MAX_DAYS,
        )


async def test_service_token_needs_an_active_service_account(db) -> None:
    admin = await _human(db)
    robot = await _service(db)
    service = TokenService(db, clock=lambda: FIXED)

    issued = await service.create_service_token(
        robot.id,
        name="ci",
        expires_in_days=None,
        actor=_api(admin),
        default_days=DEFAULT_DAYS,
        max_days=MAX_DAYS,
    )

    assert issued.raw.startswith("atl_svc_")
    assert issued.token.kind == TokenKind.SERVICE
    assert issued.token.user_id == robot.id
    assert issued.token.created_by == admin.id
    assert _utc(issued.token.expires_at) == FIXED + timedelta(days=DEFAULT_DAYS)
    for target in (admin, await _service(db, status="disabled")):
        with pytest.raises(CredentialRuleError):
            await service.create_service_token(
                target.id,
                name="ci",
                expires_in_days=None,
                actor=_api(admin),
                default_days=DEFAULT_DAYS,
                max_days=MAX_DAYS,
            )


async def test_service_tokens_have_no_live_cap(db) -> None:
    admin = await _human(db)
    robot = await _service(db)
    service = TokenService(db)
    for index in range(MAX_LIVE_PATS + 1):
        await service.create_service_token(
            robot.id,
            name=f"svc {index}",
            expires_in_days=1,
            actor=_api(admin),
            default_days=DEFAULT_DAYS,
            max_days=MAX_DAYS,
        )


async def test_revoke_own_token_only(db) -> None:
    owner = await _human(db)
    other = await _human(db)
    service = TokenService(db)
    issued = await _pat(service, owner)

    with pytest.raises(CredentialNotFoundError):
        await service.revoke_token(
            issued.token.id,
            reason=REVOKED_BY_USER,
            actor=_api(other),
            owner_id=other.id,
        )
    with pytest.raises(CredentialNotFoundError):
        await service.revoke_token(
            issued.token.id,
            reason=REVOKED_BY_ADMIN,
            actor=_api(other),
            tenant="elsewhere",
        )
    with pytest.raises(CredentialNotFoundError):
        await service.revoke_token(
            uuid4(), reason=REVOKED_BY_USER, actor=_api(owner), owner_id=owner.id
        )
    assert (await _reload(db, issued.token.id)).revoked_at is None

    await service.revoke_token(
        issued.token.id, reason=REVOKED_BY_USER, actor=_api(owner), owner_id=owner.id
    )

    row = await _reload(db, issued.token.id)
    assert row.revoked_at is not None
    assert row.revoked_reason == REVOKED_BY_USER
    (event,) = await _events(db, EVENT_TOKEN_REVOKED)
    assert (event.token_id, event.user_id, event.actor_user_id) == (
        row.id,
        owner.id,
        owner.id,
    )
    assert event.details["reason"] == REVOKED_BY_USER
    with pytest.raises(InvalidTokenError):
        await authenticate_bearer(db, issued.raw)


async def test_admin_revokes_within_the_tenant(db) -> None:
    owner = await _human(db)
    admin = await _human(db)
    service = TokenService(db)
    issued = await _pat(service, owner)

    await service.revoke_token(
        issued.token.id, reason=REVOKED_BY_ADMIN, actor=_api(admin), tenant="ygg"
    )

    assert (await _reload(db, issued.token.id)).revoked_reason == REVOKED_BY_ADMIN


async def test_revoke_is_idempotent(db) -> None:
    owner = await _human(db)
    service = TokenService(db)
    issued = await _pat(service, owner)
    for _ in range(2):
        await service.revoke_token(
            issued.token.id,
            reason=REVOKED_BY_USER,
            actor=_api(owner),
            owner_id=owner.id,
        )
    assert len(await _events(db, EVENT_TOKEN_REVOKED)) == 1


async def test_revoke_all_covers_every_kind_and_writes_one_event(db) -> None:
    user = await _human(db)
    admin = await _human(db)
    client = await make_client(db)
    family = uuid4()
    pat, _ = await insert_token(db, user, TokenKind.PAT)
    access, _ = await insert_token(
        db, user, TokenKind.OAUTH_ACCESS, client_id=client.client_id, family_id=family
    )
    refresh, _ = await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, client_id=client.client_id, family_id=family
    )
    rotated, _ = await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        client_id=client.client_id,
        family_id=family,
        revoked_reason=REVOKED_ROTATED,
    )

    count = await TokenService(db).revoke_all_tokens(
        user.id, reason=REVOKED_USER_DISABLED, actor=_api(admin)
    )

    assert count == 3
    for token in (pat, access, refresh):
        assert (await _reload(db, token.id)).revoked_reason == REVOKED_USER_DISABLED
    assert (await _reload(db, rotated.id)).revoked_reason == REVOKED_ROTATED
    (event,) = await _events(db, EVENT_TOKENS_REVOKED_ALL)
    assert event.user_id == user.id
    assert event.actor_user_id == admin.id
    assert event.details == {"count": 3, "reason": REVOKED_USER_DISABLED}


async def test_connected_apps_lists_live_families_and_revoke_family_kills_them(
    db,
) -> None:
    user = await _human(db)
    other = await _human(db)
    client = await make_client(db, name="Claude Code")
    live_family, dead_family = uuid4(), uuid4()
    _, access_raw = await insert_token(
        db,
        user,
        TokenKind.OAUTH_ACCESS,
        client_id=client.client_id,
        family_id=live_family,
    )
    await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        client_id=client.client_id,
        family_id=live_family,
    )
    await insert_token(
        db,
        user,
        TokenKind.OAUTH_REFRESH,
        client_id=client.client_id,
        family_id=dead_family,
        revoked_reason=REVOKED_ROTATED,
    )
    service = TokenService(db)

    (app,) = await service.list_connected_apps(user.id)

    assert app.family_id == live_family
    assert app.client_id == client.client_id
    assert app.client_name == "Claude Code"
    assert app.redirect_host == "localhost"
    assert app.created_at.tzinfo is not None
    assert app.expires_at.tzinfo is not None
    assert await service.list_connected_apps(other.id) == []

    with pytest.raises(CredentialNotFoundError):
        await service.revoke_family(
            live_family,
            reason=REVOKED_APP_DISCONNECTED,
            actor=_api(other),
            owner_id=other.id,
        )
    await authenticate_bearer(db, access_raw)  # still live

    await service.revoke_family(
        live_family,
        reason=REVOKED_APP_DISCONNECTED,
        actor=_api(user),
        owner_id=user.id,
    )

    assert await service.list_connected_apps(user.id) == []
    with pytest.raises(InvalidTokenError):
        await authenticate_bearer(db, access_raw)
    (event,) = await _events(db, EVENT_FAMILY_REVOKED)
    assert event.user_id == user.id
    assert event.client_id == client.client_id
    assert event.details == {
        "family_id": str(live_family),
        "count": 2,
        "reason": REVOKED_APP_DISCONNECTED,
    }
    with pytest.raises(CredentialNotFoundError):
        await service.revoke_family(
            live_family,
            reason=REVOKED_APP_DISCONNECTED,
            actor=_api(user),
            owner_id=user.id,
        )


async def test_revoke_family_without_an_owner_is_idempotent(db) -> None:
    user = await _human(db)
    client = await make_client(db)
    family = uuid4()
    await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, client_id=client.client_id, family_id=family
    )
    service = TokenService(db)
    actor = CredentialActor(None, "cli")

    await service.revoke_family(family, reason=REVOKED_BY_ADMIN, actor=actor)
    await service.revoke_family(family, reason=REVOKED_BY_ADMIN, actor=actor)

    (event,) = await _events(db, EVENT_FAMILY_REVOKED)
    assert event.details["count"] == 1
    assert event.user_id is None


async def test_list_tokens_and_events_are_tenant_scoped(db) -> None:
    user = await _human(db)
    robot = await _service(db)
    service = TokenService(db)
    pat = await _pat(service, user)
    await service.create_service_token(
        robot.id,
        name="ci",
        expires_in_days=None,
        actor=_api(user),
        default_days=DEFAULT_DAYS,
        max_days=MAX_DAYS,
    )
    await service.revoke_token(
        pat.token.id, reason=REVOKED_BY_USER, actor=_api(user), owner_id=user.id
    )

    live = await service.list_tokens(tenant="ygg")
    everything = await service.list_tokens(tenant="ygg", include_revoked=True)
    mine = await service.list_tokens(
        tenant="ygg", user_id=user.id, kinds=(TokenKind.PAT,), include_revoked=True
    )

    assert [t.kind for t in live] == [TokenKind.SERVICE]
    assert len(everything) == 2
    assert [t.id for t in mine] == [pat.token.id]
    assert await service.list_tokens(tenant="elsewhere") == []
    events = await service.list_events(tenant="ygg", user_id=user.id)
    assert {e.event for e in events} == {EVENT_TOKEN_CREATED, EVENT_TOKEN_REVOKED}
    assert len(await service.list_events(tenant="ygg", limit=1)) == 1


async def test_revoke_user_tokens_revokes_in_its_own_session(db) -> None:
    user = await _human(db)
    admin = await _human(db)
    pat, _ = await insert_token(db, user, TokenKind.PAT)

    await revoke_user_tokens(
        user.id, reason=REVOKED_USER_DISABLED, actor_user_id=admin.id, via="api"
    )

    assert (await _reload(db, pat.id)).revoked_reason == REVOKED_USER_DISABLED
    (event,) = await _events(db, EVENT_TOKENS_REVOKED_ALL)
    assert (event.actor_user_id, event.via) == (admin.id, "api")


async def test_revoke_user_tokens_never_raises(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _human(db)

    async def _boom(self: CredentialRepository, *args: object) -> int:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(CredentialRepository, "revoke_user_tokens", _boom)
    with capture_logs() as logs:
        await revoke_user_tokens(
            user.id, reason=REVOKED_USER_DISABLED, actor_user_id=None, via="cli"
        )

    (failure,) = [e for e in logs if e["event"] == "identity.revoke_all_failed"]
    assert failure["user_id"] == str(user.id)
    assert failure["error"] == "RuntimeError"


async def test_connected_app_of_an_unnamed_client_gets_the_fallback_name(db) -> None:
    user = await _human(db)
    client = await make_client(db, name=None)
    await insert_token(
        db, user, TokenKind.OAUTH_REFRESH, client_id=client.client_id, family_id=uuid4()
    )

    (app,) = await TokenService(db).list_connected_apps(user.id)

    assert app.client_name == UNNAMED_CLIENT == "Unnamed client"


async def test_tenant_of_user_ignores_status(db) -> None:
    active = await _human(db)
    disabled = await _human(db, status="disabled")

    assert await tenant_of_user(db, active.id) == active.tenant
    assert await tenant_of_user(db, disabled.id) == disabled.tenant
    assert await tenant_of_user(db, uuid4()) is None


def test_oauth_and_connected_apps_share_one_unnamed_client_name() -> None:
    # oauth.py keeps its own copy until it imports the api_tokens one.
    assert oauth.UNNAMED_CLIENT == UNNAMED_CLIENT

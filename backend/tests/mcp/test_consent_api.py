"""/oauth/consent: the Firebase-signed approval step of the OAuth flow (D4, D36)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.identity import CredentialEvent, OAuthAuthorizationRequest, OAuthCode, User
from app.identity.api_tokens import hash_secret
from tests.access_helpers import bump, make_user
from tests.identity.credential_helpers import LOOPBACK_REDIRECT, assert_no_secret
from tests.identity.oauth_helpers import (
    HOSTED_REDIRECT,
    always_eligible,
    query_param,
)
from tests.mcp.api_helpers import (
    FakeFirebase,
    api_app,
    as_user,
    client_for,
    oauth_service,
    real_door,
    start_authorization,
)

CONSENT = "/api/v1/oauth/consent"


@pytest_asyncio.fixture
async def app() -> FastAPI:
    return api_app()


@pytest_asyncio.fixture
async def analyst(db: AsyncSession) -> User:
    return await make_user(db, "ana@yougotagift.com", role="analyst")


@pytest_asyncio.fixture
async def api(app: FastAPI, analyst: User) -> AsyncIterator[AsyncClient]:
    as_user(app, analyst)
    async with client_for(app) as client:
        yield client


async def _codes(db: AsyncSession) -> list[OAuthCode]:
    result = await db.execute(
        select(OAuthCode).execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def test_prompt_shows_client_redirect_host_loopback_and_email(
    api: AsyncClient, db: AsyncSession
) -> None:
    _, txn = await start_authorization(db)
    resp = await api.get(f"{CONSENT}/{txn}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_id"] == txn
    assert body["client_name"] == "Claude Code"
    assert body["redirect_uri"] == LOOPBACK_REDIRECT
    assert body["redirect_host"] == "localhost"
    assert body["loopback"] is True
    assert body["user_email"] == "ana@yougotagift.com"
    assert body["eligible"] is True
    assert body["ineligible_reason"] is None
    assert body["expires_at"]


async def test_prompt_for_a_hosted_redirect_is_not_loopback(
    api: AsyncClient, db: AsyncSession
) -> None:
    _, txn = await start_authorization(db, redirect=HOSTED_REDIRECT)
    body = (await api.get(f"{CONSENT}/{txn}")).json()
    assert body["redirect_host"] == "claude.ai"
    assert body["loopback"] is False


async def test_unnamed_client_is_labelled(api: AsyncClient, db: AsyncSession) -> None:
    _, txn = await start_authorization(db, name=None)
    body = (await api.get(f"{CONSENT}/{txn}")).json()
    assert body["client_name"] == "Unnamed client"


async def test_prompt_for_unknown_expired_or_consumed_txn_is_404(
    api: AsyncClient, db: AsyncSession
) -> None:
    unknown = "x" * 43
    resp = await api.get(f"{CONSENT}/{unknown}")
    assert resp.status_code == 404
    assert unknown not in resp.text

    _, expired = await start_authorization(db)
    await db.execute(
        update(OAuthAuthorizationRequest)
        .where(col(OAuthAuthorizationRequest.id) == hash_secret(expired))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()
    resp = await api.get(f"{CONSENT}/{expired}")
    assert resp.status_code == 404
    assert_no_secret(expired, resp.text)

    _, consumed = await start_authorization(db)
    approved = await api.post(
        CONSENT, json={"transaction_id": consumed, "decision": "approve"}
    )
    assert approved.status_code == 200
    resp = await api.get(f"{CONSENT}/{consumed}")
    assert resp.status_code == 404
    assert_no_secret(consumed, resp.text)


async def test_prompt_marks_a_user_without_mcp_use_ineligible(
    app: FastAPI, db: AsyncSession
) -> None:
    viewer = await make_user(db, "vic@yougotagift.com", role="viewer")
    as_user(app, viewer)
    _, txn = await start_authorization(db)
    async with client_for(app) as client:
        body = (await client.get(f"{CONSENT}/{txn}")).json()
    assert body["eligible"] is False
    assert body["ineligible_reason"] == "no_mcp_use"


async def test_approve_returns_the_registered_redirect_with_code_and_state(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    client_id, txn = await start_authorization(db)
    resp = await api.post(CONSENT, json={"transaction_id": txn, "decision": "approve"})
    assert resp.status_code == 200
    target = resp.json()["redirect_to"]
    got, registered = urlsplit(target), urlsplit(LOOPBACK_REDIRECT)
    assert (got.scheme, got.hostname, got.port, got.path) == (
        registered.scheme,
        registered.hostname,
        registered.port,
        registered.path,
    )
    assert query_param(target, "state") == "state-123"

    service = oauth_service(db)
    grant = await service.load_code(client_id, query_param(target, "code"))
    assert grant is not None
    assert grant.user_id == analyst.id  # bound to the bearer, not the body
    pair = await service.exchange_code(client_id, grant, always_eligible)
    assert pair.user_id == analyst.id


async def test_approve_without_mcp_use_is_403_with_reason_and_keeps_the_txn(
    app: FastAPI, db: AsyncSession
) -> None:
    viewer = await make_user(db, "vic@yougotagift.com", role="viewer")
    as_user(app, viewer)
    _, txn = await start_authorization(db)
    async with client_for(app) as client:
        refused = await client.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve"}
        )
        assert refused.status_code == 403
        assert refused.json()["detail"]["reason"] == "no_mcp_use"
        assert refused.json()["detail"]["message"]
        assert_no_secret(txn, refused.text)
        assert await _codes(db) == []

        viewer.role = "analyst"
        db.add(viewer)
        await db.commit()
        await bump(db)
        later = await client.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve"}
        )
    assert later.status_code == 200
    assert len(await _codes(db)) == 1


async def test_approve_twice_is_404(api: AsyncClient, db: AsyncSession) -> None:
    _, txn = await start_authorization(db)
    decision = {"transaction_id": txn, "decision": "approve"}
    assert (await api.post(CONSENT, json=decision)).status_code == 200
    again = await api.post(CONSENT, json=decision)
    assert again.status_code == 404
    assert_no_secret(txn, again.text)
    assert len(await _codes(db)) == 1


async def test_cannot_approve_someone_elses_txn_after_consumption(
    app: FastAPI, db: AsyncSession, analyst: User
) -> None:
    bob = await make_user(db, "bob@yougotagift.com", role="analyst")
    _, txn = await start_authorization(db)
    decision = {"transaction_id": txn, "decision": "approve"}

    as_user(app, analyst)
    async with client_for(app) as client:
        assert (await client.post(CONSENT, json=decision)).status_code == 200
    as_user(app, bob)
    async with client_for(app) as client:
        assert (await client.post(CONSENT, json=decision)).status_code == 404
        assert (
            await client.post(CONSENT, json={**decision, "decision": "deny"})
        ).status_code == 404

    codes = await _codes(db)
    assert [c.user_id for c in codes] == [analyst.id]


async def test_deny_redirects_with_access_denied_and_state(
    api: AsyncClient, db: AsyncSession, analyst: User
) -> None:
    _, txn = await start_authorization(db)
    resp = await api.post(CONSENT, json={"transaction_id": txn, "decision": "deny"})
    assert resp.status_code == 200
    target = resp.json()["redirect_to"]
    assert target.startswith(LOOPBACK_REDIRECT)
    assert query_param(target, "error") == "access_denied"
    assert query_param(target, "state") == "state-123"
    assert "code=" not in target
    assert await _codes(db) == []
    events = (
        (
            await db.execute(
                select(CredentialEvent).where(
                    col(CredentialEvent.event) == "consent.denied"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [e.user_id for e in events] == [analyst.id]


async def test_a_user_without_mcp_use_can_still_deny(
    app: FastAPI, db: AsyncSession
) -> None:
    viewer = await make_user(db, "vic@yougotagift.com", role="viewer")
    as_user(app, viewer)
    _, txn = await start_authorization(db)
    async with client_for(app) as client:
        resp = await client.post(
            CONSENT, json={"transaction_id": txn, "decision": "deny"}
        )
    assert resp.status_code == 200
    assert query_param(resp.json()["redirect_to"], "error") == "access_denied"


async def test_consent_needs_a_bearer(app: FastAPI, db: AsyncSession) -> None:
    _, txn = await start_authorization(db)
    real_door(app)
    async with client_for(app) as client:
        prompt = await client.get(f"{CONSENT}/{txn}")
        decided = await client.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve"}
        )
    assert prompt.status_code == 401
    assert decided.status_code == 401
    assert_no_secret(txn, prompt.text, decided.text)
    assert await _codes(db) == []


async def test_consent_ignores_cookies(app: FastAPI, db: AsyncSession) -> None:
    analyst = await make_user(
        db, "ana@yougotagift.com", role="analyst", firebase_uid="fb-ana"
    )
    _, txn = await start_authorization(db)
    real_door(app, FakeFirebase(analyst.email, analyst.firebase_uid or ""))
    async with client_for(app) as client:
        # The valid Firebase token, but in cookies only: a cross-site form post.
        client.cookies.set("session", "good")
        client.cookies.set("__session", "good")
        resp = await client.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve"}
        )
        assert resp.status_code == 401
        assert await _codes(db) == []
        client.cookies.clear()
        with_bearer = await client.post(
            CONSENT,
            json={"transaction_id": txn, "decision": "approve"},
            headers={"Authorization": "Bearer good"},
        )
    assert with_bearer.status_code == 200
    assert len(await _codes(db)) == 1


async def test_body_cannot_choose_client_redirect_or_user(
    api: AsyncClient, db: AsyncSession
) -> None:
    _, txn = await start_authorization(db)
    for extra in (
        {"client_id": "other"},
        {"redirect_uri": "https://evil.example/cb"},
        {"user_id": "00000000-0000-0000-0000-000000000000"},
    ):
        resp = await api.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve", **extra}
        )
        assert resp.status_code == 422
        assert_no_secret(txn, resp.text)  # validation errors never echo input
        assert "evil.example" not in resp.text
    assert await _codes(db) == []


async def test_disabled_user_and_non_company_account_get_403(
    app: FastAPI, db: AsyncSession
) -> None:
    """The identity door's own refusals reach the page as reason codes."""
    await make_user(
        db,
        "dee@yougotagift.com",
        role="analyst",
        status="disabled",
        firebase_uid="fb-dee",
    )
    await make_user(db, "robot@yougotagift.com", role="analyst", kind="service")
    _, txn = await start_authorization(db)
    cases = (
        (FakeFirebase("dee@yougotagift.com", "fb-dee"), "user_disabled"),
        (FakeFirebase("eve@gmail.com", "fb-eve"), "not_company_account"),
        (FakeFirebase("robot@yougotagift.com", "fb-robot"), "service_account"),
    )
    for firebase, reason in cases:
        real_door(app, firebase)
        async with client_for(app) as client:
            bearer = {"Authorization": "Bearer good"}
            prompt = await client.get(f"{CONSENT}/{txn}", headers=bearer)
            decided = await client.post(
                CONSENT,
                json={"transaction_id": txn, "decision": "approve"},
                headers=bearer,
            )
        for resp in (prompt, decided):
            assert resp.status_code == 403
            detail = resp.json()["detail"]
            assert detail["reason"] == reason
            assert detail["message"]
            assert_no_secret(txn, resp.text)
    assert await _codes(db) == []


async def test_consent_never_logs_the_txn_or_code(
    api: AsyncClient, db: AsyncSession
) -> None:
    _, txn = await start_authorization(db)
    with capture_logs() as logs:
        await api.get(f"{CONSENT}/{txn}")
        resp = await api.post(
            CONSENT, json={"transaction_id": txn, "decision": "approve"}
        )
        await api.post(CONSENT, json={"transaction_id": txn, "decision": "approve"})
    code = query_param(resp.json()["redirect_to"], "code")
    assert_no_secret(txn, logs)
    assert_no_secret(code, logs)

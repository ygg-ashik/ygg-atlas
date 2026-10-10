"""Startup: bootstrap admins, the capability catalog, MCP auth (no shared MCP user)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import col, select
from structlog.testing import capture_logs
from structlog.typing import EventDict

from app import main
from app.access.catalog import CAPABILITIES
from app.access.models import Capability, PolicyState, ScopeDimension
from app.atlas.registry import get_registry
from app.config import Settings
from app.identity import CredentialEvent, OAuthClient, OAuthService
from app.identity.api_tokens import EVENT_GC
from app.identity.models import User
from app.identity.repository import UserRepository
from app.mcp import prepare_mcp_auth


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
    # The shared-token MCP user is retired (D17): startup no longer creates it.
    assert await users.get_by_email("mcp-shared@atlas.internal") is None
    codes = {c.code for c in (await db.execute(select(Capability))).scalars()}
    assert codes
    assert set(CAPABILITIES) <= codes


async def test_apply_startup_increments_the_policy_version(db) -> None:
    before = await db.get(PolicyState, 1, populate_existing=True)
    assert before is not None
    version_before = before.policy_version

    await main.apply_startup()

    after = await db.get(PolicyState, 1, populate_existing=True)
    assert after is not None
    assert after.policy_version == version_before + 1


async def test_startup_never_re_elevates_a_demoted_bootstrap_admin(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    users = UserRepository(db)
    await users.save(User(email="boss@yougotagift.com", role="viewer"))
    monkeypatch.setenv("BOOTSTRAP_ADMINS", "boss@yougotagift.com")
    main.get_settings.cache_clear()
    try:
        await main.apply_startup()
    finally:
        main.get_settings.cache_clear()

    boss = await users.get_by_email("boss@yougotagift.com")
    assert boss is not None
    await db.refresh(boss)
    assert boss.role == "viewer"


async def test_startup_mirrors_scope_dimensions(db) -> None:
    await main.apply_startup()

    rows = (await db.execute(select(ScopeDimension))).scalars().all()
    mirrored = sorted((r.source, r.entity, r.dimension, r.self_attribute) for r in rows)
    expected = sorted(
        (source, entity, dimension, self_attribute)
        for source, entity, dimension, self_attribute, _ in (
            get_registry().scope_catalog()
        )
    )
    assert expected
    assert mirrored == expected


async def _production_startup_events(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> list[EventDict]:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.setenv("ATLAS_PSEUDONYM_KEY", key)
    main.get_settings.cache_clear()
    try:
        with capture_logs() as logs:
            await main.apply_startup()  # logs, never fails startup
    finally:
        main.get_settings.cache_clear()
    return [e for e in logs if e["event"] == "atlas.pseudonym_key_missing"]


@pytest.mark.parametrize("key", ["", "   "])
async def test_startup_logs_a_missing_pseudonym_key_in_production(
    db, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    missing = await _production_startup_events(monkeypatch, key)
    assert len(missing) == 1
    assert missing[0]["log_level"] == "error"


async def test_startup_accepts_a_set_pseudonym_key_in_production(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await _production_startup_events(monkeypatch, "k" * 64) == []


async def test_startup_is_quiet_about_the_key_outside_production(db) -> None:
    with capture_logs() as logs:
        await main.apply_startup()
    assert all(e["event"] != "atlas.pseudonym_key_missing" for e in logs)


async def test_startup_prepares_mcp_auth(db) -> None:
    stale = OAuthClient(
        client_id="idle-client",
        client_name="Old",
        redirect_uris=["http://localhost:1/cb"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code"],
        response_types=["code"],
        registered_at=datetime.now(UTC) - timedelta(days=200),
    )
    db.add(stale)
    await db.commit()

    with capture_logs() as logs:
        await main.apply_startup()

    ready = [e for e in logs if e["event"] == "mcp.auth_ready"]
    assert ready == [
        {
            "event": "mcp.auth_ready",
            "log_level": "info",
            "issuer": "http://localhost:8080/mcp-server",
            "resource": "http://localhost:8080/mcp-server/mcp",
            "hosted_connectors": False,
        }
    ]
    assert any(e["event"] == EVENT_GC for e in logs)
    gc_events = (
        await db.execute(
            select(CredentialEvent).where(col(CredentialEvent.event) == EVENT_GC)
        )
    ).scalars()
    assert len(list(gc_events)) == 1
    assert await db.get(OAuthClient, "idle-client", populate_existing=True) is None


async def test_mcp_auth_startup_never_raises(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_gc(_self: object) -> None:
        raise RuntimeError("database at 10.0.0.5 down")

    monkeypatch.setattr(OAuthService, "gc", broken_gc)
    with capture_logs() as logs:
        await main.apply_startup()

    failed = [e for e in logs if e["event"] == "mcp.credentials_gc_failed"]
    assert failed == [
        {
            "event": "mcp.credentials_gc_failed",
            "log_level": "error",
            "error": "RuntimeError",
        }
    ]


async def test_a_local_public_url_in_production_is_flagged(db) -> None:
    settings = Settings.model_validate(
        {
            "environment": "production",
            "firebase_project_id": "p",
            "auth_disabled": False,
        }
    )
    with capture_logs() as logs:
        await prepare_mcp_auth(db, settings)
    assert any(e["event"] == "mcp.public_url_local" for e in logs)

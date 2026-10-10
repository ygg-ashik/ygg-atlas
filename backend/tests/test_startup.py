"""Startup: bootstrap admins, the MCP service user, the capability catalog."""

import pytest
from sqlmodel import select
from structlog.testing import capture_logs
from structlog.typing import EventDict

from app import main
from app.access.catalog import CAPABILITIES
from app.access.models import Capability, PolicyState, ScopeDimension
from app.atlas.registry import get_registry
from app.identity.models import User
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

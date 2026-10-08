"""Startup: bootstrap admins, the MCP service user, the capability catalog."""

import pytest
from sqlmodel import select

from app import main
from app.access.catalog import CAPABILITIES
from app.access.models import Capability, PolicyState
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

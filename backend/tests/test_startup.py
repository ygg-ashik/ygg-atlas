"""Startup: bootstrap admins, the MCP service user, the capability catalog."""

import pytest
from sqlmodel import select

from app import main
from app.access.models import Capability
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
    assert (await db.execute(select(Capability))).scalars().first() is not None

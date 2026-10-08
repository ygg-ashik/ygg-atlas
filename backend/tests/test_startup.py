"""Startup applies bootstrap admins and no longer creates tables itself."""

import pytest

from app import main
from app.identity.repository import UserRepository


async def test_startup_applies_bootstrap_admins(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMINS", "boss@yougotagift.com")
    main.get_settings.cache_clear()
    try:
        await main.apply_bootstrap_admins()
    finally:
        main.get_settings.cache_clear()

    user = await UserRepository(db).get_by_email("boss@yougotagift.com")
    assert user is not None
    assert user.role == "admin"

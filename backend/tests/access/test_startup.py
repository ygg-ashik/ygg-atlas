import pytest
from sqlalchemy import delete
from sqlmodel import select

from app.access.catalog import CAPABILITIES, CHAT_USE
from app.access.errors import PolicyUnavailableError
from app.access.models import Capability, PolicyState
from app.access.repository import AccessRepository
from app.access.startup import prepare_access


async def _version(db) -> int:
    state = await db.get(PolicyState, 1, populate_existing=True)
    assert state is not None
    return state.policy_version


async def test_prepare_access_mirrors_the_catalog_and_bumps(db) -> None:
    db.add(Capability(code="old:thing", description="retired"))
    await db.commit()

    await prepare_access(db)

    rows = {c.code: c for c in (await db.execute(select(Capability))).scalars()}
    assert set(CAPABILITIES) <= set(rows)
    assert rows["old:thing"].deprecated
    assert not rows[CHAT_USE].deprecated
    assert await _version(db) == 2


async def test_prepare_access_recreates_a_missing_policy_row(db) -> None:
    await db.execute(delete(PolicyState))
    await db.commit()

    await prepare_access(db)

    assert await _version(db) == 2


# --- code review follow-ups -------------------------------------------------


async def test_sync_capabilities_undeprecates_a_returning_code(db) -> None:
    db.add(Capability(code=CHAT_USE, description="old", deprecated=True))
    await db.commit()

    await AccessRepository(db).sync_capabilities(CAPABILITIES)
    await db.commit()

    row = await db.get(Capability, CHAT_USE, populate_existing=True)
    assert row is not None
    assert not row.deprecated
    assert row.description == CAPABILITIES[CHAT_USE]


async def test_sync_capabilities_updates_the_description(db) -> None:
    db.add(Capability(code=CHAT_USE, description="stale description"))
    await db.commit()

    await AccessRepository(db).sync_capabilities(CAPABILITIES)
    await db.commit()

    row = await db.get(Capability, CHAT_USE, populate_existing=True)
    assert row is not None
    assert row.description == CAPABILITIES[CHAT_USE]


async def test_bump_version_raises_when_the_row_is_missing(db) -> None:
    await db.execute(delete(PolicyState))
    await db.commit()

    with pytest.raises(PolicyUnavailableError) as raised:
        await AccessRepository(db).bump_version()
    assert raised.value.reason == "policy_state has no row"

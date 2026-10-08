from sqlalchemy import delete
from sqlmodel import select

from app.access.catalog import CAPABILITIES, CHAT_USE
from app.access.models import Capability, PolicyState
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

"""The scope_dimensions mirror, synced from the registry at startup (D3.6, C8)."""

import pytest
from sqlmodel import col, select

from app.access import sync_scope_dimensions
from app.access.models import ScopeDimension
from tests.access_helpers import policy_version

ORDER = [
    ("demo", "order", "channel", None, "Sales channel"),
    ("demo", "order", "sales_rep", "rep_name", "Sales rep"),
]


async def _rows(db) -> list[tuple[str, str, str, str | None, str]]:
    stmt = select(ScopeDimension).order_by(
        col(ScopeDimension.source),
        col(ScopeDimension.entity),
        col(ScopeDimension.dimension),
    )
    return [
        (r.source, r.entity, r.dimension, r.self_attribute, r.description)
        for r in (
            await db.execute(stmt.execution_options(populate_existing=True))
        ).scalars()
    ]


async def test_sync_writes_the_catalog_without_bumping(db) -> None:
    before = await policy_version(db)

    await sync_scope_dimensions(db, ORDER)

    assert await _rows(db) == ORDER
    assert await policy_version(db) == before


async def test_sync_replaces_wholesale(db) -> None:
    await sync_scope_dimensions(db, ORDER)

    await sync_scope_dimensions(
        db,
        [
            ("demo", "order", "channel", None, "Channel, renamed"),
            ("demo", "customer", "segment", None, "Segment"),
        ],
    )

    assert await _rows(db) == [
        ("demo", "customer", "segment", None, "Segment"),
        ("demo", "order", "channel", None, "Channel, renamed"),
    ]


async def test_running_sync_twice_is_a_no_op(db) -> None:
    await sync_scope_dimensions(db, ORDER)
    first = {
        r.dimension: r.synced_at
        for r in (await db.execute(select(ScopeDimension))).scalars()
    }

    await sync_scope_dimensions(db, ORDER)

    assert await _rows(db) == ORDER
    second = {
        r.dimension: r.synced_at
        for r in (
            await db.execute(
                select(ScopeDimension).execution_options(populate_existing=True)
            )
        ).scalars()
    }
    assert second == first


async def test_an_empty_catalog_clears_the_mirror(db) -> None:
    await sync_scope_dimensions(db, ORDER)
    await sync_scope_dimensions(db, [])
    assert await _rows(db) == []


async def test_a_long_description_is_trimmed_to_the_column(db) -> None:
    await sync_scope_dimensions(db, [("demo", "order", "channel", None, "x" * 500)])
    ((*_, description),) = await _rows(db)
    assert description == "x" * 200


async def test_a_failed_sync_rolls_back_and_re_raises(db, monkeypatch) -> None:
    await sync_scope_dimensions(db, ORDER)

    async def failing_commit() -> None:
        msg = "database went away"
        raise RuntimeError(msg)

    monkeypatch.setattr(db, "commit", failing_commit)
    with pytest.raises(RuntimeError, match="database went away"):
        await sync_scope_dimensions(db, [("demo", "customer", "segment", None, "S")])
    monkeypatch.undo()

    assert await _rows(db) == ORDER  # rolled back: the staged rows are gone

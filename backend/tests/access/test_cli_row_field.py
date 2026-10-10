"""Row and field commands of the access CLI (phase 3, T7). Writes are via="cli"."""

import pytest
from sqlmodel import col, select

from app.access import cli
from app.access.models import LabelClassSetting, RbacChange, UserAttribute
from app.access.repository import AccessRepository
from tests.access_helpers import (
    add_grant,
    make_group,
    make_user,
    mirror_dimensions,
    seed_label_classes,
    set_attribute,
)

REVENUE = "demo/order/revenue"
DIMENSIONS = [
    ("deepsales", "ds_account", "csm", "csm_name"),
    ("deepsales", "ds_account", "country", None),
    ("demo", "order", "channel", None),
    ("demo", "order", "sales_rep", "rep_name"),
]


async def _changes(db, action: str) -> list[RbacChange]:
    stmt = select(RbacChange).where(col(RbacChange.action) == action)
    return list((await db.execute(stmt)).scalars().all())


# ---- grant --scope / --kind clearance ----------------------------------------


async def test_grant_with_a_self_scope_stores_it(db) -> None:
    await mirror_dimensions(db, DIMENSIONS)
    group = await make_group(db, "csm")

    code = await cli.run(
        ["grant", "group:csm", "allow", "deepsales/*", "--scope", "csm=$self"]
    )

    assert code == 0
    grants = await AccessRepository(db).list_grants("group", group.id)
    assert grants[0].row_scope == {"csm": ["$self"]}


async def test_scope_values_split_on_commas_and_repeats_merge(db) -> None:
    await mirror_dimensions(db, DIMENSIONS)
    group = await make_group(db, "gcc")

    code = await cli.run(
        [
            "grant",
            "group:gcc",
            "allow",
            "deepsales/ds_account/*",
            "--scope",
            "country=AE,SA",
            "--scope",
            "country=KW",
            "--scope",
            "csm=$self",
        ]
    )

    assert code == 0
    grants = await AccessRepository(db).list_grants("group", group.id)
    assert grants[0].row_scope == {"country": ["AE", "KW", "SA"], "csm": ["$self"]}
    created = await _changes(db, "grant.create")
    assert created[0].via == "cli"


@pytest.mark.parametrize("bad", ["country", "=AE", "country=", "country=,"])
async def test_a_malformed_scope_exits_1_with_a_message(
    db, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    await make_group(db, "gcc")

    code = await cli.run(["grant", "group:gcc", "allow", "*", "--scope", bad])

    assert code == 1
    assert "--scope" in capsys.readouterr().err


async def test_grant_a_clearance_with_kind(db) -> None:
    user = await make_user(db, "lead@yougotagift.com")

    code = await cli.run(
        [
            "grant",
            "user:lead@yougotagift.com",
            "allow",
            "fields:people_names",
            "--kind",
            "clearance",
            "--reason",
            "team lead",
        ]
    )

    assert code == 0
    grants = await AccessRepository(db).list_grants("user", user.id)
    assert (grants[0].target_kind, grants[0].target) == (
        "clearance",
        "fields:people_names",
    )


# ---- attributes --------------------------------------------------------------


async def test_set_attr_attrs_and_unset_attr(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    sara = await make_user(db, "sara@yougotagift.com")

    assert (
        await cli.run(["set-attr", "sara@yougotagift.com", "rep_name", "Sara K"]) == 0
    )
    set_out = capsys.readouterr().out
    assert "rep_name" in set_out
    assert "Sara K" not in set_out  # the confirmation never echoes the value
    row = await db.get(UserAttribute, (sara.id, "rep_name"), populate_existing=True)
    assert row is not None
    assert row.value == "Sara K"

    assert await cli.run(["attrs", "sara@yougotagift.com"]) == 0
    assert "rep_name = Sara K" in capsys.readouterr().out

    assert await cli.run(["unset-attr", "sara@yougotagift.com", "rep_name"]) == 0
    assert await cli.run(["attrs", "sara@yougotagift.com"]) == 0
    assert "no attributes" in capsys.readouterr().out

    sets = await _changes(db, "attribute.set")
    deletes = await _changes(db, "attribute.delete")
    assert [c.via for c in sets + deletes] == ["cli", "cli"]


async def test_attribute_errors_exit_1(db, capsys: pytest.CaptureFixture[str]) -> None:
    await make_user(db, "sara@yougotagift.com")

    assert await cli.run(["set-attr", "sara@yougotagift.com", "email", "x"]) == 1
    assert await cli.run(["unset-attr", "sara@yougotagift.com", "rep_name"]) == 1
    assert await cli.run(["attrs", "ghost@yougotagift.com"]) == 1
    assert "error:" in capsys.readouterr().err


# ---- label classes -----------------------------------------------------------


async def test_label_classes_and_label_class(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await seed_label_classes(db)

    assert await cli.run(["label-classes"]) == 0
    out = capsys.readouterr().out
    assert "business_name: pseudonymise" in out
    assert "person_name: suppress" in out

    assert (
        await cli.run(["label-class", "person_name", "bucket", "--bucket-size", "3"])
        == 0
    )
    row = await db.get(LabelClassSetting, "person_name", populate_existing=True)
    assert row is not None
    assert (row.mode, row.bucket_size) == ("bucket", 3)
    assert [c.via for c in await _changes(db, "label_class.update")] == ["cli"]


async def test_label_class_category_is_rejected(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["label-class", "category", "suppress"]) == 1
    assert "error:" in capsys.readouterr().err


# ---- scope dimensions and the access preview ---------------------------------


async def test_scope_dimensions_lists_the_mirror(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await mirror_dimensions(db, DIMENSIONS)

    assert await cli.run(["scope-dimensions"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(
        "demo/order" in ln and "sales_rep" in ln and "rep_name" in ln for ln in lines
    )
    assert any("demo/order" in ln and "channel" in ln for ln in lines)


async def test_access_prints_clearances_skipped_and_the_row_scope(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await mirror_dimensions(db, DIMENSIONS)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_grant(db, sara, REVENUE, row_scope={"channel": ["b2c"]})
    await add_grant(db, sara, "demo/order/*", row_scope={"sales_rep": ["$self"]})
    await add_grant(db, sara, "fields:people_names", kind="clearance")

    code = await cli.run(["access", "sara@yougotagift.com", "--resource", REVENUE])

    assert code == 0
    out = capsys.readouterr().out
    assert "clearances: fields:people_names" in out
    assert "skipped demo/order/*" in out
    assert "rep_name" in out
    assert "rows: channel in (b2c)" in out


async def test_access_shows_all_rows_and_a_resolved_self(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await mirror_dimensions(db, DIMENSIONS)
    sara = await make_user(db, "sara@yougotagift.com")
    await add_grant(db, sara, "demo/order/*", row_scope={"sales_rep": ["$self"]})
    await set_attribute(db, sara, "rep_name", "Sara K")

    assert await cli.run(["access", "sara@yougotagift.com", "--resource", REVENUE]) == 0
    out = capsys.readouterr().out
    assert "clearances: none" in out
    assert "rows: sales_rep in (Sara K)" in out

    await add_grant(db, sara, "demo/*")
    assert await cli.run(["access", "sara@yougotagift.com", "--resource", REVENUE]) == 0
    assert "rows: all" in capsys.readouterr().out

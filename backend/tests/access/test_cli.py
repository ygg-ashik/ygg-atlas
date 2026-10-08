import pytest
from sqlmodel import select

from app.access import cli
from app.access.models import RbacChange
from tests.access_helpers import make_group, make_user


async def test_bootstrap_an_admin_from_the_shell(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_group(db, "atlas-admins")
    await make_user(db, "ashik@yougotagift.com", role="admin")

    assert (
        await cli.run(
            ["add-member", "ashik@yougotagift.com", "atlas-admins", "--manager"]
        )
        == 0
    )
    assert (
        await cli.run(
            ["grant", "group:atlas-admins", "allow", "*", "--reason", "bootstrap"]
        )
        == 0
    )
    assert (
        await cli.run(
            ["access", "ashik@yougotagift.com", "--resource", "demo/order/revenue"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "is now a manager of atlas-admins" in out
    assert "allowed by grant" in out
    changes = (await db.execute(select(RbacChange))).scalars().all()
    assert {c.via for c in changes} == {"cli"}


async def test_errors_are_reported_not_raised(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["add-member", "ghost@yougotagift.com", "nowhere"]) == 1
    assert "error: No group named 'nowhere'" in capsys.readouterr().out


async def test_bad_subjects_and_patterns_fail(db) -> None:
    await make_group(db, "marketing")
    assert await cli.run(["grant", "team:marketing", "allow", "*"]) == 1
    assert await cli.run(["grant", "group:marketing", "allow", "demo order"]) == 1


async def test_groups_prints_the_tree(db, capsys: pytest.CaptureFixture[str]) -> None:
    parent = await make_group(db, "marketing")
    await make_group(db, "growth", parent=parent)

    assert await cli.run(["groups"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("marketing")
    assert lines[1].startswith("  growth")

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlmodel import col, select

from app.access import cli
from app.access.facts import as_utc
from app.access.models import PolicyState, RbacChange
from app.access.repository import AccessRepository
from tests.access_helpers import add_grant, add_member, make_group, make_user


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
    assert "error: No group named 'nowhere'" in capsys.readouterr().err


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


# ---- destructive commands (capture ids before any call expected to fail) ----


async def test_revoke_deletes_a_grant_and_is_audited(db) -> None:
    group = await make_group(db, "ops")
    grant = await add_grant(db, group, "*")
    grant_id = str(grant.id)  # captured before the call below could expire it

    assert await cli.run(["revoke", grant_id]) == 0

    changes = (
        (
            await db.execute(
                select(RbacChange).where(col(RbacChange.action) == "grant.revoke")
            )
        )
        .scalars()
        .all()
    )
    assert len(changes) == 1
    assert changes[0].object_id == grant_id


async def test_revoke_a_bad_uuid_fails(db) -> None:
    assert await cli.run(["revoke", "not-a-uuid"]) == 1


async def test_revoke_an_unknown_uuid_fails(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.run(["revoke", str(uuid4())]) == 1
    assert "No such grant" in capsys.readouterr().err


async def test_set_role_changes_the_role(db) -> None:
    user = await make_user(db, "someone@yougotagift.com", role="viewer")
    user_id = user.id  # captured in case of failure; also used after the call

    assert await cli.run(["set-role", "someone@yougotagift.com", "analyst"]) == 0

    refreshed = await AccessRepository(db).user(user_id)
    assert refreshed is not None
    assert refreshed.role == "analyst"


async def test_remove_member_succeeds(db) -> None:
    group = await make_group(db, "ops")
    user = await make_user(db, "someone@yougotagift.com")
    await add_member(db, group, user)
    group_id, user_id = group.id, user.id  # captured before the call below

    assert await cli.run(["remove-member", "someone@yougotagift.com", "ops"]) == 0

    assert await AccessRepository(db).member(group_id, user_id) is None


# ---- grant details: subject resolution, kind, expiry ------------------------


async def test_grant_resolves_a_mixed_case_email(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    user = await make_user(db, "ashik@yougotagift.com")

    assert (
        await cli.run(
            ["grant", "user:Ashik@YouGotAGift.COM", "allow", "*", "--reason", "r"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "to ashik@yougotagift.com" in out
    grants = await AccessRepository(db).list_grants("user", user.id)
    assert len(grants) == 1


async def test_grant_prints_the_group_name_not_the_raw_subject(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_group(db, "marketing")

    assert await cli.run(["grant", "group:marketing", "allow", "*"]) == 0

    assert "to marketing" in capsys.readouterr().out


async def test_grant_a_capability_with_kind(db) -> None:
    user = await make_user(db, "pilot@yougotagift.com")

    assert (
        await cli.run(
            [
                "grant",
                "user:pilot@yougotagift.com",
                "allow",
                "mcp:use",
                "--kind",
                "capability",
                "--reason",
                "pilot",
            ]
        )
        == 0
    )

    grants = await AccessRepository(db).list_grants("user", user.id)
    assert len(grants) == 1
    assert grants[0].target_kind == "capability"
    assert grants[0].target == "mcp:use"


async def test_expires_is_persisted_as_timezone_aware(db) -> None:
    group = await make_group(db, "temp")

    assert (
        await cli.run(
            [
                "grant",
                "group:temp",
                "allow",
                "*",
                "--expires",
                "2099-01-01T00:00:00+00:00",
            ]
        )
        == 0
    )

    grants = await AccessRepository(db).list_grants("group", group.id)
    assert len(grants) == 1
    # SQLite returns naive datetimes even for TIMESTAMP(timezone=True) columns
    # (facts.as_utc); every stored value is UTC end-to-end, so this is the
    # same aware instant that was parsed from "...+00:00".
    assert as_utc(grants[0].expires_at) == datetime(2099, 1, 1, tzinfo=UTC)


async def test_naive_expires_is_rejected_by_argparse(db) -> None:
    with pytest.raises(SystemExit) as exc_info:
        await cli.run(
            ["grant", "group:temp", "allow", "*", "--expires", "2099-01-01T00:00:00"]
        )
    assert exc_info.value.code == 2


async def test_grant_target_too_long_reports_a_clean_validation_message(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_group(db, "marketing")

    assert await cli.run(["grant", "group:marketing", "allow", "x" * 300]) == 1

    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "validation error" not in err  # the raw pydantic dump is not shown


# ---- access --resource validation -------------------------------------------


async def test_access_rejects_a_malformed_resource(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(db, "ashik@yougotagift.com")

    assert await cli.run(["access", "ashik@yougotagift.com", "--resource", "demo"]) == 1

    assert (
        "'demo' is not a resource path like demo/order/revenue"
        in capsys.readouterr().err
    )


# ---- fails closed when the policy can't be evaluated ------------------------


async def test_uninitialised_policy_gives_a_friendly_error(
    db, capsys: pytest.CaptureFixture[str]
) -> None:
    await make_user(db, "ashik@yougotagift.com")
    await db.execute(delete(PolicyState))
    await db.commit()

    assert await cli.run(["access", "ashik@yougotagift.com"]) == 1

    assert "atlas access isn't initialised yet" in capsys.readouterr().err

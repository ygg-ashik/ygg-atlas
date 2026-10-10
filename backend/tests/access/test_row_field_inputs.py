"""The repository and service feed row scopes, attributes, `$self` attributes and
label modes from the phase-3 tables into PolicyInputs (spec §5.5, §5.6)."""

from datetime import UTC, datetime
from uuid import uuid4

from structlog.testing import capture_logs

from app.access.cache import PolicyCache
from app.access.repository import AccessRepository
from app.access.service import AccessService
from tests.access_helpers import (
    add_grant,
    make_user,
    mirror_dimensions,
    seed_label_classes,
    set_attribute,
)

DEALS = "deepsales/ds_account/arr"


def _service(db) -> AccessService:
    return AccessService(AccessRepository(db), PolicyCache(), lambda: datetime.now(UTC))


async def test_grants_for_returns_row_scope(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await add_grant(db, user, "demo/*", row_scope={"channel": ["b2c", "b2b"]})
    await add_grant(db, user, "deepsales/*")

    facts = await AccessRepository(db).grants_for(user.id, [])

    scopes = {g.target: g.row_scope for g in facts}
    assert scopes == {"demo/*": {"channel": ["b2c", "b2b"]}, "deepsales/*": None}


async def test_attributes_include_the_builtins(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await set_attribute(db, user, "csm_name", "Sara Khan")
    await set_attribute(
        db, user, "email", "spoofed@example.com"
    )  # bypasses AccessAdmin
    other = await make_user(db, "omar@yougotagift.com")
    await set_attribute(db, other, "csm_name", "Omar")

    attributes = await AccessRepository(db).attributes_for(user.id)

    assert attributes == {
        "csm_name": "Sara Khan",
        "email": "sara@yougotagift.com",  # the built-in wins over a stored row
        "user_id": str(user.id),
    }


async def test_attributes_of_an_unknown_user_are_empty(db) -> None:
    assert await AccessRepository(db).attributes_for(uuid4()) == {}


async def test_label_modes_are_read(db) -> None:
    await seed_label_classes(db, person="bucket", business="suppress", bucket=3)

    modes = await AccessRepository(db).label_modes()

    assert modes == {"person_name": ("bucket", 3), "business_name": ("suppress", 3)}


async def test_label_modes_are_empty_without_settings(db) -> None:
    assert await AccessRepository(db).label_modes() == {}


async def test_self_attributes_come_from_the_mirror(db) -> None:
    await mirror_dimensions(
        db,
        [
            ("deepsales", "ds_account", "csm", "csm_name"),
            ("deepsales", "ds_revenue", "csm", "csm_name"),
            ("demo", "order", "channel", None),
            ("demo", "order", "rep", "rep_name"),
            ("demo", "customer", "rep", "rep_email"),  # disagrees: fail closed
        ],
    )

    with capture_logs() as logs:
        mapping = await AccessRepository(db).self_attributes()

    assert mapping == {"csm": "csm_name"}
    conflicts = [e for e in logs if e["event"] == "access.self_attribute_conflict"]
    assert [e["dimension"] for e in conflicts] == ["rep"]


async def test_inputs_reach_the_policy(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await mirror_dimensions(db, [("deepsales", "ds_account", "csm", "csm_name")])
    await set_attribute(db, user, "csm_name", "Sara Khan")
    await seed_label_classes(db)
    await add_grant(db, user, "deepsales/*", row_scope={"csm": ["$self"]})

    policy = await _service(db).policy_for_user(user.id)

    assert policy.row_scope(DEALS) == ({"csm": frozenset({"Sara Khan"})},)
    mode = policy.mask_mode("business_name")
    assert mode is not None
    assert (mode.mode, mode.bucket_size) == ("pseudonymise", 5)


async def test_an_attribute_change_reaches_the_next_policy(db) -> None:
    user = await make_user(db, "sara@yougotagift.com")
    await mirror_dimensions(db, [("deepsales", "ds_account", "csm", "csm_name")])
    await add_grant(db, user, "deepsales/*", row_scope={"csm": ["$self"]})
    service = _service(db)

    before = await service.policy_for_user(user.id)
    assert not before.allows(DEALS)  # no csm_name yet: the rule is skipped
    assert [s.reason for s in before.skipped] == ["missing attribute 'csm_name'"]

    await set_attribute(db, user, "csm_name", "Sara Khan")
    after = await service.policy_for_user(user.id)

    assert after.row_scope(DEALS) == ({"csm": frozenset({"Sara Khan"})},)

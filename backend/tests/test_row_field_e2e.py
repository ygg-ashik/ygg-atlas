"""Row and field controls end to end (spec §13).

The real path: grants and attributes in the database, `policy_for` through the
process-wide cache, `evaluate()`, the shipped demo registry and real AtlasTools.
Three principals ask the same `orders_by_rep` question and get three answers;
admin changes through AccessAdmin take effect on the very next call.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.access import policy_for, sync_scope_dimensions
from app.access.admin import Actor
from app.access.catalog import CLEARANCE_PEOPLE_NAMES
from app.access.models import Grant
from app.atlas import AtlasCaller, AtlasTools, get_registry
from app.atlas.tools import (
    _settings_pseudonym_key,  # pyright: ignore[reportPrivateUsage] -- the lazy key read (C13)
)
from app.config import get_settings
from app.identity.models import User
from app.identity.principal import Principal
from app.insights.schemas import ProvenanceOut
from tests.access_helpers import (
    add_grant,
    add_member,
    admin_for,
    make_group,
    make_user,
    policy_version,
    seed_label_classes,
    set_attribute,
)

ORDERS = "demo/order/*"


def _last_7_full_days() -> dict[str, str]:
    today = datetime.now(UTC).date()
    return {
        "start_date": (today - timedelta(days=7)).isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
    }


def _principal(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.email,
        role=user.role,
        kind=str(user.kind),
        tenant="ygg",
        auth_method="web",
    )


async def _tools(db, user: User) -> AtlasTools:
    """A fresh request: a new policy_for (shared cache) and real AtlasTools."""
    policy = await policy_for(db, _principal(user))
    caller = AtlasCaller(user_id=user.id, auth_method="web", surface="chat")
    return AtlasTools(caller, policy, db=db)


async def _breakdown(db, user: User) -> dict[str, Any]:
    tools = await _tools(db, user)
    return await tools.execute(
        "metric_breakdown",
        {"metric_id": "orders_by_rep", "limit": 10, **_last_7_full_days()},
    )


async def _total(db, user: User) -> dict[str, Any]:
    tools = await _tools(db, user)
    return await tools.execute(
        "query_metric", {"metric_id": "orders_by_rep", **_last_7_full_days()}
    )


async def _world(db) -> tuple[User, User, User, Grant]:
    """The mirror synced, label classes seeded, three principals, and the
    group clearance grant the first two hold."""
    await sync_scope_dimensions(db, get_registry().scope_catalog())
    await seed_label_classes(db, person="suppress")
    cleared = await make_group(db, "people-names")
    clearance = await add_grant(db, cleared, CLEARANCE_PEOPLE_NAMES, kind="clearance")

    manager = await make_user(db, "manager@yougotagift.com")
    await add_grant(db, manager, "*")
    await add_member(db, cleared, manager)

    rep = await make_user(db, "aisha@yougotagift.com")
    await add_grant(db, rep, ORDERS, row_scope={"sales_rep": ["$self"]})
    await set_attribute(db, rep, "rep_name", "Aisha Khan")
    await add_member(db, cleared, rep)

    analyst = await make_user(db, "analyst@yougotagift.com")
    await add_grant(db, analyst, "*")
    return manager, rep, analyst, clearance


def _rows(result: dict[str, Any]) -> dict[str, float]:
    assert "error" not in result, result
    return {row["label"]: row["value"] for row in result["rows"]}


async def test_three_principals_get_three_answers(db) -> None:
    manager, rep, analyst, _ = await _world(db)

    # 1. Unscoped and cleared: every rep, by name.
    full = await _breakdown(db, manager)
    assert _rows(full) == {"Aisha Khan": 21, "Omar Haddad": 14, "Lina Saab": 14}
    assert full["provenance"][0]["scope"] == {"restricted": False, "dimensions": []}
    assert full["provenance"][0].get("masking") is None

    # 2. Scoped to themself via $self, cleared: only their own row.
    own = await _breakdown(db, rep)
    assert _rows(own) == {"Aisha Khan": 21}
    provenance = own["provenance"][0]
    assert provenance["scope"]["restricted"] is True
    assert provenance["scope"]["dimensions"] == ["sales_rep"]
    # Dashboards keep scope and masking: ProvenanceOut doesn't drop them.
    out = ProvenanceOut.model_validate(provenance)
    assert out.scope is not None
    assert out.scope.restricted is True
    assert (await _total(db, rep))["value"] == 21

    # 3. Unscoped, uncleared: the names are suppressed, the total is not.
    hidden = await _breakdown(db, analyst)
    assert _rows(hidden) == {}
    assert hidden["suppressed_rows"] == 3
    assert hidden["provenance"][0]["masking"] == {
        "label_class": "person_name",
        "mode": "suppress",
    }
    out = ProvenanceOut.model_validate(hidden["provenance"][0])
    assert out.masking is not None
    assert out.masking.mode == "suppress"
    for name in ("Aisha", "Omar", "Lina"):
        assert name not in repr(hidden)
    assert (await _total(db, analyst))["value"] == 49


async def test_a_revoked_clearance_applies_on_the_next_call(db) -> None:
    manager, _, _, clearance = await _world(db)
    assert len(_rows(await _breakdown(db, manager))) == 3  # now cached
    before = await policy_version(db)

    await admin_for(db).revoke_grant(Actor.cli(), clearance.id)

    assert await policy_version(db) > before
    after = await _breakdown(db, manager)
    assert _rows(after) == {}
    assert after["suppressed_rows"] == 3


async def test_deleting_the_self_attribute_denies_the_scoped_grant(db) -> None:
    _, rep, _, _ = await _world(db)
    assert _rows(await _breakdown(db, rep)) == {"Aisha Khan": 21}

    await admin_for(db).delete_attribute(Actor.cli(), rep.id, "rep_name")

    denied = await _breakdown(db, rep)
    assert "isn't available" in denied["error"]
    assert "Aisha" not in repr(denied)


@pytest.mark.parametrize(("raw", "expected"), [("", ""), ("  ", ""), ("k1", "k1")])
def test_a_blank_pseudonym_key_reads_as_missing(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    """Whitespace is no key: masking then suppresses (fail closed)."""
    monkeypatch.setenv("ATLAS_PSEUDONYM_KEY", raw)
    get_settings.cache_clear()
    try:
        assert _settings_pseudonym_key() == expected
    finally:
        get_settings.cache_clear()

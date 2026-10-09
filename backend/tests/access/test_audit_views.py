"""Audit views (admin:audit): the paged change log, the decision log and the
deny summary. Keyset paging, filters, tenant isolation and the gates."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import admin as admin_module
from app.access.cursor import encode_cursor
from app.access.models import RbacChange
from app.access.schemas import GroupCreate
from app.identity.models import User
from app.main import app as asgi_app
from app.models.audit import AtlasAuditLog
from tests.access_helpers import actor_with, add_grant, admin_for, make_user

DEV = "dev@yougotagift.com"
CHANGES = "/api/v1/admin/rbac-changes"
DECISIONS = "/api/v1/admin/audit/decisions"
SUMMARY = "/api/v1/admin/audit/summary"
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest_asyncio.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        yield client


def _change(
    at: datetime,
    *,
    tenant: str = "ygg",
    actor: User | None = None,
    via: str = "api",
    action: str = "group.create",
    object_type: str = "group",
    object_id: str = "g1",
) -> RbacChange:
    return RbacChange(
        actor_user_id=actor.id if actor else None,
        via=via,
        tenant=tenant,
        action=action,
        object_type=object_type,
        object_id=object_id,
        at=at,
    )


def _decision(
    user: User | None,
    at: datetime,
    *,
    decision: str = "allow",
    deny_reason: str | None = None,
    surface: str = "chat",
    tool: str = "query_metric",
    auth_method: str | None = "firebase",
) -> AtlasAuditLog:
    return AtlasAuditLog(
        user_uid=str(user.id) if user else "legacy-uid",
        user_id=user.id if user else None,
        auth_method=auth_method,
        surface=surface,
        tool=tool,
        arguments={"metric": "revenue"},
        decision=decision,
        deny_reason=deny_reason,
        duration_ms=12,
        created_at=at,
    )


async def _save(db: AsyncSession, *rows: Any) -> None:
    db.add_all(rows)
    await db.commit()


async def _other_tenant_user(db: AsyncSession) -> User:
    other = User(email="eve@acme.example", display_name="Eve", tenant="acme")
    await _save(db, other)
    return other


async def _walk(api: AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        resp = await api.get(path, params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rows.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return rows


# ---- the change log ----------------------------------------------------------


async def test_changes_cursor_walks_250_rows_without_gaps_or_repeats(
    api: AsyncClient, db
) -> None:
    await make_user(db, DEV, role="admin")
    # Five rows share each timestamp, so the id tiebreak decides the order.
    rows = [_change(NOW - timedelta(minutes=i // 5)) for i in range(250)]
    await _save(db, *rows)

    walked = await _walk(api, CHANGES, limit=40)

    ids = [r["id"] for r in walked]
    assert len(ids) == 250
    assert set(ids) == {str(r.id) for r in rows}
    keys = [(r["at"], r["id"]) for r in walked]
    assert keys == sorted(keys, reverse=True)


async def test_changes_cursor_is_stable_under_new_inserts(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    original = [_change(NOW - timedelta(minutes=i + 1)) for i in range(30)]
    await _save(db, *original)

    first = (await api.get(CHANGES, params={"limit": 10})).json()
    await _save(db, *[_change(NOW + timedelta(seconds=i)) for i in range(5)])
    rest = await _walk(api, CHANGES, limit=10, cursor=first["next_cursor"])

    ids = [r["id"] for r in first["items"] + rest]
    assert sorted(ids) == sorted(str(r.id) for r in original)


async def test_changes_filters(api: AsyncClient, db) -> None:
    dev = await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    old = _change(
        NOW - timedelta(days=3),
        actor=sara,
        action="grant.create",
        object_type="grant",
        object_id="x1",
    )
    mid = _change(
        NOW - timedelta(days=2),
        actor=dev,
        action="member.put",
        object_type="group",
        object_id="g2",
    )
    new = _change(
        NOW - timedelta(days=1),
        actor=dev,
        action="group.create",
        object_type="group",
        object_id="g3",
    )
    await _save(db, old, mid, new)

    async def ids(**params: Any) -> list[str]:
        resp = await api.get(CHANGES, params=params)
        assert resp.status_code == 200, resp.text
        return [r["id"] for r in resp.json()["items"]]

    assert await ids(actor_user_id=str(sara.id)) == [str(old.id)]
    assert await ids(object_type="group") == [str(new.id), str(mid.id)]
    assert await ids(action="member.put") == [str(mid.id)]
    assert await ids(object_id="g3") == [str(new.id)]
    since = (NOW - timedelta(days=2)).isoformat()
    until = (NOW - timedelta(days=1)).isoformat()
    assert await ids(since=since) == [str(new.id), str(mid.id)]
    assert await ids(until=until) == [str(mid.id), str(old.id)]
    assert await ids(since=since, until=until) == [str(mid.id)]
    assert await ids(
        actor_user_id=str(dev.id), object_type="group", object_id="g2"
    ) == [str(mid.id)]
    assert await ids(actor_user_id=str(sara.id), object_type="group") == []


async def test_changes_carry_the_actor_ref(db) -> None:
    actor = await actor_with(db)
    admin = admin_for(db)
    await admin.create_group(actor, GroupCreate(name="growth"))
    await _save(db, _change(NOW - timedelta(days=1), via="cli"))

    page = await admin.list_changes(actor)

    by_via = {c.via: c for c in page.items}
    api_ref = by_via["api"].actor
    assert api_ref is not None
    assert api_ref.email.startswith("admin-")
    assert by_via["cli"].actor is None
    assert page.next_cursor is None


async def test_changes_actor_ref_never_crosses_tenants(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    other = await _other_tenant_user(db)
    await _save(db, _change(NOW, actor=other))

    items = (await api.get(CHANGES)).json()["items"]

    assert items[0]["actor_user_id"] == str(other.id)
    assert items[0]["actor"] is None


# ---- the decision log --------------------------------------------------------


async def test_decisions_exclude_null_user_and_other_tenants(
    api: AsyncClient, db
) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    other = await _other_tenant_user(db)
    mine = _decision(sara, NOW)
    await _save(db, mine, _decision(None, NOW), _decision(other, NOW, decision="deny"))

    items = (await api.get(DECISIONS)).json()["items"]

    assert [i["id"] for i in items] == [str(mine.id)]
    assert items[0]["user"] == {
        "user_id": str(sara.id),
        "email": "sara@yougotagift.com",
        "display_name": "",
    }
    assert items[0]["arguments"] == {"metric": "revenue"}
    assert items[0]["decision"] == "allow"


async def test_decisions_filters_and_deny_only(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    omar = await make_user(db, "omar@yougotagift.com")
    a = _decision(sara, NOW - timedelta(days=3))
    b = _decision(
        sara,
        NOW - timedelta(days=2),
        decision="deny",
        deny_reason="no grant",
        surface="mcp",
        auth_method="pat",
    )
    c = _decision(
        omar,
        NOW - timedelta(days=1),
        decision="deny",
        deny_reason="no grant",
        tool="query_funnel",
    )
    await _save(db, a, b, c)

    async def ids(**params: Any) -> list[str]:
        resp = await api.get(DECISIONS, params=params)
        assert resp.status_code == 200, resp.text
        return [r["id"] for r in resp.json()["items"]]

    assert await ids(decision="deny") == [str(c.id), str(b.id)]
    assert await ids(decision="allow") == [str(a.id)]
    assert await ids(user_id=str(sara.id)) == [str(b.id), str(a.id)]
    assert await ids(surface="mcp") == [str(b.id)]
    assert await ids(tool="query_funnel") == [str(c.id)]
    assert await ids(auth_method="pat") == [str(b.id)]
    since = (NOW - timedelta(days=2)).isoformat()
    until = (NOW - timedelta(days=1)).isoformat()
    assert await ids(since=since, until=until) == [str(b.id)]
    assert await ids(user_id=str(sara.id), decision="deny") == [str(b.id)]
    assert (await api.get(DECISIONS, params={"decision": "maybe"})).status_code == 422


async def test_decisions_cursor_walks_every_row(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    rows = [_decision(sara, NOW - timedelta(minutes=i // 4)) for i in range(45)]
    await _save(db, *rows)

    walked = await _walk(api, DECISIONS, limit=10)

    assert sorted(r["id"] for r in walked) == sorted(str(r.id) for r in rows)


async def test_cursor_naming_another_tenants_row_returns_only_own_rows(
    api: AsyncClient, db
) -> None:
    await make_user(db, DEV, role="admin")
    sara = await make_user(db, "sara@yougotagift.com")
    other = await _other_tenant_user(db)
    own_changes = [_change(NOW - timedelta(minutes=i)) for i in range(1, 6)]
    own_decisions = [_decision(sara, NOW - timedelta(minutes=i)) for i in range(1, 6)]
    foreign_change = _change(NOW - timedelta(seconds=150), tenant="acme")
    foreign_decision = _decision(other, NOW - timedelta(seconds=150))
    foreign_older = [
        _change(NOW - timedelta(minutes=10), tenant="acme"),
        _decision(other, NOW - timedelta(minutes=10)),
    ]
    await _save(
        db,
        *own_changes,
        *own_decisions,
        foreign_change,
        foreign_decision,
        *foreign_older,
    )

    for path, foreign, own in (
        (CHANGES, foreign_change, own_changes),
        (DECISIONS, foreign_decision, own_decisions),
    ):
        moment = foreign.at if isinstance(foreign, RbacChange) else foreign.created_at
        cursor = encode_cursor(moment.isoformat(), foreign.id)
        items = (await api.get(path, params={"cursor": cursor})).json()["items"]
        # Positioned after 2.5 minutes ago: only own rows 3, 4 and 5 minutes old.
        assert [i["id"] for i in items] == [str(r.id) for r in own[2:]]


async def test_tampered_cursor_is_422(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    naive = encode_cursor("2026-10-01T10:00:00", UUID(int=1))
    for path in (CHANGES, DECISIONS):
        for cursor in ("tampered!", "x" * 600, "bm9wZQ", naive):
            resp = await api.get(path, params={"cursor": cursor})
            assert resp.status_code == 422, (path, cursor)
            if len(cursor) <= 512:
                assert resp.json()["detail"] == (
                    "That page link is invalid; reload the list."
                ), (path, cursor)


# ---- the summary -------------------------------------------------------------


async def test_summary_counts_per_day_and_tops(
    api: AsyncClient, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fixed clock: the window is computed from "now", so a real clock could
    # cross UTC midnight between inserting the rows and asking for the summary.
    clock = datetime(2026, 10, 9, 22, 30, tzinfo=UTC)
    monkeypatch.setattr(admin_module, "_utcnow", lambda: clock)
    await make_user(db, DEV, role="admin")
    sara = User(email="sara@yougotagift.com", display_name="Sara Ali")
    omar = User(email="omar@yougotagift.com", display_name="Omar")
    other = await _other_tenant_user(db)
    await _save(db, sara, omar)
    today = clock.replace(hour=0, minute=0, second=1)
    yesterday = today - timedelta(days=1)
    window_start = datetime(2026, 10, 3, tzinfo=UTC)  # 7 UTC days incl. today
    await _save(
        db,
        _decision(sara, today),
        _decision(sara, today, decision="deny", deny_reason="no grant"),
        _decision(omar, today, decision="deny", deny_reason="no grant"),
        _decision(sara, yesterday, decision="deny", deny_reason="row scope"),
        _decision(sara, yesterday, decision="deny", deny_reason=None),
        _decision(None, today, decision="deny", deny_reason="no grant"),
        _decision(other, today, decision="deny", deny_reason="acme only"),
        _decision(
            sara, today - timedelta(days=40), decision="deny", deny_reason="ancient"
        ),
        _decision(omar, window_start),
        _decision(omar, window_start - timedelta(seconds=1), decision="deny"),
    )

    resp = await api.get(SUMMARY, params={"days": 7})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    per_day = body["per_day"]
    assert [d["date"] for d in per_day] == [
        (today.date() - timedelta(days=6 - i)).isoformat() for i in range(7)
    ]
    assert date.fromisoformat(per_day[-1]["date"]) == today.date()
    assert per_day[-1] == {"date": today.date().isoformat(), "allow": 1, "deny": 2}
    assert per_day[-2] == {"date": yesterday.date().isoformat(), "allow": 0, "deny": 2}
    assert per_day[0] == {"date": "2026-10-03", "allow": 1, "deny": 0}
    assert all(d["allow"] == d["deny"] == 0 for d in per_day[1:-2])
    assert body["top_deny_reasons"] == [
        {"reason": "no grant", "count": 2},
        {"reason": "row scope", "count": 1},
        {"reason": "unspecified", "count": 1},
    ]
    assert body["top_denied_users"] == [
        {"user_id": str(sara.id), "display_name": "Sara Ali", "count": 3},
        {"user_id": str(omar.id), "display_name": "Omar", "count": 1},
    ]
    assert "email" not in str(body)

    month = (await api.get(SUMMARY, params={"days": 30})).json()
    assert len(month["per_day"]) == 30


async def test_summary_days_must_be_7_or_30(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    for days in (0, 1, 14, 31):
        resp = await api.get(SUMMARY, params={"days": days})
        assert resp.status_code == 422, days


# ---- gates -------------------------------------------------------------------


async def test_audit_views_need_admin_audit(api: AsyncClient, db) -> None:
    dev = await make_user(db, DEV, role="builder")
    for path in (CHANGES, DECISIONS, f"{SUMMARY}?days=7"):
        resp = await api.get(path)
        assert resp.status_code == 403, path
        assert "admin:audit" in resp.json()["detail"]

    await add_grant(db, dev, "admin:users", kind="capability")
    for path in (CHANGES, DECISIONS, f"{SUMMARY}?days=7"):
        assert (await api.get(path)).status_code == 403, path


async def test_limit_bounds(api: AsyncClient, db) -> None:
    await make_user(db, DEV, role="admin")
    for path in (CHANGES, DECISIONS):
        for limit in (0, 201):
            resp = await api.get(path, params={"limit": limit})
            assert resp.status_code == 422, (path, limit)
        assert (await api.get(path, params={"limit": 200})).status_code == 200

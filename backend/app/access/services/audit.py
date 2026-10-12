"""Audit views (admin:audit): the access-change log, atlas tool decisions and
the allow/deny summary."""

from datetime import UTC, datetime, time, timedelta
from typing import Final, Literal

from app.access.actor import Actor
from app.access.catalog import ADMIN_AUDIT
from app.access.cursor import time_page
from app.access.repositories import AccessRepository
from app.access.schemas import (
    ActorRefOut,
    AuditDecisionOut,
    AuditSummaryOut,
    AuditUserOut,
    ChangeOut,
    ChangeQuery,
    DayCountOut,
    DecisionQuery,
    Page,
    ReasonCountOut,
    UserCountOut,
)
from app.access.services.paging import page_position
from app.identity import User
from app.models.audit import AtlasAuditLog

_ALL_CHANGES: Final = ChangeQuery()
_ALL_DECISIONS: Final = DecisionQuery()
_TOP: Final = 5  # top deny reasons and denied users in the summary
_NO_REASON: Final = "unspecified"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_ref(user: User | None) -> ActorRefOut | None:
    if user is None:
        return None
    return ActorRefOut(display_name=user.display_name, email=user.email)


def _decision_out(entry: AtlasAuditLog, user: User) -> AuditDecisionOut:
    # The owner keys are replaced by the user ref; the session id stays private.
    fields = entry.model_dump(exclude={"user_uid", "user_id", "session_id"})
    user_ref = AuditUserOut(
        user_id=user.id, email=user.email, display_name=user.display_name
    )
    return AuditDecisionOut.model_validate({**fields, "user": user_ref})


class AuditService:
    """Read-only audit views."""

    def __init__(self, repo: AccessRepository) -> None:
        self._repo = repo

    async def list_changes(
        self, actor: Actor, query: ChangeQuery = _ALL_CHANGES
    ) -> Page[ChangeOut]:
        """The tenant's access-change log, newest first (keyset on (at, id))."""
        actor.require(ADMIN_AUDIT)
        rows = await self._repo.audit.list_changes(
            actor.tenant, query, page_position(query.cursor)
        )
        page, next_cursor = time_page(rows, query.limit, lambda r: (r[0].at, r[0].id))
        items = [
            ChangeOut.model_validate({**change.model_dump(), "actor": _actor_ref(user)})
            for change, user in page
        ]
        return Page[ChangeOut](items=items, next_cursor=next_cursor)

    async def list_decisions(
        self, actor: Actor, query: DecisionQuery = _ALL_DECISIONS
    ) -> Page[AuditDecisionOut]:
        """The tenant's atlas tool decisions, newest first (keyset on
        (created_at, id)); rows with no user are never listed."""
        actor.require(ADMIN_AUDIT)
        rows = await self._repo.audit.list_decisions(
            actor.tenant, query, page_position(query.cursor)
        )
        page, next_cursor = time_page(
            rows, query.limit, lambda r: (r[0].created_at, r[0].id)
        )
        items = [_decision_out(entry, user) for entry, user in page]
        return Page[AuditDecisionOut](items=items, next_cursor=next_cursor)

    async def audit_summary(
        self, actor: Actor, days: Literal[7, 30]
    ) -> AuditSummaryOut:
        """Allow/deny per UTC day over the last `days` days (today included,
        zero-filled), plus the top deny reasons and the most-denied users."""
        actor.require(ADMIN_AUDIT)
        today = _utcnow().date()
        first = today - timedelta(days=days - 1)
        since = datetime.combine(first, time.min, tzinfo=UTC)
        counts = {
            (day, decision): n
            for day, decision, n in await self._repo.audit.decision_counts_by_day(
                actor.tenant, since
            )
        }
        per_day = [
            DayCountOut(
                date=day,
                allow=counts.get((day, "allow"), 0),
                deny=counts.get((day, "deny"), 0),
            )
            for day in (first + timedelta(days=i) for i in range(days))
        ]
        reasons = await self._repo.audit.top_deny_reasons(actor.tenant, since, _TOP)
        users = await self._repo.audit.top_denied_users(actor.tenant, since, _TOP)
        return AuditSummaryOut(
            days=days,
            per_day=per_day,
            top_deny_reasons=[
                ReasonCountOut(reason=reason or _NO_REASON, count=n)
                for reason, n in reasons
            ],
            top_denied_users=[
                UserCountOut(user_id=uid, display_name=name, count=n)
                for uid, name, n in users
            ],
        )

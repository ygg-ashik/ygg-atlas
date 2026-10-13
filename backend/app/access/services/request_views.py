"""How access requests are shown: one `AccessRequestOut` per row, with the
group's name as the target label and the decider's display name."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from app.access.errors import NotFoundError
from app.access.facts import as_utc
from app.access.models import AccessRequest
from app.access.repositories import AccessRepository
from app.access.schemas import AccessRequestOut, DeciderOut, RequesterOut
from app.access.services.request_rules import KIND_GROUP, NO_SUCH_REQUEST, PENDING
from app.identity import User

CLI_DECIDER: Final = "atlas CLI"


def _aware(moment: datetime) -> datetime:
    """A stored timestamp as UTC-aware (SQLite returns naive UTC)."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class RequestViews:
    """Shapes requests for the requester's and the deciders' views."""

    def __init__(self, repo: AccessRepository) -> None:
        self._repo = repo

    async def reloaded(
        self, request_id: UUID, *, with_requester: bool = False
    ) -> AccessRequestOut:
        request = await self._repo.requests.request(request_id)
        if request is None:  # pragma: no cover - committed just before
            raise NotFoundError(NO_SUCH_REQUEST)
        return await self.out(request, with_requester=with_requester)

    async def out(
        self, request: AccessRequest, *, with_requester: bool = False
    ) -> AccessRequestOut:
        """One request; `with_requester` embeds the requester (decider views)."""
        requester = (
            await self._repo.users.user(request.user_id) if with_requester else None
        )
        [out] = await self.outs([(request, requester)], request.tenant)
        return out

    async def outs(
        self, rows: Sequence[tuple[AccessRequest, User | None]], tenant: str
    ) -> list[AccessRequestOut]:
        """Shape requests; `requester` is set only where a row carries one
        (admin views)."""
        groups = await self._repo.groups.tenant_groups(tenant)
        deciders = await self._repo.users.users_by_id(
            r.decided_by for r, _ in rows if r.decided_by is not None
        )
        outs: list[AccessRequestOut] = []
        for request, requester in rows:
            label = request.target
            if request.kind == KIND_GROUP:
                try:
                    group = groups.get(UUID(request.target))
                except ValueError:
                    group = None
                label = group.name if group is not None else request.target
            decided_by = None
            if request.status != PENDING:
                decider = (
                    None
                    if request.decided_by is None
                    else deciders.get(request.decided_by)
                )
                decided_by = DeciderOut(
                    user_id=request.decided_by,
                    display_name=(
                        CLI_DECIDER
                        if request.decided_by is None
                        else (decider.display_name if decider is not None else "")
                    ),
                )
            outs.append(
                AccessRequestOut(
                    id=request.id,
                    kind=request.kind,
                    target=request.target,
                    target_label=label,
                    note=request.note,
                    status=request.status,
                    created_at=_aware(request.created_at),
                    decided_by=decided_by,
                    decided_at=as_utc(request.decided_at),
                    decision_note=request.decision_note,
                    requester=None
                    if requester is None
                    else RequesterOut(
                        user_id=requester.id,
                        email=requester.email,
                        display_name=requester.display_name,
                        role=requester.role,
                    ),
                )
            )
        return outs

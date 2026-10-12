"""Group membership routes, and the add-member search."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.schemas import MemberCandidateOut, MemberOut, MemberPut
from app.access.services import AccessAdmin

router = APIRouter()


@router.get(
    "/admin/groups/{group_id}/member-candidates",
    response_model=list[MemberCandidateOut],
)
async def member_candidates(
    group_id: UUID,
    q: str = Query(max_length=200),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[MemberCandidateOut]:
    return await admin.members.member_candidates(actor, group_id, q)


@router.get("/admin/groups/{group_id}/members", response_model=list[MemberOut])
async def list_members(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[MemberOut]:
    return await admin.members.list_members(actor, group_id)


@router.put("/admin/groups/{group_id}/members/{user_id}", response_model=MemberOut)
async def put_member(
    group_id: UUID,
    user_id: UUID,
    payload: MemberPut,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> MemberOut:
    return await admin.members.put_member(actor, group_id, user_id, payload.standing)


@router.delete("/admin/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: UUID,
    user_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.members.remove_member(actor, group_id, user_id)

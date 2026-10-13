"""Group administration routes."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.schemas import GroupCreate, GroupDetailOut, GroupOut, GroupUpdate
from app.access.services import AccessAdmin

router = APIRouter()


@router.get("/admin/groups", response_model=list[GroupOut])
async def list_groups(
    actor: Actor = Depends(get_actor), admin: AccessAdmin = Depends(get_access_admin)
) -> list[GroupOut]:
    return [GroupOut.model_validate(g) for g in await admin.groups.list_groups(actor)]


@router.post("/admin/groups", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(await admin.groups.create_group(actor, payload))


@router.get("/admin/groups/{group_id}", response_model=GroupDetailOut)
async def group_detail(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupDetailOut:
    return await admin.groups.group_detail(actor, group_id)


@router.patch("/admin/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(
        await admin.groups.update_group(actor, group_id, payload)
    )


@router.delete("/admin/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.groups.delete_group(actor, group_id)

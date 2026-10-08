"""Access routes. Thin: resolve the caller, call a service, return a schema."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.admin import AccessAdmin, Actor
from app.access.dependencies import (
    get_access_admin,
    get_access_service,
    get_actor,
    get_policy,
)
from app.access.policy import Policy
from app.access.schemas import (
    CatalogOut,
    ChangeOut,
    EffectiveAccessOut,
    GrantCreate,
    GrantOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    MeAccessOut,
    MemberOut,
    MemberPut,
    UserOut,
    UserUpdate,
)
from app.access.service import AccessService
from app.identity import Principal, get_principal

router = APIRouter(prefix="/api/v1", tags=["access"])


@router.get("/me/access", response_model=MeAccessOut)
async def my_access(
    policy: Policy = Depends(get_policy),
    service: AccessService = Depends(get_access_service),
) -> MeAccessOut:
    return await service.describe(policy)


@router.get("/meta/capabilities", response_model=CatalogOut)
async def capability_catalog(
    _principal: Principal = Depends(get_principal),
) -> CatalogOut:
    return CatalogOut.build()


# ---- administration (spec §10; UI in phase 5) -------------------------------


@router.get("/admin/groups", response_model=list[GroupOut])
async def list_groups(
    actor: Actor = Depends(get_actor), admin: AccessAdmin = Depends(get_access_admin)
) -> list[GroupOut]:
    return [GroupOut.model_validate(g) for g in await admin.list_groups(actor)]


@router.post("/admin/groups", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(await admin.create_group(actor, payload))


@router.patch("/admin/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GroupOut:
    return GroupOut.model_validate(await admin.update_group(actor, group_id, payload))


@router.delete("/admin/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.delete_group(actor, group_id)


@router.get("/admin/groups/{group_id}/members", response_model=list[MemberOut])
async def list_members(
    group_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[MemberOut]:
    return await admin.list_members(actor, group_id)


@router.put("/admin/groups/{group_id}/members/{user_id}", response_model=MemberOut)
async def put_member(
    group_id: UUID,
    user_id: UUID,
    payload: MemberPut,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> MemberOut:
    return await admin.put_member(actor, group_id, user_id, payload.standing)


@router.delete("/admin/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: UUID,
    user_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.remove_member(actor, group_id, user_id)


@router.get("/admin/grants", response_model=list[GrantOut])
async def list_grants(
    subject_type: Literal["group", "user"],
    subject_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[GrantOut]:
    grants = await admin.list_grants(actor, subject_type, subject_id)
    return [GrantOut.model_validate(g) for g in grants]


@router.post("/admin/grants", response_model=GrantOut, status_code=201)
async def create_grant(
    payload: GrantCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GrantOut:
    return GrantOut.model_validate(await admin.create_grant(actor, payload))


@router.delete("/admin/grants/{grant_id}", status_code=204)
async def revoke_grant(
    grant_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.revoke_grant(actor, grant_id)


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await admin.list_users(actor, q, limit)]


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> UserOut:
    return UserOut.model_validate(await admin.update_user(actor, user_id, payload))


@router.get("/admin/users/{user_id}/access", response_model=EffectiveAccessOut)
async def user_access(
    user_id: UUID,
    resource: str | None = None,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> EffectiveAccessOut:
    policy = await admin.effective_access(actor, user_id)
    return EffectiveAccessOut.from_policy(policy, resource)


@router.get("/admin/rbac-changes", response_model=list[ChangeOut])
async def rbac_changes(
    limit: int = Query(100, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[ChangeOut]:
    return [ChangeOut.model_validate(c) for c in await admin.list_changes(actor, limit)]

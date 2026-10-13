"""User administration routes and the effective-access preview."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.errors import InvalidChangeError
from app.access.patterns import is_resource_path
from app.access.schemas import (
    EffectiveAccessOut,
    Page,
    UserDetailOut,
    UserOut,
    UserQuery,
    UserUpdate,
)
from app.access.services import AccessAdmin

router = APIRouter()


@router.get("/admin/users", response_model=Page[UserOut])
async def list_users(
    query: Annotated[UserQuery, Query()],
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> Page[UserOut]:
    return await admin.users.list_users(actor, query)


@router.get("/admin/users/{user_id}", response_model=UserDetailOut)
async def user_detail(
    user_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> UserDetailOut:
    return await admin.users.user_detail(actor, user_id)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> UserOut:
    return UserOut.model_validate(
        await admin.users.update_user(actor, user_id, payload)
    )


@router.get("/admin/users/{user_id}/access", response_model=EffectiveAccessOut)
async def user_access(
    user_id: UUID,
    resource: str | None = Query(None, min_length=1, max_length=200),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> EffectiveAccessOut:
    if resource is not None and not is_resource_path(resource):
        msg = f"'{resource}' is not a resource path like demo/order/revenue."
        raise InvalidChangeError(msg)
    policy = await admin.users.effective_access(actor, user_id)
    return EffectiveAccessOut.from_policy(policy, resource)

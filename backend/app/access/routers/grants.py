"""Grant administration routes."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.schemas import GrantCreate, GrantOut
from app.access.services import AccessAdmin

router = APIRouter()


@router.get("/admin/grants", response_model=list[GrantOut])
async def list_grants(
    subject_type: Literal["group", "user"],
    subject_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[GrantOut]:
    grants = await admin.grants.list_grants(actor, subject_type, subject_id)
    return [GrantOut.model_validate(g) for g in grants]


@router.post("/admin/grants", response_model=GrantOut, status_code=201)
async def create_grant(
    payload: GrantCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> GrantOut:
    return GrantOut.model_validate(await admin.grants.create_grant(actor, payload))


@router.delete("/admin/grants/{grant_id}", status_code=204)
async def revoke_grant(
    grant_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.grants.revoke_grant(actor, grant_id)

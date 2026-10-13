"""Row and field control routes: attributes, label classes, scope dimensions."""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.schemas import (
    AttributeOut,
    AttributePut,
    LabelClassOut,
    LabelClassPut,
    ScopeDimensionOut,
)
from app.access.services import AccessAdmin

router = APIRouter()


@router.get("/admin/users/{user_id}/attributes", response_model=list[AttributeOut])
async def list_attributes(
    user_id: UUID,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> list[AttributeOut]:
    rows = await admin.row_field.list_attributes(actor, user_id)
    return [AttributeOut.model_validate(a) for a in rows]


@router.put("/admin/users/{user_id}/attributes/{key}", response_model=AttributeOut)
async def put_attribute(
    user_id: UUID,
    key: str,
    payload: AttributePut,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> AttributeOut:
    row = await admin.row_field.set_attribute(actor, user_id, key, payload.value)
    return AttributeOut.model_validate(row)


@router.delete("/admin/users/{user_id}/attributes/{key}", status_code=204)
async def delete_attribute(
    user_id: UUID,
    key: str,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> None:
    await admin.row_field.delete_attribute(actor, user_id, key)


@router.get("/admin/label-classes", response_model=list[LabelClassOut])
async def list_label_classes(
    actor: Actor = Depends(get_actor), admin: AccessAdmin = Depends(get_access_admin)
) -> list[LabelClassOut]:
    rows = await admin.row_field.list_label_classes(actor)
    return [LabelClassOut.model_validate(c) for c in rows]


@router.put("/admin/label-classes/{label_class}", response_model=LabelClassOut)
async def put_label_class(
    label_class: str,
    payload: LabelClassPut,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> LabelClassOut:
    row = await admin.row_field.set_label_class(
        actor, label_class, payload.mode, payload.bucket_size
    )
    return LabelClassOut.model_validate(row)


@router.get("/meta/scope-dimensions", response_model=list[ScopeDimensionOut])
async def scope_dimensions(
    actor: Actor = Depends(get_actor), admin: AccessAdmin = Depends(get_access_admin)
) -> list[ScopeDimensionOut]:
    rows = await admin.row_field.list_scope_dimensions(actor)
    return [ScopeDimensionOut.model_validate(d) for d in rows]

"""Access routes, one router per resource. Thin: resolve the caller, call a
service, return a schema."""

from fastapi import APIRouter

from app.access.routers import (
    audit,
    grants,
    groups,
    me,
    members,
    meta,
    requests,
    row_field,
    users,
)

router = APIRouter(prefix="/api/v1", tags=["access"])
router.include_router(me.router)
router.include_router(meta.router)
router.include_router(groups.router)
router.include_router(members.router)
router.include_router(grants.router)
router.include_router(users.router)
router.include_router(audit.router)
router.include_router(requests.router)
router.include_router(row_field.router)

__all__ = ["router"]

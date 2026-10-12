"""Audit views: the access-change log, atlas decisions and the summary."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.access.actor import Actor
from app.access.dependencies import get_access_admin, get_actor
from app.access.errors import InvalidChangeError
from app.access.schemas import (
    AuditDecisionOut,
    AuditSummaryOut,
    ChangeOut,
    ChangeQuery,
    DecisionQuery,
    Page,
)
from app.access.services import AccessAdmin

router = APIRouter()

_SUMMARY_WINDOWS: dict[int, Literal[7, 30]] = {7: 7, 30: 30}


@router.get("/admin/rbac-changes", response_model=Page[ChangeOut])
async def rbac_changes(
    query: Annotated[ChangeQuery, Query()],
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> Page[ChangeOut]:
    return await admin.audit.list_changes(actor, query)


@router.get("/admin/audit/decisions", response_model=Page[AuditDecisionOut])
async def audit_decisions(
    query: Annotated[DecisionQuery, Query()],
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> Page[AuditDecisionOut]:
    return await admin.audit.list_decisions(actor, query)


@router.get("/admin/audit/summary", response_model=AuditSummaryOut)
async def audit_summary(
    days: int = 7,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> AuditSummaryOut:
    # A Literal[7, 30] query parameter refuses the string "7", so map it here.
    window = _SUMMARY_WINDOWS.get(days)
    if window is None:
        msg = "The summary covers 7 or 30 days."
        raise InvalidChangeError(msg)
    return await admin.audit.audit_summary(actor, window)

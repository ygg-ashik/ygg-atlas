"""Access routes. Thin: resolve the caller, call a service, return a schema."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.admin import AccessAdmin, Actor
from app.access.dependencies import (
    get_access_admin,
    get_access_requests,
    get_access_service,
    get_actor,
    get_policy,
)
from app.access.errors import InvalidChangeError
from app.access.patterns import is_resource_path
from app.access.policy import Policy
from app.access.requests import AccessRequests
from app.access.schemas import (
    AccessRequestCreate,
    AccessRequestOut,
    AuditDecisionOut,
    AuditSummaryOut,
    CatalogOut,
    ChangeOut,
    ChangeQuery,
    DecisionQuery,
    EffectiveAccessOut,
    GrantCreate,
    GrantOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    MeAccessOut,
    MemberOut,
    MemberPut,
    Page,
    RequestDecision,
    RequestOptionsOut,
    UserOut,
    UserUpdate,
)
from app.access.service import AccessService
from app.identity import Principal, get_principal

router = APIRouter(prefix="/api/v1", tags=["access"])

_SUMMARY_WINDOWS: dict[int, Literal[7, 30]] = {7: 7, 30: 30}


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
    q: str = Query("", max_length=100),
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
    resource: str | None = Query(None, min_length=1, max_length=200),
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> EffectiveAccessOut:
    if resource is not None and not is_resource_path(resource):
        msg = f"'{resource}' is not a resource path like demo/order/revenue."
        raise InvalidChangeError(msg)
    policy = await admin.effective_access(actor, user_id)
    return EffectiveAccessOut.from_policy(policy, resource)


@router.get("/admin/rbac-changes", response_model=Page[ChangeOut])
async def rbac_changes(
    query: Annotated[ChangeQuery, Query()],
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> Page[ChangeOut]:
    return await admin.list_changes(actor, query)


@router.get("/admin/audit/decisions", response_model=Page[AuditDecisionOut])
async def audit_decisions(
    query: Annotated[DecisionQuery, Query()],
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> Page[AuditDecisionOut]:
    return await admin.list_decisions(actor, query)


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
    return await admin.audit_summary(actor, window)


# ---- access requests (spec §3.2 step 4; phase 5) -----------------------------


@router.get("/me/requests", response_model=list[AccessRequestOut])
async def my_requests(
    policy: Policy = Depends(get_policy),
    requests: AccessRequests = Depends(get_access_requests),
) -> list[AccessRequestOut]:
    return await requests.list_own(policy)


@router.get("/me/requests/options", response_model=RequestOptionsOut)
async def request_options(
    resource: str = Query(min_length=1, max_length=200),
    policy: Policy = Depends(get_policy),
    requests: AccessRequests = Depends(get_access_requests),
) -> RequestOptionsOut:
    return await requests.options(policy, resource)


@router.post("/me/requests", response_model=AccessRequestOut, status_code=201)
async def create_request(
    payload: AccessRequestCreate,
    policy: Policy = Depends(get_policy),
    requests: AccessRequests = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.create(policy, payload)


@router.post("/me/requests/{request_id}/cancel", response_model=AccessRequestOut)
async def cancel_request(
    request_id: UUID,
    policy: Policy = Depends(get_policy),
    requests: AccessRequests = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.cancel(policy, request_id)


@router.get("/admin/requests", response_model=Page[AccessRequestOut])
async def decidable_requests(
    status: Literal["pending", "approved", "declined", "cancelled", "all"] = "pending",
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    requests: AccessRequests = Depends(get_access_requests),
) -> Page[AccessRequestOut]:
    wanted = None if status == "all" else status
    return await requests.list_decidable(actor, wanted, cursor, limit)


@router.post("/admin/requests/{request_id}/approve", response_model=AccessRequestOut)
async def approve_request(
    request_id: UUID,
    decision: RequestDecision,
    actor: Actor = Depends(get_actor),
    requests: AccessRequests = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.approve(actor, request_id, decision)


@router.post("/admin/requests/{request_id}/decline", response_model=AccessRequestOut)
async def decline_request(
    request_id: UUID,
    decision: RequestDecision,
    actor: Actor = Depends(get_actor),
    requests: AccessRequests = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.decline(actor, request_id, decision)

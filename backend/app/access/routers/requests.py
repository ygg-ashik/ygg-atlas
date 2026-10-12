"""Access request routes: the requester's own and the deciders' queue."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.access.actor import Actor
from app.access.dependencies import get_access_requests, get_actor, get_policy
from app.access.policy import Policy
from app.access.schemas import (
    AccessRequestCreate,
    AccessRequestOut,
    Page,
    RequestDecision,
    RequestOptionsOut,
)
from app.access.services import RequestService

router = APIRouter()


@router.get("/me/requests", response_model=list[AccessRequestOut])
async def my_requests(
    policy: Policy = Depends(get_policy),
    requests: RequestService = Depends(get_access_requests),
) -> list[AccessRequestOut]:
    return await requests.list_own(policy)


@router.get("/me/requests/options", response_model=RequestOptionsOut)
async def request_options(
    resource: str = Query(min_length=1, max_length=200),
    policy: Policy = Depends(get_policy),
    requests: RequestService = Depends(get_access_requests),
) -> RequestOptionsOut:
    return await requests.options(policy, resource)


@router.post("/me/requests", response_model=AccessRequestOut, status_code=201)
async def create_request(
    payload: AccessRequestCreate,
    policy: Policy = Depends(get_policy),
    requests: RequestService = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.create(policy, payload)


@router.post("/me/requests/{request_id}/cancel", response_model=AccessRequestOut)
async def cancel_request(
    request_id: UUID,
    policy: Policy = Depends(get_policy),
    requests: RequestService = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.cancel(policy, request_id)


@router.get("/admin/requests", response_model=Page[AccessRequestOut])
async def decidable_requests(
    status: Literal[
        "pending", "approved", "declined", "cancelled", "decided", "all"
    ] = "pending",
    user_id: UUID | None = None,
    cursor: str | None = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(get_actor),
    requests: RequestService = Depends(get_access_requests),
) -> Page[AccessRequestOut]:
    wanted = None if status == "all" else status
    return await requests.list_decidable(actor, wanted, cursor, limit, user_id=user_id)


@router.post("/admin/requests/{request_id}/approve", response_model=AccessRequestOut)
async def approve_request(
    request_id: UUID,
    decision: RequestDecision,
    actor: Actor = Depends(get_actor),
    requests: RequestService = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.approve(actor, request_id, decision)


@router.post("/admin/requests/{request_id}/decline", response_model=AccessRequestOut)
async def decline_request(
    request_id: UUID,
    decision: RequestDecision,
    actor: Actor = Depends(get_actor),
    requests: RequestService = Depends(get_access_requests),
) -> AccessRequestOut:
    return await requests.decline(actor, request_id, decision)

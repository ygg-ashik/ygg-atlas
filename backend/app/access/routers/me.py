"""The caller's own access."""

from fastapi import APIRouter, Depends

from app.access.dependencies import get_access_service, get_policy
from app.access.policy import Policy
from app.access.schemas import MeAccessOut
from app.access.service import AccessService

router = APIRouter()


@router.get("/me/access", response_model=MeAccessOut)
async def my_access(
    policy: Policy = Depends(get_policy),
    service: AccessService = Depends(get_access_service),
) -> MeAccessOut:
    return await service.describe(policy)

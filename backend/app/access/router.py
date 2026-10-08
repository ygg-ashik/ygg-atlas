"""Access routes. Thin: resolve the caller, call a service, return a schema."""

from fastapi import APIRouter, Depends

from app.access.dependencies import get_access_service, get_policy
from app.access.policy import Policy
from app.access.schemas import CatalogOut, MeAccessOut
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

"""The capability catalog."""

from fastapi import APIRouter, Depends

from app.access.schemas import CatalogOut
from app.identity import Principal, get_principal

router = APIRouter()


@router.get("/meta/capabilities", response_model=CatalogOut)
async def capability_catalog(
    _principal: Principal = Depends(get_principal),
) -> CatalogOut:
    return CatalogOut.build()

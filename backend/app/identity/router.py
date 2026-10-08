"""Identity routes. Thin: resolve the principal, return a schema."""

from fastapi import APIRouter, Depends

from app.identity.dependencies import get_principal
from app.identity.principal import Principal
from app.identity.schemas import MeOut

router = APIRouter(prefix="/api/v1", tags=["identity"])


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(get_principal)) -> MeOut:
    return MeOut.from_principal(principal)

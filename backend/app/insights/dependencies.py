"""FastAPI wiring for insights: the service runs as the caller, under their policy.

Kept out of router.py so the router never imports a database type (ARCHITECTURE §2.2).
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Policy, get_policy
from app.atlas import AtlasCaller, AtlasTools
from app.database import get_db
from app.identity import Principal, get_principal
from app.insights.service import InsightsService


def get_insights_service(
    principal: Principal = Depends(get_principal),
    policy: Policy = Depends(get_policy),
    db: AsyncSession = Depends(get_db),
) -> InsightsService:
    """Scope comes from the token (guardrail #4); every call is audited as "api"."""
    caller = AtlasCaller(
        user_id=principal.user_id, auth_method=principal.auth_method, surface="api"
    )
    return InsightsService(AtlasTools(caller, policy, db=db))

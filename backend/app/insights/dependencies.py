"""FastAPI wiring for insights: builds the service from the request's user and DB.

Kept out of router.py so the router never imports a database type (ARCHITECTURE §2.2).
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas import AtlasTools
from app.database import get_db
from app.insights.service import InsightsService
from app.middleware import AuthUser, get_current_user


def get_insights_service(
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsightsService:
    """Scope comes from the token (guardrail #4); every call is audited as "api"."""
    return InsightsService(AtlasTools(user_uid=user.uid, surface="api", db=db))

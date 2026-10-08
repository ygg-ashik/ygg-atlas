"""Identity: who is calling. Other modules import only from here."""

from app.identity.bootstrap import bootstrap_admins, ensure_service_user
from app.identity.dependencies import get_principal, get_token_verifier
from app.identity.models import User, UserKind, UserStatus
from app.identity.principal import Principal
from app.identity.router import router as identity_router
from app.identity.service import service_principal
from app.identity.tokens import TokenVerifier

__all__ = [
    "Principal",
    "TokenVerifier",
    "User",
    "UserKind",
    "UserStatus",
    "bootstrap_admins",
    "ensure_service_user",
    "get_principal",
    "get_token_verifier",
    "identity_router",
    "service_principal",
]

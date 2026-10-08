"""Identity: who is calling. Other modules import only from here."""

from app.identity.bootstrap import bootstrap_admins
from app.identity.dependencies import get_principal
from app.identity.principal import Principal
from app.identity.router import router as identity_router

__all__ = ["Principal", "bootstrap_admins", "get_principal", "identity_router"]

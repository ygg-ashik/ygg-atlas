"""Personal and service tokens, connected apps and the single bearer door.

Raw secrets exist only in `IssuedToken.raw`, once, and are never logged, stored or
put in a repr.
"""

from app.identity.credentials.bearer import (
    AuthenticatedBearer,
    authenticate_bearer,
    principal_for_user,
    tenant_of_user,
)
from app.identity.credentials.issuance import (
    SERVICE_ACCOUNT_DOMAIN,
    IssuedToken,
    service_account_email,
)
from app.identity.credentials.revocation import ConnectedApp
from app.identity.credentials.service import TokenService, revoke_user_tokens

__all__ = [
    "SERVICE_ACCOUNT_DOMAIN",
    "AuthenticatedBearer",
    "ConnectedApp",
    "IssuedToken",
    "TokenService",
    "authenticate_bearer",
    "principal_for_user",
    "revoke_user_tokens",
    "service_account_email",
    "tenant_of_user",
]

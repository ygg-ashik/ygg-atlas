"""Firebase ID-token verification. Scope comes from the token, never from the request body."""

from dataclasses import dataclass

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)
_firebase_initialized = False


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: str


def _verify_firebase_token(token: str, settings: Settings) -> AuthUser:
    global _firebase_initialized
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if not _firebase_initialized:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                options={"projectId": settings.firebase_project_id}
                if settings.firebase_project_id
                else None
            )
        _firebase_initialized = True

    decoded = fb_auth.verify_id_token(token)
    return AuthUser(uid=decoded["uid"], email=decoded.get("email", ""))


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    if settings.auth_disabled:
        return AuthUser(uid="dev-user", email=f"dev@{settings.allowed_email_domain}")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        user = _verify_firebase_token(credentials.credentials, settings)
    except Exception:
        logger.warning("auth.token_invalid")
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    domain = user.email.rsplit("@", 1)[-1].lower() if "@" in user.email else ""
    if domain != settings.allowed_email_domain.lower():
        logger.warning("auth.domain_rejected", email=user.email)
        raise HTTPException(status_code=403, detail="Unauthorized email domain")

    return user

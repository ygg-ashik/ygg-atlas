# pyright: basic
# Adapter over the untyped firebase_admin SDK; strict typing stops at this boundary.
"""The only module that talks to Firebase. Blocking SDK calls run in a thread."""

import asyncio
from functools import cache
from typing import Any

import firebase_admin
from firebase_admin import auth as fb_auth

from app.identity.errors import IdentityUnavailableError
from app.identity.tokens import InvalidTokenError, VerifiedToken


@cache
def _app(project_id: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        options = {"projectId": project_id} if project_id else None
        return firebase_admin.initialize_app(options=options)


class FirebaseVerifier:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def verify(self, token: str) -> VerifiedToken:
        try:
            claims: dict[str, Any] = await asyncio.to_thread(
                fb_auth.verify_id_token, token, _app(self._project_id)
            )
        except fb_auth.CertificateFetchError:
            msg = "Firebase signing certificates are unreachable"
            raise IdentityUnavailableError(msg) from None
        except (ValueError, fb_auth.InvalidIdTokenError) as exc:
            # The class name says why (expired, wrong project) without the token.
            raise InvalidTokenError(type(exc).__name__) from None
        firebase_claims = claims.get("firebase") or {}
        return VerifiedToken(
            uid=str(claims["uid"]),
            email=str(claims.get("email", "")).strip().lower(),
            email_verified=bool(claims.get("email_verified", False)),
            name=str(claims.get("name", "")),
            auth_time=int(claims.get("auth_time", 0)),
            sign_in_provider=str(firebase_claims.get("sign_in_provider", "")),
        )

    async def revoke(self, firebase_uid: str) -> None:
        await asyncio.to_thread(
            fb_auth.revoke_refresh_tokens, firebase_uid, _app(self._project_id)
        )

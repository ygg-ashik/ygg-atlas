# pyright: basic
# Adapter over the untyped google-auth / firebase_admin SDKs; strict typing stops here.
"""The only module that talks to Firebase. Blocking SDK calls run in a thread.

ID tokens are verified with google-auth against Google's public signing keys, which
needs no service-account credentials (Firebase's documented third-party check:
signature, expiry, audience = project, issuer = securetoken/<project>, subject set).
Revocation is an Admin API call and does need credentials
(GOOGLE_APPLICATION_CREDENTIALS).
"""

import asyncio
from collections.abc import Mapping
from functools import cache
from typing import Any

import cachecontrol
import firebase_admin
import requests
from firebase_admin import auth as fb_auth
from google.auth.exceptions import TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.identity.errors import IdentityUnavailableError
from app.identity.tokens import InvalidTokenError, VerifiedToken

ISSUER_PREFIX = "https://securetoken.google.com/"


@cache
def _certs_request() -> google_requests.Request:
    # Google's signing certs carry Cache-Control; honour it instead of refetching.
    return google_requests.Request(
        session=cachecontrol.CacheControl(requests.Session())
    )


@cache
def _admin_app(project_id: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        options = {"projectId": project_id} if project_id else None
        return firebase_admin.initialize_app(options=options)


class FirebaseVerifier:
    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    async def verify(self, token: str) -> VerifiedToken:
        if not self._project_id:
            raise InvalidTokenError("NoFirebaseProject")
        try:
            claims: Mapping[str, Any] = await asyncio.to_thread(
                id_token.verify_firebase_token,
                token,
                _certs_request(),
                audience=self._project_id,
            )
        except TransportError:
            msg = "Firebase signing certificates are unreachable"
            raise IdentityUnavailableError(msg) from None
        except ValueError as exc:
            # The class name says why (expired, malformed) without the token.
            raise InvalidTokenError(type(exc).__name__) from None
        if claims.get("iss") != f"{ISSUER_PREFIX}{self._project_id}":
            raise InvalidTokenError("WrongIssuer")
        uid = str(claims.get("sub") or "")
        if not uid:
            raise InvalidTokenError("NoSubject")
        firebase_claims = claims.get("firebase") or {}
        return VerifiedToken(
            uid=uid,
            email=str(claims.get("email", "")).strip().lower(),
            email_verified=bool(claims.get("email_verified", False)),
            name=str(claims.get("name", "")),
            auth_time=int(claims.get("auth_time", 0)),
            sign_in_provider=str(firebase_claims.get("sign_in_provider", "")),
        )

    async def revoke(self, firebase_uid: str) -> None:
        await asyncio.to_thread(
            fb_auth.revoke_refresh_tokens, firebase_uid, _admin_app(self._project_id)
        )

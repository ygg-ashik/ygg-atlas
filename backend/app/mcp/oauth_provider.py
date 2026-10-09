"""identity's OAuthService adapted to the SDK authorization-server provider (D1).

The SDK handlers (authorize, token, register) do the protocol checks: client match,
code expiry, redirect equality and PKCE S256. Everything stateful lives in
`OAuthService`; each protocol call opens one fresh session for it.

Carriers never hold secrets (D28): `AtlasAuthorizationCode.code` and
`AtlasRefreshToken.token` are display prefixes; the ids travel in extra fields.
Client secrets are only ever compared as hashes (`HashedClientAuthenticator`).
"""

import base64
import binascii
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final
from urllib.parse import unquote
from uuid import UUID

import structlog
from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import FormData
from starlette.requests import Request

from app.access import MCP_USE, policy_for
from app.database import get_session_factory
from app.identity import (
    AuthorizationRequestData,
    ClientRegistration,
    CodeGrant,
    OAuthConfig,
    OAuthGrantError,
    OAuthRegistrationError,
    OAuthRequestError,
    OAuthService,
    RefreshGrant,
    RegisteredClient,
    TokenPair,
    principal_for_user,
)
from app.mcp.auth import AtlasAccessToken, AtlasTokenVerifier

logger = structlog.get_logger()

SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]

_SERVER_ERROR: Final = "The authorization server could not handle the request."
_BAD_CREDENTIALS: Final = "Invalid client credentials"
_PUBLIC: Final = "none"
_BASIC: Final = "client_secret_basic"
_POST: Final = "client_secret_post"
_BEARER: Final = "Bearer"  # the RFC 6750 token type name


class AtlasAuthorizationCode(AuthorizationCode):
    """SDK carrier. `code` holds the display prefix only (D28)."""

    code_id: UUID
    family_id: UUID
    user_id: UUID


class AtlasRefreshToken(RefreshToken):
    """SDK carrier. `token` holds the display prefix only (D28)."""

    token_id: UUID
    family_id: UUID
    user_id: UUID


def _client_info(client: RegisteredClient) -> OAuthClientInformationFull:
    """Never carries a secret: the SDK's own authenticator would compare plaintext,
    and ours compares hashes from `client_record`."""
    return OAuthClientInformationFull.model_validate(
        {
            "client_id": client.client_id,
            "client_secret": None,
            "client_name": client.client_name,
            "redirect_uris": list(client.redirect_uris),
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
            "grant_types": list(client.grant_types),
            "response_types": list(client.response_types),
            "client_id_issued_at": int(client.registered_at.timestamp()),
        }
    )


def _registration(info: OAuthClientInformationFull) -> ClientRegistration:
    if info.client_id is None:  # the SDK handler always mints one
        raise RegistrationError("invalid_client_metadata", "client_id is missing.")
    return ClientRegistration(
        client_id=info.client_id,
        client_secret=info.client_secret,
        client_name=info.client_name,
        # The canonical str(AnyUrl) spelling: what the SDK compares against later.
        redirect_uris=tuple(str(uri) for uri in info.redirect_uris or ()),
        token_endpoint_auth_method=info.token_endpoint_auth_method or _POST,
        grant_types=tuple(info.grant_types),
        response_types=tuple(info.response_types),
        software_id=info.software_id,
    )


def _code_carrier(grant: CodeGrant) -> AtlasAuthorizationCode:
    return AtlasAuthorizationCode(
        code=grant.display,
        scopes=list(grant.scopes),
        expires_at=grant.expires_at.timestamp(),
        client_id=grant.client_id,
        code_challenge=grant.code_challenge,
        redirect_uri=AnyUrl(grant.redirect_uri),
        redirect_uri_provided_explicitly=grant.redirect_uri_provided_explicitly,
        resource=grant.resource,
        subject=str(grant.user_id),
        code_id=grant.code_id,
        family_id=grant.family_id,
        user_id=grant.user_id,
    )


def _code_grant(code: AtlasAuthorizationCode) -> CodeGrant:
    return CodeGrant(
        code_id=code.code_id,
        family_id=code.family_id,
        client_id=code.client_id,
        user_id=code.user_id,
        code_challenge=code.code_challenge,
        redirect_uri=str(code.redirect_uri),
        redirect_uri_provided_explicitly=code.redirect_uri_provided_explicitly,
        resource=code.resource or "",
        scopes=tuple(code.scopes),
        expires_at=datetime.fromtimestamp(code.expires_at, UTC),
        display=code.code,
    )


def _refresh_carrier(grant: RefreshGrant) -> AtlasRefreshToken:
    return AtlasRefreshToken(
        token=grant.display,
        client_id=grant.client_id,
        scopes=[],
        expires_at=int(grant.expires_at.timestamp()),
        resource=grant.resource,
        subject=str(grant.user_id),
        token_id=grant.token_id,
        family_id=grant.family_id,
        user_id=grant.user_id,
    )


def _refresh_grant(token: AtlasRefreshToken) -> RefreshGrant:
    return RefreshGrant(
        token_id=token.token_id,
        family_id=token.family_id,
        client_id=token.client_id,
        user_id=token.user_id,
        resource=token.resource or "",
        expires_at=datetime.fromtimestamp(token.expires_at or 0, UTC),
        display=token.token,
    )


def _oauth_token(pair: TokenPair) -> OAuthToken:
    return OAuthToken(
        access_token=pair.access_token,
        token_type=_BEARER,
        expires_in=pair.expires_in,
        refresh_token=pair.refresh_token,
    )


class AtlasOAuthProvider(
    OAuthAuthorizationServerProvider[
        AtlasAuthorizationCode, AtlasRefreshToken, AtlasAccessToken
    ]
):
    """The nine SDK protocol methods over OAuthService, one session per call.

    Expected refusals map to the SDK's typed errors with identity's safe
    descriptions. Anything unexpected propagates to the route guard in
    `oauth_routes`, which answers a generic `server_error` (a transient failure
    must not read as `invalid_grant`, or clients drop a good refresh token).
    """

    def __init__(
        self,
        config: OAuthConfig,
        verifier: AtlasTokenVerifier,
        *,
        sessions: SessionFactory = get_session_factory,
    ) -> None:
        self._config = config
        self._verifier = verifier
        self._sessions = sessions

    async def client_record(self, client_id: str) -> RegisteredClient | None:
        """The live client with its secret hash (for HashedClientAuthenticator)."""
        async with self._sessions()() as db:
            return await OAuthService(db, self._config).get_client(client_id)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = await self.client_record(client_id)
        return None if client is None else _client_info(client)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        registration = _registration(client_info)
        try:
            async with self._sessions()() as db:
                await OAuthService(db, self._config).register_client(registration)
        except OAuthRegistrationError as exc:
            raise RegistrationError(exc.error, exc.description) from None

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Stores the request and returns the consent URL (`?txn=`)."""
        request = AuthorizationRequestData(
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            state=params.state,
            scopes=tuple(params.scopes or ()),
            resource=params.resource,
        )
        try:
            async with self._sessions()() as db:
                return await OAuthService(db, self._config).begin_authorization(
                    client.client_id or "", request
                )
        except OAuthRequestError as exc:
            raise AuthorizeError("invalid_request", exc.description) from None
        except Exception as exc:  # the SDK would log a traceback; keep it ours
            logger.error("mcp.oauth_authorize_failed", error=type(exc).__name__)
            raise AuthorizeError("server_error", _SERVER_ERROR) from None

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AtlasAuthorizationCode | None:
        async with self._sessions()() as db:
            grant = await OAuthService(db, self._config).load_code(
                client.client_id or "", authorization_code
            )
        return None if grant is None else _code_carrier(grant)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AtlasAuthorizationCode,
    ) -> OAuthToken:
        try:
            async with self._sessions()() as db:
                pair = await OAuthService(db, self._config).exchange_code(
                    client.client_id or "",
                    _code_grant(authorization_code),
                    self.eligible,
                )
        except OAuthGrantError as exc:
            raise TokenError("invalid_grant", exc.description) from None
        return _oauth_token(pair)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> AtlasRefreshToken | None:
        async with self._sessions()() as db:
            grant = await OAuthService(db, self._config).load_refresh(
                client.client_id or "", refresh_token
            )
        return None if grant is None else _refresh_carrier(grant)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: AtlasRefreshToken,
        scopes: list[str],  # ignored: no scopes, no narrowing (D10)
    ) -> OAuthToken:
        try:
            async with self._sessions()() as db:
                pair = await OAuthService(db, self._config).rotate_refresh(
                    client.client_id or "", _refresh_grant(refresh_token), self.eligible
                )
        except OAuthGrantError as exc:
            raise TokenError("invalid_grant", exc.description) from None
        return _oauth_token(pair)

    async def load_access_token(self, token: str) -> AtlasAccessToken | None:
        return await self._verifier.verify_token(token)

    async def revoke_token(self, token: AtlasAccessToken | AtlasRefreshToken) -> None:
        """RFC 7009: the whole family. The caller has checked the client matches."""
        async with self._sessions()() as db:
            await OAuthService(db, self._config).revoke_by_token_id(token.token_id)

    async def eligible(self, user_id: UUID) -> bool:
        """Active and holds mcp:use. Any error is False (fail closed)."""
        try:
            async with self._sessions()() as db:
                principal = await principal_for_user(db, user_id)
                if principal is None:
                    return False
                return (await policy_for(db, principal)).has(MCP_USE)
        except Exception as exc:
            logger.error("mcp.eligibility_check_failed", error=type(exc).__name__)
            return False


def _basic_secret(header: str, client_id: str) -> str:
    """RFC 6749 §2.3.1: base64(urlencode(id):urlencode(secret)); the id must be the
    form's client_id."""
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise AuthenticationError(_BAD_CREDENTIALS)
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise AuthenticationError(_BAD_CREDENTIALS) from None
    basic_id, separator, secret = decoded.partition(":")
    if not separator or unquote(basic_id) != client_id:
        raise AuthenticationError(_BAD_CREDENTIALS)
    return unquote(secret)


def _presented_secret(
    request: Request, form: FormData, method: str, client_id: str
) -> str | None:
    """The secret the client's registered method says to read; None for public."""
    if method == _BASIC:
        return _basic_secret(request.headers.get("Authorization", ""), client_id)
    if method == _POST:
        secret = form.get("client_secret")
        return secret if isinstance(secret, str) else None
    if method == _PUBLIC:
        return None
    raise AuthenticationError(_BAD_CREDENTIALS)


class HashedClientAuthenticator(ClientAuthenticator):
    """Client authentication against stored hashes, in constant time.

    The SDK's ClientAuthenticator compares `client.client_secret` in plaintext and
    skips the check when it is None, which `get_client` always returns, so the SDK
    class must never be used here.
    """

    def __init__(self, provider: AtlasOAuthProvider) -> None:
        super().__init__(provider)
        self._atlas = provider

    async def authenticate_request(
        self, request: Request
    ) -> OAuthClientInformationFull:
        form = await request.form()
        client_id = form.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthenticationError("Missing client_id")
        record = await self._atlas.client_record(client_id)  # None: unknown/revoked
        if record is None:
            raise AuthenticationError("Invalid client")
        presented = _presented_secret(
            request, form, record.token_endpoint_auth_method, client_id
        )
        if not record.secret_matches(presented):  # public: True; else compare_digest
            raise AuthenticationError(_BAD_CREDENTIALS)
        return _client_info(record)

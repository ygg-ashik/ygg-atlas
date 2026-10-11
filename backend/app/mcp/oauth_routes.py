"""The OAuth authorization-server routes and the discovery documents (D1, D2).

`build_oauth_routes` is the route table of the `/mcp-server` sub-app: the SDK's
authorize, token and register handlers with our provider and our hashed client
authenticator, our metadata (with `none`, S256 only, no scopes, no CIMD) and our
own RFC 7009 revocation handler (D29). `discovery_router` serves the root-level
documents clients look for first: the RFC 9728 protected-resource metadata and the
RFC 8414 path-inserted authorization-server metadata.

Every endpoint is guarded: an unexpected failure answers a generic `server_error`
and logs only the exception type, never a traceback or token material.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Final
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError
from mcp.server.auth.routes import cors_middleware, validate_issuer_url
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.streamable_http import MCP_PROTOCOL_VERSION_HEADER
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    ProtectedResourceMetadata,
)
from pydantic import AnyHttpUrl, BaseModel, ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

from app.config import Settings, get_settings
from app.identity import OAuthConfig
from app.mcp.oauth_provider import AtlasOAuthProvider, HashedClientAuthenticator
from app.mcp.ratelimit import (
    AUTHORIZE,
    REGISTER,
    REVOKE,
    TOKEN,
    RateLimitedEndpoint,
)

logger = structlog.get_logger()

Endpoint = Callable[[Request], Awaitable[Response]]

_AUTH_METHODS: Final = ["none", "client_secret_post", "client_secret_basic"]
_FORM: Final = "application/x-www-form-urlencoded"
_NO_STORE: Final = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_DISCOVERY_HEADERS: Final = {
    "Cache-Control": "public, max-age=300",
    "Access-Control-Allow-Origin": "*",
}
# What the SDK's own discovery routes answer to a CORS preflight (cors_middleware).
_PREFLIGHT_HEADERS: Final = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": MCP_PROTOCOL_VERSION_HEADER,
    "Access-Control-Max-Age": "600",
}
_SERVER_ERROR: Final = "The authorization server could not handle the request."
_REFRESH_HINT: Final = "refresh_token"
_NOT_FORM: Final = "The request body must be application/x-www-form-urlencoded."


def build_oauth_metadata(config: OAuthConfig) -> OAuthMetadata:
    """RFC 8414 metadata. The SDK's `build_metadata` hard-codes the secret-based
    methods only; public clients need `none`. No `scopes_supported` (D10) and no
    `client_id_metadata_document_supported` (D9), so clients use DCR."""
    issuer = config.issuer
    return OAuthMetadata(
        issuer=AnyHttpUrl(issuer),
        authorization_endpoint=AnyHttpUrl(f"{issuer}/authorize"),
        token_endpoint=AnyHttpUrl(f"{issuer}/token"),
        registration_endpoint=AnyHttpUrl(f"{issuer}/register"),
        revocation_endpoint=AnyHttpUrl(f"{issuer}/revoke"),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=list(_AUTH_METHODS),
        revocation_endpoint_auth_methods_supported=list(_AUTH_METHODS),
        code_challenge_methods_supported=["S256"],
    )


def build_protected_resource_metadata(settings: Settings) -> ProtectedResourceMetadata:
    """RFC 9728: `resource` is exactly the URL users type (D2)."""
    return ProtectedResourceMetadata(
        resource=AnyHttpUrl(settings.mcp_resource_url),
        authorization_servers=[AnyHttpUrl(settings.mcp_issuer_url)],
        resource_name="ygg-atlas",
    )


def _oauth_error(status: int, error: str, description: str) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers=_NO_STORE,
    )


def _guarded(endpoint: Endpoint, name: str) -> Endpoint:
    """Any unexpected failure becomes a generic OAuth `server_error`. Only the
    exception type is logged: the frames may hold a raw code, token or secret."""

    async def guarded(request: Request) -> Response:
        try:
            return await endpoint(request)
        except Exception as exc:
            logger.error(
                "mcp.oauth_endpoint_failed", endpoint=name, error=type(exc).__name__
            )
            return _oauth_error(500, "server_error", _SERVER_ERROR)

    return guarded


def _form_only(endpoint: Endpoint) -> Endpoint:
    """RFC 6749 §3.2 and RFC 7009 §2.1: form-encoded bodies only."""

    async def form_only(request: Request) -> Response:
        media_type = request.headers.get("content-type", "").partition(";")[0]
        if media_type.strip().lower() != _FORM:
            return _oauth_error(400, "invalid_request", _NOT_FORM)
        return await endpoint(request)

    return form_only


class _RevocationRequest(BaseModel):
    """RFC 7009 §2.1. Unlike the SDK's model, `client_secret` is optional (C2), and
    an unknown `token_type_hint` is accepted and ignored (§2.1: it is only a hint)."""

    token: str
    token_type_hint: str | None = None
    client_id: str
    client_secret: str | None = None


@dataclass
class AtlasRevocationHandler:
    """RFC 7009 revocation (D29). Revokes the token's family only when the token
    was issued to the authenticated client; always 200 otherwise, including for
    unknown tokens.

    Access tokens are found without the bearer door (no `last_used_at` write, no
    owner checks), so an expired access token still revokes its family. A refresh
    token presented by another client revokes its family anyway: `load_refresh`
    treats that as cross-client reuse (an intentional fail-safe)."""

    provider: AtlasOAuthProvider
    authenticator: HashedClientAuthenticator

    async def handle(self, request: Request) -> Response:
        try:
            client = await self.authenticator.authenticate_request(request)
        except AuthenticationError as exc:
            return _oauth_error(401, "unauthorized_client", exc.message)
        try:
            body = _RevocationRequest.model_validate(dict(await request.form()))
        except ValidationError:
            return _oauth_error(400, "invalid_request", "token is required.")
        token_id = await self._owned_token_id(client, body)
        if token_id is not None:
            await self.provider.revoke_family_of(token_id)
        return Response(status_code=200, headers=_NO_STORE)

    async def _owned_token_id(
        self, client: OAuthClientInformationFull, body: _RevocationRequest
    ) -> UUID | None:
        """The id of the presented token when it was issued to `client`."""
        if body.token_type_hint == _REFRESH_HINT:
            return await self._refresh_id(client, body.token) or await self._access_id(
                client, body.token
            )
        return await self._access_id(client, body.token) or await self._refresh_id(
            client, body.token
        )

    async def _access_id(
        self, client: OAuthClientInformationFull, raw: str
    ) -> UUID | None:
        found = await self.provider.find_access_token(raw)
        if found is None or found.client_id != client.client_id:
            return None
        return found.token_id

    async def _refresh_id(
        self, client: OAuthClientInformationFull, raw: str
    ) -> UUID | None:
        found = await self.provider.load_refresh_token(client, raw)
        if found is None or found.client_id != client.client_id:
            return None
        return found.token_id


def _cors(app: ASGIApp) -> ASGIApp:
    """As the SDK does: CORS outermost so inner refusals (413) carry the headers."""
    return CORSMiddleware(
        app=app,
        allow_origins="*",
        allow_methods=["POST", "OPTIONS"],
        allow_headers=[MCP_PROTOCOL_VERSION_HEADER],
    )


def _body_limited(endpoint: Endpoint) -> ASGIApp:
    return RequestBodyLimitMiddleware(
        request_response(endpoint), DEFAULT_MAX_REQUEST_BODY_SIZE
    )


def build_oauth_routes(
    provider: AtlasOAuthProvider, config: OAuthConfig
) -> list[Route]:
    """Routes relative to the `/mcp-server` mount (issuer `<url>/mcp-server`).

    `/authorize`, `/token`, `/register` and `/revoke` are rate limited per source
    (D16; `/revoke` 30/min, a review addition), inside
    CORS so a refusal still carries the CORS headers and a preflight never counts."""
    validate_issuer_url(AnyHttpUrl(config.issuer))
    metadata = build_oauth_metadata(config)
    authenticator = HashedClientAuthenticator(provider)
    authorize = AuthorizationHandler(provider)
    token = TokenHandler(provider, authenticator)
    register = RegistrationHandler(provider, ClientRegistrationOptions(enabled=True))
    revoke = AtlasRevocationHandler(provider, authenticator)
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(
                MetadataHandler(metadata).handle, ["GET", "OPTIONS"]
            ),
            methods=["GET", "OPTIONS"],
        ),
        Route(
            "/authorize",  # no CORS: clients redirect the browser here
            endpoint=RateLimitedEndpoint(
                _body_limited(_guarded(authorize.handle, "authorize")), AUTHORIZE
            ),
            methods=["GET", "POST"],
        ),
        Route(
            "/token",
            endpoint=_cors(
                RateLimitedEndpoint(
                    _body_limited(_guarded(_form_only(token.handle), "token")), TOKEN
                )
            ),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/register",
            endpoint=_cors(
                RateLimitedEndpoint(
                    _body_limited(_guarded(register.handle, "register")), REGISTER
                )
            ),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/revoke",
            endpoint=_cors(
                RateLimitedEndpoint(
                    _body_limited(_guarded(_form_only(revoke.handle), "revoke")),
                    REVOKE,
                )
            ),
            methods=["POST", "OPTIONS"],
        ),
    ]


SettingsDep = Annotated[Settings, Depends(get_settings)]

discovery_router = APIRouter(tags=["mcp-discovery"])


_PRM_PATH: Final = "/.well-known/oauth-protected-resource/mcp-server/mcp"
_AS_PATH: Final = "/.well-known/oauth-authorization-server/mcp-server"


@discovery_router.options(_PRM_PATH)
@discovery_router.options(_AS_PATH)
async def discovery_preflight() -> Response:
    """CORS preflight for browser-based clients, as the SDK's discovery routes do."""
    return Response(status_code=200, headers=_PREFLIGHT_HEADERS)


@discovery_router.get(_PRM_PATH)
async def protected_resource(settings: SettingsDep) -> JSONResponse:
    """RFC 9728 §3.1: path-inserted for the resource `<url>/mcp-server/mcp`."""
    metadata = build_protected_resource_metadata(settings)
    return JSONResponse(
        metadata.model_dump(mode="json", exclude_none=True), headers=_DISCOVERY_HEADERS
    )


@discovery_router.get(_AS_PATH)
async def authorization_server(settings: SettingsDep) -> JSONResponse:
    """RFC 8414 §3.1: path-inserted for the issuer `<url>/mcp-server`."""
    metadata = build_oauth_metadata(OAuthConfig.from_settings(settings))
    return JSONResponse(
        metadata.model_dump(mode="json", exclude_none=True), headers=_DISCOVERY_HEADERS
    )

"""The MCP credential API: personal tokens, connected apps, OAuth consent, admin
credential routes and the auth-methods catalog (D4, D13, D22, D24, D34, D36).

Thin: parse, call an identity service or AccessAdmin, map errors, return a schema.
Raw tokens appear only in the two create responses. Error bodies, including
validation errors, never echo what the caller sent.
"""

from collections.abc import Callable, Coroutine
from typing import Any, Final, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    ADMIN_AUDIT,
    ADMIN_CLIENTS,
    ADMIN_TOKENS,
    MCP_USE,
    TOKENS_CREATE,
    AccessAdmin,
    Actor,
    Policy,
    get_access_admin,
    get_actor,
    get_policy,
    require_capability,
)
from app.config import Settings, get_settings
from app.database import get_db
from app.identity import (
    REVOKED_APP_DISCONNECTED,
    REVOKED_BY_ADMIN,
    REVOKED_BY_USER,
    ConnectedApp,
    CredentialActor,
    ForbiddenError,
    IssuedToken,
    OAuthService,
    Principal,
    TokenKind,
    TokenService,
    get_principal,
)
from app.mcp.dependencies import (
    consent_errors,
    credential_errors,
    get_oauth_service,
    get_token_service,
    mint_service_token,
    require_tenant_user,
    transaction_gone,
)
from app.mcp.ratelimit import CONSENT, rate_limit
from app.mcp.schemas import (
    AdminTokenKind,
    AuthMethodsOut,
    ClientOut,
    ConnectedAppOut,
    ConsentDecision,
    ConsentOut,
    ConsentPromptOut,
    ConsentRefusal,
    ConsentRefusalOut,
    CredentialEventOut,
    OAuthMethodOut,
    PatMethodOut,
    RevokedOut,
    ServiceAccountCreate,
    ServiceAccountOut,
    TokenCreate,
    TokenCreatedOut,
    TokenOut,
)

logger = structlog.get_logger()

Handler = Callable[[Request], Coroutine[Any, Any, Response]]

_ADMIN_KINDS: Final[dict[AdminTokenKind | None, tuple[TokenKind, ...]]] = {
    None: tuple(TokenKind),
    "pat": (TokenKind.PAT,),
    "service": (TokenKind.SERVICE,),
    "oauth": (TokenKind.OAUTH_ACCESS, TokenKind.OAUTH_REFRESH),
}
_NO_MCP_USE: Final = "Your role doesn't include MCP access yet."


class _QuietValidationRoute(APIRoute):
    """422s list what failed, never the input: a mistyped body may hold a token or
    a consent transaction id."""

    def get_route_handler(self) -> Handler:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                errors = [
                    {
                        "loc": list(e.get("loc", ())),
                        "msg": e.get("msg", ""),
                        "type": e.get("type", ""),
                    }
                    for e in exc.errors()
                ]
                return JSONResponse({"detail": errors}, status_code=422)

        return handle


class _ConsentRoute(_QuietValidationRoute):
    """Every consent 403 says why as `detail.reason` (ConsentRefusal), including the
    identity door's own refusals (`ForbiddenError.reason`, chained by get_principal),
    so the page never parses message text."""

    def get_route_handler(self) -> Handler:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except HTTPException as exc:
                # Starlette types `detail` as str; ours (no_mcp_use) is a dict.
                detail = cast(object, exc.detail)
                refused = exc.__cause__
                if (
                    exc.status_code != 403
                    or not isinstance(detail, str)
                    or not isinstance(refused, ForbiddenError)
                ):
                    raise
                logger.info("mcp.consent_refused", reason=refused.reason)
                raise HTTPException(
                    403, _refusal(refused.reason, detail), headers=exc.headers
                ) from None

        return handle


def _refusal(reason: ConsentRefusal, message: str) -> dict[str, str]:
    return ConsentRefusalOut(reason=reason, message=message).model_dump()


mcp_router = APIRouter(
    prefix="/api/v1", tags=["mcp-auth"], route_class=_QuietValidationRoute
)
_consent = APIRouter(route_class=_ConsentRoute)


def _created(issued: IssuedToken) -> TokenCreatedOut:
    return TokenCreatedOut.model_validate(
        {**TokenOut.model_validate(issued.token).model_dump(), "token": issued.raw}
    )


def _connected(app: ConnectedApp) -> ConnectedAppOut:
    return ConnectedAppOut(
        family_id=app.family_id,
        client_id=app.client_id,
        client_name=app.client_name,
        redirect_host=app.redirect_host,
        created_at=app.created_at,
        last_used_at=app.last_used_at,
        expires_at=app.expires_at,
    )


def _api_actor(user_id: UUID) -> CredentialActor:
    return CredentialActor(user_id, "api")


# ---- self-service ---------------------------------------------------------------


@mcp_router.get("/me/tokens", response_model=list[TokenOut])
async def list_my_tokens(
    principal: Principal = Depends(get_principal),
    tokens: TokenService = Depends(get_token_service),
) -> list[TokenOut]:
    rows = await tokens.list_tokens(
        tenant=principal.tenant, user_id=principal.user_id, kinds=(TokenKind.PAT,)
    )
    return [TokenOut.model_validate(row) for row in rows]


@mcp_router.post("/me/tokens", response_model=TokenCreatedOut, status_code=201)
async def create_my_token(
    payload: TokenCreate,
    policy: Policy = Depends(require_capability(TOKENS_CREATE)),
    tokens: TokenService = Depends(get_token_service),
    settings: Settings = Depends(get_settings),
) -> TokenCreatedOut:
    with credential_errors():
        issued = await tokens.create_pat(
            policy.user_id,
            name=payload.name,
            expires_in_days=payload.expires_in_days,
            actor=_api_actor(policy.user_id),
            default_days=settings.pat_default_days,
            max_days=settings.pat_max_days,
        )
    return _created(issued)


@mcp_router.delete("/me/tokens/{token_id}", status_code=204)
async def revoke_my_token(
    token_id: UUID,
    principal: Principal = Depends(get_principal),
    tokens: TokenService = Depends(get_token_service),
) -> None:
    with credential_errors():
        await tokens.revoke_token(
            token_id,
            reason=REVOKED_BY_USER,
            actor=_api_actor(principal.user_id),
            owner_id=principal.user_id,
        )


@mcp_router.get("/me/connected-apps", response_model=list[ConnectedAppOut])
async def list_my_connected_apps(
    principal: Principal = Depends(get_principal),
    tokens: TokenService = Depends(get_token_service),
) -> list[ConnectedAppOut]:
    return [_connected(a) for a in await tokens.list_connected_apps(principal.user_id)]


@mcp_router.delete("/me/connected-apps/{family_id}", status_code=204)
async def disconnect_my_app(
    family_id: UUID,
    principal: Principal = Depends(get_principal),
    tokens: TokenService = Depends(get_token_service),
) -> None:
    with credential_errors():
        await tokens.revoke_family(
            family_id,
            reason=REVOKED_APP_DISCONNECTED,
            actor=_api_actor(principal.user_id),
            owner_id=principal.user_id,
        )


# ---- OAuth consent (D4, D36) ----------------------------------------------------
# CSRF: the Firebase bearer is required and a browser never attaches it on its own,
# so a cross-site form or a cookie cannot approve. The code is bound to the bearer's
# user; client, redirect, PKCE and audience come from the stored request.
# Both routes share one budget per signed-in user (D16: 10/min).


async def _consent_user_key(principal: Principal = Depends(get_principal)) -> str:
    return str(principal.user_id)


_consent_limit = rate_limit(CONSENT, _consent_user_key)


@_consent.get(
    "/oauth/consent/{txn}",
    response_model=ConsentPromptOut,
    dependencies=[Depends(_consent_limit)],
)
async def consent_prompt(
    txn: str,
    principal: Principal = Depends(get_principal),
    policy: Policy = Depends(get_policy),
    oauth: OAuthService = Depends(get_oauth_service),
) -> ConsentPromptOut:
    pending = await oauth.pending_request(txn)
    if pending is None:
        raise transaction_gone()
    eligible = policy.has(MCP_USE)
    return ConsentPromptOut(
        transaction_id=txn,
        client_name=pending.client_name,
        redirect_uri=pending.redirect_uri,
        redirect_host=pending.redirect_host,
        loopback=pending.loopback,
        user_email=principal.email,
        eligible=eligible,
        ineligible_reason=None if eligible else "no_mcp_use",
        expires_at=pending.expires_at,
    )


@_consent.post(
    "/oauth/consent", response_model=ConsentOut, dependencies=[Depends(_consent_limit)]
)
async def decide_consent(
    payload: ConsentDecision,
    principal: Principal = Depends(get_principal),
    policy: Policy = Depends(get_policy),
    oauth: OAuthService = Depends(get_oauth_service),
) -> ConsentOut:
    with consent_errors():
        if payload.decision == "deny":
            redirect = await oauth.deny(payload.transaction_id, principal.user_id)
        elif not policy.has(MCP_USE):  # the transaction stays usable
            raise HTTPException(403, _refusal("no_mcp_use", _NO_MCP_USE))
        else:
            redirect = await oauth.approve(payload.transaction_id, principal.user_id)
    logger.info(
        "mcp.consent_decided", user_id=str(principal.user_id), decision=payload.decision
    )
    return ConsentOut(redirect_to=redirect)


mcp_router.include_router(_consent)


# ---- administration (D13, D24, D34) ------------------------------------------------


@mcp_router.get(
    "/admin/tokens",
    response_model=list[TokenOut],
    response_description="Newest first; at most 200 tokens.",
)
async def admin_list_tokens(
    user_id: UUID | None = None,
    kind: AdminTokenKind | None = None,
    policy: Policy = Depends(require_capability(ADMIN_TOKENS)),
    tokens: TokenService = Depends(get_token_service),
) -> list[TokenOut]:
    """Unrevoked tokens in the caller's tenant, newest first, capped at 200 rows (the
    repository's limit); narrow with `user_id` or `kind` to see older ones."""
    rows = await tokens.list_tokens(
        tenant=policy.tenant, user_id=user_id, kinds=_ADMIN_KINDS[kind]
    )
    return [TokenOut.model_validate(row) for row in rows]


@mcp_router.delete("/admin/tokens/{token_id}", status_code=204)
async def admin_revoke_token(
    token_id: UUID,
    policy: Policy = Depends(require_capability(ADMIN_TOKENS)),
    tokens: TokenService = Depends(get_token_service),
) -> None:
    with credential_errors():
        await tokens.revoke_token(
            token_id,
            reason=REVOKED_BY_ADMIN,
            actor=_api_actor(policy.user_id),
            tenant=policy.tenant,
        )


@mcp_router.post("/admin/users/{user_id}/tokens/revoke-all", response_model=RevokedOut)
async def admin_revoke_all_tokens(
    user_id: UUID,
    policy: Policy = Depends(require_capability(ADMIN_TOKENS)),
    tokens: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
) -> RevokedOut:
    """Every token of a user in the caller's tenant, whatever their status: the
    cleanup tool for a disable whose post-commit revoke hook (D18) failed."""
    await require_tenant_user(db, user_id, policy.tenant)
    count = await tokens.revoke_all_tokens(
        user_id, reason=REVOKED_BY_ADMIN, actor=_api_actor(policy.user_id)
    )
    return RevokedOut(revoked=count)


@mcp_router.post(
    "/admin/service-accounts", response_model=ServiceAccountOut, status_code=201
)
async def admin_create_service_account(
    payload: ServiceAccountCreate,
    actor: Actor = Depends(get_actor),
    admin: AccessAdmin = Depends(get_access_admin),
) -> ServiceAccountOut:
    """AccessAdmin checks admin:users and the role ceiling (D10, D13)."""
    user = await admin.create_service_account(actor, payload.name, payload.role)
    return ServiceAccountOut.model_validate(user)


@mcp_router.post(
    "/admin/service-accounts/{user_id}/tokens",
    response_model=TokenCreatedOut,
    status_code=201,
)
async def admin_mint_service_token(
    user_id: UUID,
    payload: TokenCreate,
    policy: Policy = Depends(require_capability(ADMIN_TOKENS)),
    tokens: TokenService = Depends(get_token_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenCreatedOut:
    issued = await mint_service_token(
        db,
        tokens,
        actor=policy,
        service_user_id=user_id,
        request=payload,
        settings=settings,
    )
    return _created(issued)


@mcp_router.get("/admin/clients", response_model=list[ClientOut])
async def admin_list_clients(
    _policy: Policy = Depends(require_capability(ADMIN_CLIENTS)),
    oauth: OAuthService = Depends(get_oauth_service),
) -> list[ClientOut]:
    """OAuth clients are global (dynamic registration knows no tenant)."""
    return [
        ClientOut(
            client_id=c.client_id,
            client_name=c.client_name,
            redirect_uris=list(c.redirect_uris),
            token_endpoint_auth_method=c.token_endpoint_auth_method,
            registered_at=c.registered_at,
            revoked_at=c.revoked_at,
            active_families=c.active_families,
        )
        for c in await oauth.list_clients()
    ]


@mcp_router.delete("/admin/clients/{client_id}", status_code=204)
async def admin_revoke_client(
    client_id: str = Path(max_length=255),
    policy: Policy = Depends(require_capability(ADMIN_CLIENTS)),
    oauth: OAuthService = Depends(get_oauth_service),
) -> None:
    """Revokes the client and every token issued to it."""
    if not await oauth.revoke_client(client_id, actor=_api_actor(policy.user_id)):
        raise HTTPException(404, "No such active client.")


@mcp_router.get("/admin/credential-events", response_model=list[CredentialEventOut])
async def admin_credential_events(
    user_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    policy: Policy = Depends(require_capability(ADMIN_AUDIT)),
    tokens: TokenService = Depends(get_token_service),
) -> list[CredentialEventOut]:
    """Newest first, in the caller's tenant. Events about no user (client
    registration, garbage collection) are global: they appear in every tenant's
    list unless `user_id` is given."""
    rows = await tokens.list_events(tenant=policy.tenant, user_id=user_id, limit=limit)
    return [CredentialEventOut.model_validate(row) for row in rows]


# ---- catalog (D22) -------------------------------------------------------------------


@mcp_router.get("/meta/auth-methods", response_model=AuthMethodsOut)
async def auth_methods(
    _principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> AuthMethodsOut:
    """What the account UI may offer. Hosted connectors (claude.ai) need https."""
    return AuthMethodsOut(
        pat=PatMethodOut(
            enabled=True,
            default_days=settings.pat_default_days,
            max_days=settings.pat_max_days,
        ),
        oauth=OAuthMethodOut(
            enabled=True, hosted_connectors=settings.hosted_connectors_enabled
        ),
    )

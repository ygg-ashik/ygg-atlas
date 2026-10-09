"""The OAuth 2.1 authorization service behind the MCP edge (D4-D8, D30, D36).

Clients (dynamic registration, allowlisted redirects), pending authorizations,
single-use codes and rotating refresh-token families with reuse detection. Only
hashes are stored; raw codes, txn ids, tokens and client secrets live in the
request and the response alone. It never imports `credentials` (a sibling layer)
or the MCP SDK: `app/mcp` adapts this service to the SDK handlers.
"""

import hmac
import re
from collections.abc import Awaitable, Callable, Collection, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Self
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import structlog
from pydantic import AnyHttpUrl, AnyUrl, ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.identity.api_tokens import (
    ACCESS_TOKEN_TTL,
    AUTHORIZATION_REQUEST_TTL,
    CODE_TTL,
    EVENT_CLIENT_REGISTERED,
    EVENT_CLIENT_REVOKED,
    EVENT_CONSENT_APPROVED,
    EVENT_CONSENT_DENIED,
    EVENT_FAMILY_REVOKED,
    EVENT_GC,
    EVENT_REFRESH_GRACE,
    EVENT_REFRESHED,
    EVENT_REUSE_DETECTED,
    EVENT_TOKENS_ISSUED,
    REFRESH_REUSE_GRACE,
    REFRESH_TOKEN_TTL,
    REVOKED_AUDIENCE_CHANGED,
    REVOKED_CLIENT,
    REVOKED_CODE_REUSE,
    REVOKED_CROSS_CLIENT,
    REVOKED_NO_MCP_USE,
    REVOKED_OAUTH_REVOKE,
    REVOKED_REFRESH_REUSE,
    REVOKED_ROTATED,
    REVOKED_USER_DISABLED,
    UNNAMED_CLIENT,
    CredentialActor,
    TokenKind,
    display_prefix,
    hash_secret,
    kind_of,
    mint,
    mint_secret,
)
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    UserKind,
    UserStatus,
)
from app.identity.repository import CredentialRepository, GcCounts, UserRepository

logger = structlog.get_logger()

INVALID_REQUEST: Final = "invalid_request"
INVALID_GRANT: Final = "invalid_grant"
RegistrationErrorCode = Literal["invalid_redirect_uri", "invalid_client_metadata"]

MAX_REDIRECT_URIS: Final = 5
MAX_CLIENT_NAME: Final = 100
MAX_SOFTWARE_ID: Final = 200
MAX_STATE: Final = 500
MAX_REDIRECT_LENGTH: Final = 2000  # the stored column's width

_PUBLIC_METHOD: Final = "none"
_AUTH_METHODS: Final = frozenset(
    {_PUBLIC_METHOD, "client_secret_post", "client_secret_basic"}
)
_GRANT_TYPES: Final = frozenset({"authorization_code", "refresh_token"})
_RESPONSE_TYPES: Final = ("code",)
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "[::1]"})
_CHALLENGE: Final = re.compile(r"[A-Za-z0-9_-]{43}")  # base64url(SHA-256), RFC 7636
_REUSE_REASONS: Final = frozenset(
    {REVOKED_CODE_REUSE, REVOKED_REFRESH_REUSE, REVOKED_CROSS_CLIENT}
)

# Safe, generic descriptions: the reason goes to a log field, never to the client.
_DEAD_CODE: Final = "The authorization code is no longer valid."
_DEAD_REFRESH: Final = "The refresh token is no longer valid."
_INELIGIBLE: Final = "Authorization is no longer valid. Sign in again."
_UNAVAILABLE: Final = "The grant could not be processed. Try again."

# Supplied by app/mcp: the user is active and holds mcp:use.
Eligibility = Callable[[UUID], Awaitable[bool]]
ReuseKind = Literal["code", "refresh"]

# What `OAuthService.gc` removed: the repository's counts are the report.
GcReport = GcCounts


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime) -> datetime:
    """SQLite drops tzinfo on the way back; every stored moment is UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class OAuthConfig:
    issuer: str
    resource: str
    consent_url: str
    hosted_redirect_uris: frozenset[str]
    access_ttl: timedelta = ACCESS_TOKEN_TTL
    refresh_ttl: timedelta = REFRESH_TOKEN_TTL
    code_ttl: timedelta = CODE_TTL
    request_ttl: timedelta = AUTHORIZATION_REQUEST_TTL
    refresh_grace: timedelta = REFRESH_REUSE_GRACE

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Issuer, resource and consent URLs from ATLAS_PUBLIC_URL (D2)."""
        return cls(
            issuer=settings.mcp_issuer_url,
            resource=settings.mcp_resource_url,
            consent_url=settings.oauth_consent_url,
            hosted_redirect_uris=frozenset(settings.hosted_redirect_uri_list),
        )


@dataclass(frozen=True, slots=True)
class ClientRegistration:
    """What dynamic client registration hands us (mapped from the SDK by app/mcp)."""

    client_id: str
    client_secret: str | None = field(repr=False)
    client_name: str | None
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    software_id: str | None


@dataclass(frozen=True, slots=True)
class RegisteredClient:
    """A live client. The secret hash never leaves identity except to authenticate."""

    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    registered_at: datetime
    secret_hash: str | None = field(default=None, repr=False)

    def secret_matches(self, presented: str | None) -> bool:
        """The auth method decides: a public client authenticates with no secret (a
        presented one is ignored); a confidential one only with its own, compared
        as hashes in constant time. A confidential client with no hash never does."""
        if self.token_endpoint_auth_method == _PUBLIC_METHOD:
            return True
        if self.secret_hash is None or presented is None:
            return False
        return hmac.compare_digest(self.secret_hash, hash_secret(presented))


@dataclass(frozen=True, slots=True)
class AuthorizationRequestData:
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    state: str | None
    scopes: tuple[str, ...]
    resource: str | None


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    """What the consent page shows about a pending request."""

    client_id: str
    client_name: str  # UNNAMED_CLIENT when the client registered none
    redirect_uri: str
    redirect_host: str
    loopback: bool
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CodeGrant:
    code_id: UUID
    family_id: UUID
    client_id: str
    user_id: UUID
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str
    scopes: tuple[str, ...]
    expires_at: datetime
    display: str  # display prefix only (D28)


@dataclass(frozen=True, slots=True)
class RefreshGrant:
    token_id: UUID
    family_id: UUID
    client_id: str
    user_id: UUID
    resource: str
    expires_at: datetime
    display: str  # display prefix only (D28)


@dataclass(frozen=True, slots=True)
class AccessTokenRef:
    """An OAuth access token as RFC 7009 revocation needs it: whose it is."""

    token_id: UUID
    client_id: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    family_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class ClientSummary:
    """One row of /admin/clients."""

    client_id: str
    client_name: str  # UNNAMED_CLIENT when the client registered none
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    registered_at: datetime
    revoked_at: datetime | None
    active_families: int


class OAuthRegistrationError(Exception):
    """Dynamic registration refused (RFC 7591 error codes)."""

    def __init__(self, error: RegistrationErrorCode, description: str) -> None:
        super().__init__(description)
        self.error: RegistrationErrorCode = error
        self.description = description


class OAuthRequestError(Exception):
    """An /authorize request refused; `description` is safe to show."""

    error: Final = INVALID_REQUEST

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class OAuthGrantError(Exception):
    """A code or refresh grant refused; `description` is safe to show."""

    error: Final = INVALID_GRANT

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class AuthorizationRequestNotFoundError(Exception):
    """Unknown, expired or already consumed authorization request (404)."""


# ---- pure URL rules ---------------------------------------------------------------


def _parse_url(uri: str) -> AnyUrl | None:
    if len(uri) > MAX_REDIRECT_LENGTH:
        return None
    try:
        return AnyUrl(uri)
    except ValidationError:
        return None


def canonical_resource(url: str) -> str | None:
    """The SDK's own comparison (BearerAuthBackend._issued_for_this_resource): case and
    default port do not matter, one trailing slash aside. None if not a URL."""
    try:
        return str(AnyHttpUrl(url)).removesuffix("/")
    except ValidationError:
        return None


def redirect_allowed(uri: str, hosted: Collection[str]) -> bool:
    """D8. Parsed with Pydantic AnyUrl (WHATWG, as the browser parses it), so there is
    no parser differential: loopback http on any port and path, or an exact approved
    https callback. Never userinfo (even `evil.com@localhost`, which lands on
    loopback: credentials-shaped text in a redirect is only a phishing aid) and never
    a fragment (RFC 6749 §3.1.2)."""
    url = _parse_url(uri)
    if url is None:
        return False
    if url.username is not None or url.password is not None:
        return False
    if url.fragment is not None:
        return False
    if url.scheme == "https":
        approved = {str(h) for h in map(_parse_url, hosted) if h is not None}
        return str(url) in approved
    return url.scheme == "http" and url.host in _LOOPBACK_HOSTS


def is_loopback_redirect(uri: str) -> bool:
    """True for an http redirect to localhost, 127.0.0.1 or [::1]."""
    url = _parse_url(uri)
    return url is not None and url.scheme == "http" and url.host in _LOOPBACK_HOSTS


def with_query(uri: str, **params: str | None) -> str:
    """`uri` with `params` added to its query; keeps the existing query, skips None."""
    extra = urlencode(
        {name: value for name, value in params.items() if value is not None}
    )
    if not extra:
        return uri
    parts = urlsplit(uri)
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit(parts._replace(query=query))


def _canonical_redirect(uri: str) -> str:
    """The one spelling of a redirect we store and compare: `str(AnyUrl(uri))`.

    Note for app/mcp (Task 5): the SDK compares redirects as `str(AnyUrl)` on both
    sides (`OAuthClientMetadata.validate_redirect_uri`, `handlers/token.py`), so
    everything this service stores, returns in `RegisteredClient.redirect_uris`,
    binds into a code and redirects to is already in that form; a client may
    register `http://127.0.0.1:33418` and send `http://127.0.0.1:33418/`. Only
    called on URIs `redirect_allowed` accepted, or to normalise a comparison.
    """
    url = _parse_url(uri)
    return str(url) if url is not None else uri


def _redirect_host(uri: str) -> str:
    url = _parse_url(uri)
    return (url.host or "") if url is not None else ""


# ---- registration rules -----------------------------------------------------------


def _clean_name(name: str | None) -> str | None:
    stripped = (name or "").strip()
    return stripped or None


def _metadata_problem(registration: ClientRegistration) -> str | None:
    method = registration.token_endpoint_auth_method
    name = _clean_name(registration.client_name)
    software_id = registration.software_id or ""
    checks = (
        (
            len(registration.redirect_uris) > MAX_REDIRECT_URIS,
            "Too many redirect URIs.",
        ),
        (method not in _AUTH_METHODS, "Unsupported token_endpoint_auth_method."),
        (
            (method == _PUBLIC_METHOD) != (registration.client_secret is None),
            "client_secret does not fit token_endpoint_auth_method.",
        ),
        (
            frozenset(registration.grant_types) != _GRANT_TYPES,
            "grant_types must be authorization_code and refresh_token.",
        ),
        (
            registration.response_types != _RESPONSE_TYPES,
            "response_types must be code.",
        ),
        (name is not None and len(name) > MAX_CLIENT_NAME, "client_name is too long."),
        (len(software_id) > MAX_SOFTWARE_ID, "software_id is too long."),
    )
    return next((message for failed, message in checks if failed), None)


def _validate_registration(
    registration: ClientRegistration, hosted: Collection[str]
) -> None:
    uris = registration.redirect_uris
    if not uris or not all(redirect_allowed(uri, hosted) for uri in uris):
        raise OAuthRegistrationError(
            "invalid_redirect_uri",
            "Redirect URIs must be loopback (http://localhost, 127.0.0.1 or [::1]) "
            "or an approved hosted callback.",
        )
    problem = _metadata_problem(registration)
    if problem is not None:
        raise OAuthRegistrationError("invalid_client_metadata", problem)


# ---- row builders -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Family:
    """One consent's token family: who it belongs to and through which client."""

    family_id: UUID
    user_id: UUID
    client_id: str


def _mint_row(
    kind: TokenKind, family: _Family, audience: str, now: datetime, ttl: timedelta
) -> tuple[ApiToken, str]:
    """A new token of `kind` in `family`: the row to store and the raw value."""
    raw = mint(kind)
    row = ApiToken(
        user_id=family.user_id,
        kind=kind,
        token_hash=hash_secret(raw),
        prefix=display_prefix(raw),
        client_id=family.client_id,
        family_id=family.family_id,
        audience=audience,
        created_at=now,
        expires_at=now + ttl,
    )
    return row, raw


def _code_grant(row: OAuthCode, display: str) -> CodeGrant:
    return CodeGrant(
        code_id=row.id,
        family_id=row.family_id,
        client_id=row.client_id,
        user_id=row.user_id,
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        resource=row.resource,
        scopes=tuple(row.scopes),
        expires_at=_as_utc(row.expires_at),
        display=display,
    )


def _presenter(owner_client_id: str, presented_by: str) -> dict[str, str]:
    """Forensics for a reuse event: who presented the credential, when not its own
    client (the event's client_id stays the family's client)."""
    if presented_by == owner_client_id:
        return {}
    return {"presented_by_client_id": presented_by}


async def _is_eligible(eligible: Eligibility, user_id: UUID) -> bool:
    try:
        return await eligible(user_id)
    except Exception as exc:  # fail closed: any error is "not eligible"
        logger.error("oauth.eligibility_check_failed", error=type(exc).__name__)
        return False


class OAuthService:
    """Clients, consent, codes and token families. One instance per request.

    Every state change commits together with its credential_events row. Every
    "only once" step (consent, code exchange, rotation) is one conditional UPDATE in
    the repository, so concurrent requests on separate sessions cannot both win.
    """

    def __init__(
        self,
        db: AsyncSession,
        config: OAuthConfig,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._creds = CredentialRepository(db)
        self._users = UserRepository(db)
        self._config = config
        self._clock = clock

    # ---- clients ------------------------------------------------------------------

    async def register_client(self, registration: ClientRegistration) -> None:
        """Validates and stores a DCR client (secret hashed); writes
        client.registered. Raises OAuthRegistrationError."""
        _validate_registration(registration, self._config.hosted_redirect_uris)
        name = _clean_name(registration.client_name)
        secret = registration.client_secret
        method = registration.token_endpoint_auth_method
        self._creds.add(
            OAuthClient(
                client_id=registration.client_id,
                client_name=name,
                redirect_uris=[
                    _canonical_redirect(uri) for uri in registration.redirect_uris
                ],
                token_endpoint_auth_method=method,
                client_secret_hash=hash_secret(secret) if secret is not None else None,
                grant_types=list(registration.grant_types),
                response_types=list(registration.response_types),
                software_id=registration.software_id,
                registered_at=self._clock(),
            )
        )
        hosts = [_redirect_host(uri) for uri in registration.redirect_uris]
        self._creds.add(
            CredentialEvent(
                event=EVENT_CLIENT_REGISTERED,
                via="oauth",
                client_id=registration.client_id,
                details={"name": name, "redirect_hosts": hosts, "auth_method": method},
            )
        )
        await self._creds.commit()
        logger.info(
            "oauth.client_registered",
            client_id=registration.client_id,
            auth_method=method,
        )

    async def get_client(self, client_id: str) -> RegisteredClient | None:
        """None for unknown or revoked clients, or when no stored redirect is still
        allowed (the allowlist may have narrowed since registration)."""
        row = await self._creds.client(client_id)
        if row is None or row.revoked_at is not None:
            return None
        hosted = self._config.hosted_redirect_uris
        allowed = tuple(
            _canonical_redirect(uri)
            for uri in row.redirect_uris
            if redirect_allowed(uri, hosted)
        )
        if not allowed:
            return None
        return RegisteredClient(
            client_id=row.client_id,
            client_name=row.client_name,
            redirect_uris=allowed,
            token_endpoint_auth_method=row.token_endpoint_auth_method,
            grant_types=tuple(row.grant_types),
            response_types=tuple(row.response_types),
            registered_at=_as_utc(row.registered_at),
            secret_hash=row.client_secret_hash,
        )

    async def revoke_client(self, client_id: str, *, actor: CredentialActor) -> bool:
        """Revokes the client and all its tokens; writes client.revoked. False when
        the client is unknown or already revoked."""
        now = self._clock()
        if not await self._creds.revoke_client(client_id, now):
            return False
        tokens = await self._creds.revoke_client_tokens(client_id, REVOKED_CLIENT, now)
        self._creds.add(
            CredentialEvent(
                event=EVENT_CLIENT_REVOKED,
                via=actor.via,
                actor_user_id=actor.user_id,
                client_id=client_id,
                details={"tokens": tokens},
            )
        )
        await self._creds.commit()
        logger.info("oauth.client_revoked", client_id=client_id, tokens=tokens)
        return True

    async def list_clients(self) -> list[ClientSummary]:
        rows = await self._creds.list_clients()
        families = await self._creds.live_family_counts(self._clock())
        return [
            ClientSummary(
                client_id=row.client_id,
                client_name=row.client_name or UNNAMED_CLIENT,
                redirect_uris=tuple(row.redirect_uris),
                token_endpoint_auth_method=row.token_endpoint_auth_method,
                registered_at=_as_utc(row.registered_at),
                revoked_at=_as_utc(row.revoked_at) if row.revoked_at else None,
                active_families=families.get(row.client_id, 0),
            )
            for row in rows
        ]

    # ---- authorization and consent ---------------------------------------------------

    async def begin_authorization(
        self, client_id: str, request: AuthorizationRequestData
    ) -> str:
        """Stores the request under hash(txn) and returns the consent URL with txn.
        Raises OAuthRequestError."""
        client = await self.get_client(client_id)
        redirect_uri = _canonical_redirect(request.redirect_uri)
        if client is None or redirect_uri not in client.redirect_uris:
            raise OAuthRequestError("This client or redirect is not registered.")
        audience = self._bind_audience(request.resource)
        if not _CHALLENGE.fullmatch(request.code_challenge):
            raise OAuthRequestError("code_challenge must be an S256 challenge.")
        if request.state is not None and len(request.state) > MAX_STATE:
            raise OAuthRequestError("state is too long.")
        txn = mint_secret()
        now = self._clock()
        self._creds.add(
            OAuthAuthorizationRequest(
                id=hash_secret(txn),
                client_id=client_id,
                redirect_uri=redirect_uri,
                redirect_uri_provided_explicitly=request.redirect_uri_provided_explicitly,
                code_challenge=request.code_challenge,
                state=request.state,
                scopes=list(request.scopes),
                resource=audience,
                created_at=now,
                expires_at=now + self._config.request_ttl,
            )
        )
        await self._creds.commit()
        return with_query(self._config.consent_url, txn=txn)

    def _bind_audience(self, requested: str | None) -> str:
        """RFC 8707 (D7): a missing resource is bound to ours anyway."""
        if requested is None:
            return self._config.resource
        if not self._same_audience(requested):
            raise OAuthRequestError(
                f"Tokens here are only for {self._config.resource}."
            )
        return self._config.resource

    def _same_audience(self, audience: str) -> bool:
        expected = canonical_resource(self._config.resource)
        return expected is not None and canonical_resource(audience) == expected

    async def pending_request(self, txn: str) -> PendingAuthorization | None:
        row = await self._creds.pending_request(hash_secret(txn), self._clock())
        if row is None:
            return None
        client = await self.get_client(row.client_id)
        if client is None or row.redirect_uri not in client.redirect_uris:
            return None
        return PendingAuthorization(
            client_id=row.client_id,
            client_name=client.client_name or UNNAMED_CLIENT,
            redirect_uri=row.redirect_uri,
            redirect_host=_redirect_host(row.redirect_uri),
            loopback=is_loopback_redirect(row.redirect_uri),
            expires_at=_as_utc(row.expires_at),
        )

    async def _consume(self, txn: str, now: datetime) -> OAuthAuthorizationRequest:
        """Single use (D36). A client revoked meanwhile leaves the request as it was
        and issues nothing."""
        request = await self._creds.consume_request(hash_secret(txn), now)
        if request is None:
            raise AuthorizationRequestNotFoundError
        client = await self.get_client(request.client_id)
        if client is None or request.redirect_uri not in client.redirect_uris:
            await self._creds.rollback()
            raise AuthorizationRequestNotFoundError
        return request

    async def approve(self, txn: str, user_id: UUID) -> str:
        """Consumes the request once and returns the redirect carrying a code bound
        to `user_id` (the caller has checked eligibility). Raises
        AuthorizationRequestNotFoundError."""
        now = self._clock()
        request = await self._consume(txn, now)
        raw = mint_secret()
        family_id = uuid4()
        self._creds.add(
            OAuthCode(
                code_hash=hash_secret(raw),
                client_id=request.client_id,
                user_id=user_id,
                family_id=family_id,
                code_challenge=request.code_challenge,
                redirect_uri=request.redirect_uri,
                redirect_uri_provided_explicitly=request.redirect_uri_provided_explicitly,
                resource=request.resource,
                scopes=request.scopes,
                created_at=now,
                expires_at=now + self._config.code_ttl,
            )
        )
        self._creds.add(
            CredentialEvent(
                event=EVENT_CONSENT_APPROVED,
                via="oauth",
                user_id=user_id,
                actor_user_id=user_id,
                client_id=request.client_id,
                details={"family_id": str(family_id)},
            )
        )
        await self._creds.commit()
        return with_query(request.redirect_uri, code=raw, state=request.state)

    async def deny(self, txn: str, user_id: UUID) -> str:
        """Consumes the request and returns the access_denied redirect."""
        request = await self._consume(txn, self._clock())
        self._creds.add(
            CredentialEvent(
                event=EVENT_CONSENT_DENIED,
                via="oauth",
                user_id=user_id,
                actor_user_id=user_id,
                client_id=request.client_id,
            )
        )
        await self._creds.commit()
        return with_query(
            request.redirect_uri, error="access_denied", state=request.state
        )

    # ---- codes ----------------------------------------------------------------------

    async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        """None for unknown, foreign or reused codes. A used code revokes its family
        whoever presents it. Expiry is the SDK's check (C14). An unexpected database
        error is None too (fail closed)."""
        try:
            return await self._load_code(client_id, raw_code)
        except DBAPIError as exc:
            await self._database_error(exc)
            return None

    async def _load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        row = await self._creds.code_by_hash(hash_secret(raw_code))
        if row is None:
            return None
        if row.used_at is not None:
            family = _Family(row.family_id, row.user_id, row.client_id)
            await self._revoke_family(
                family,
                REVOKED_CODE_REUSE,
                kind="code",
                extra_details=_presenter(row.client_id, client_id),
            )
            return None
        if row.client_id != client_id:
            return None
        return _code_grant(row, display_prefix(raw_code))

    async def exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        """Exactly one exchange of a code succeeds; a second one (reuse or a lost
        race) revokes the family, the winner's tokens included (D30, C8). Raises
        OAuthGrantError, also for an unexpected database error."""
        return await self._db_errors_as_grant_errors(
            self._exchange_code(client_id, grant, eligible)
        )

    async def _exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        if grant.client_id != client_id:
            raise OAuthGrantError(_DEAD_CODE)
        family = _Family(grant.family_id, grant.user_id, client_id)
        now = await self._enter_family(family)
        if not await self._creds.mark_code_used(grant.code_id, now):
            await self._creds.rollback()
            fresh = await self._creds.code(grant.code_id, fresh=True)
            if fresh is not None and fresh.used_at is not None:
                await self._revoke_family(family, REVOKED_CODE_REUSE, kind="code")
            raise OAuthGrantError(_DEAD_CODE)
        denial = await self._issue_denial(family, grant.resource, eligible)
        if denial is not None:
            await self._creds.commit()  # the code stays used; nothing is issued
            logger.info(
                "oauth.code_refused", reason=denial, family_id=str(grant.family_id)
            )
            raise OAuthGrantError(_INELIGIBLE)
        return await self._issue_pair(family, now, EVENT_TOKENS_ISSUED)

    # ---- refresh --------------------------------------------------------------------

    async def load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        """None for non-refresh or unknown tokens; a cross-client presentation revokes
        the family (no grace across clients). Revoked rows load too: rotation
        decides between grace and reuse. An unexpected database error is None too
        (fail closed)."""
        try:
            return await self._load_refresh(client_id, raw_refresh)
        except DBAPIError as exc:
            await self._database_error(exc)
            return None

    async def _load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        if kind_of(raw_refresh) is not TokenKind.OAUTH_REFRESH:
            return None
        row = await self._creds.token_by_hash(hash_secret(raw_refresh))
        if row is None or row.kind != TokenKind.OAUTH_REFRESH or row.family_id is None:
            return None
        if row.client_id != client_id:
            family = _Family(row.family_id, row.user_id, row.client_id or client_id)
            await self._revoke_family(
                family,
                REVOKED_CROSS_CLIENT,
                kind="refresh",
                extra_details=_presenter(family.client_id, client_id),
            )
            return None
        return RefreshGrant(
            token_id=row.id,
            family_id=row.family_id,
            client_id=client_id,
            user_id=row.user_id,
            resource=row.audience or "",
            expires_at=_as_utc(row.expires_at),
            display=row.prefix,
        )

    async def rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        """Rotation with reuse detection and a 30 s same-client grace (D6). Every
        refresh re-checks the user, mcp:use, the client and the audience. Raises
        OAuthGrantError, also for an unexpected database error."""
        return await self._db_errors_as_grant_errors(
            self._rotate_refresh(client_id, grant, eligible)
        )

    async def _rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        row = await self._creds.token(grant.token_id, fresh=True)
        if (
            row is None
            or row.client_id != client_id
            or row.family_id != grant.family_id
            or row.kind != TokenKind.OAUTH_REFRESH
        ):
            raise OAuthGrantError(_DEAD_REFRESH)
        family = _Family(grant.family_id, row.user_id, client_id)
        audience = row.audience or ""
        # Held until the commit: a family revoke cannot slip in between marking
        # this token rotated and inserting its successor.
        now = await self._enter_family(family)
        if row.revoked_at is None and _as_utc(row.expires_at) <= now:
            await self._creds.rollback()
            raise OAuthGrantError(_DEAD_REFRESH)
        if row.revoked_at is not None or not await self._creds.mark_rotated(
            row.id, now
        ):
            return await self._retry_or_reuse(grant.token_id, family, eligible)
        return await self._issue_checked(
            family, audience, eligible, now, EVENT_REFRESHED
        )

    async def _retry_or_reuse(
        self, token_id: UUID, family: _Family, eligible: Eligibility
    ) -> TokenPair:
        """The presented token was already rotated or revoked: a same-client retry
        within the grace gets a fresh pair; anything else is reuse. The grace check
        (the family still has a live token) runs under the family lock, so a
        concurrent revoke either lands first and is seen, or waits for the issue
        and then covers the new pair too."""
        await self._creds.rollback()
        now = await self._enter_family(family)
        row = await self._creds.token(token_id, fresh=True)
        if row is not None and await self._in_grace(row, now):
            audience = row.audience or ""
            return await self._issue_checked(
                family, audience, eligible, now, EVENT_REFRESH_GRACE
            )
        await self._revoke_family(family, REVOKED_REFRESH_REUSE, kind="refresh")
        raise OAuthGrantError(_DEAD_REFRESH)

    async def _enter_family(self, family: _Family) -> datetime:
        """Takes the locks an issuing transaction needs, in the one global order:
        the client row first (revoke_client locks it and then the client's token
        rows), then the family lock, and only then token or code rows. Returns
        the time after the waits, so a lock wait never stretches a window such as
        the refresh grace."""
        await self._creds.touch_client(family.client_id, self._clock())
        await self._creds.lock_family(family.family_id)
        return self._clock()

    async def _db_errors_as_grant_errors(
        self, issuing: Awaitable[TokenPair]
    ) -> TokenPair:
        """Defence in depth for the SDK token handler: an unexpected database error
        (a deadlock, a lost connection) becomes a generic invalid_grant, never a
        500 with a stack. Logged by type only: the statement may carry hashes."""
        try:
            return await issuing
        except DBAPIError as exc:
            await self._database_error(exc)
            raise OAuthGrantError(_UNAVAILABLE) from None

    async def _database_error(self, exc: DBAPIError) -> None:
        """Logs a database error by type only (the statement may carry hashes) and
        leaves the session usable."""
        logger.error("oauth.database_error", error=type(exc).__name__)
        with suppress(DBAPIError):
            await self._creds.rollback()

    async def _in_grace(self, row: ApiToken, now: datetime) -> bool:
        """A concurrent retry by the same client (already checked) within 30 s, while
        the family is still alive. A family revoke never overwrites 'rotated', hence
        the live-token check."""
        return (
            row.revoked_reason == REVOKED_ROTATED
            and row.revoked_at is not None
            and now - _as_utc(row.revoked_at) <= self._config.refresh_grace
            and row.family_id is not None
            and await self._creds.family_has_live_token(row.family_id, now)
        )

    # ---- issuing and revoking --------------------------------------------------------

    async def _issue_denial(
        self, family: _Family, audience: str, eligible: Eligibility
    ) -> str | None:
        """Why tokens may not be issued now (a revoke reason), or None."""
        user = await self._users.get(family.user_id)
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.kind != UserKind.HUMAN
        ):
            return REVOKED_USER_DISABLED
        if await self.get_client(family.client_id) is None:
            return REVOKED_CLIENT
        if not self._same_audience(audience):
            return REVOKED_AUDIENCE_CHANGED
        if not await _is_eligible(eligible, family.user_id):
            return REVOKED_NO_MCP_USE
        return None

    async def _issue_checked(
        self,
        family: _Family,
        audience: str,
        eligible: Eligibility,
        now: datetime,
        event: str,
    ) -> TokenPair:
        """Issues a pair after the per-refresh checks; a failed check revokes the
        whole family with that reason."""
        denial = await self._issue_denial(family, audience, eligible)
        if denial is not None:
            await self._creds.rollback()
            await self._revoke_family(family, denial)
            raise OAuthGrantError(_DEAD_REFRESH)
        return await self._issue_pair(family, now, event)

    async def _issue_pair(
        self, family: _Family, now: datetime, event: str
    ) -> TokenPair:
        audience = self._config.resource
        access, access_raw = _mint_row(
            TokenKind.OAUTH_ACCESS, family, audience, now, self._config.access_ttl
        )
        refresh, refresh_raw = _mint_row(
            TokenKind.OAUTH_REFRESH, family, audience, now, self._config.refresh_ttl
        )
        self._creds.add(access)
        self._creds.add(refresh)
        self._creds.add(
            CredentialEvent(
                event=event,
                via="oauth",
                user_id=family.user_id,
                client_id=family.client_id,
                token_id=refresh.id,
                details={
                    "family_id": str(family.family_id),
                    "access_token_id": str(access.id),
                },
            )
        )
        await self._creds.commit()
        logger.info(event, family_id=str(family.family_id))
        return TokenPair(
            access_token=access_raw,
            refresh_token=refresh_raw,
            expires_in=int(self._config.access_ttl.total_seconds()),
            family_id=family.family_id,
            user_id=family.user_id,
        )

    async def _revoke_family(
        self,
        family: _Family,
        reason: str,
        *,
        kind: ReuseKind | None = None,
        extra_details: Mapping[str, str] | None = None,
    ) -> None:
        """Revokes every live row of the family (under the family lock, taken by the
        repository) and records why, then commits. The event's client_id is the
        family's client; `extra_details` adds forensics such as the presenter."""
        await self._creds.revoke_family(family.family_id, reason, self._clock())
        family_id = str(family.family_id)
        if reason in _REUSE_REASONS:
            event = EVENT_REUSE_DETECTED
            details: dict[str, Any] = {"family_id": family_id, "kind": kind}
            logger.warning(EVENT_REUSE_DETECTED, family_id=family_id, kind=kind)
        else:
            event = EVENT_FAMILY_REVOKED
            details = {"family_id": family_id, "reason": reason}
            logger.info(EVENT_FAMILY_REVOKED, family_id=family_id, reason=reason)
        self._creds.add(
            CredentialEvent(
                event=event,
                via="oauth",
                user_id=family.user_id,
                client_id=family.client_id,
                details=details | dict(extra_details or {}),
            )
        )
        await self._creds.commit()

    async def find_access_token(self, raw_access: str) -> AccessTokenRef | None:
        """RFC 7009 lookup of an OAuth access token: expired, revoked or owned by a
        disabled user alike, and without touching `last_used_at` (unlike the bearer
        door), so a client can always revoke what it holds. None for anything else."""
        if kind_of(raw_access) is not TokenKind.OAUTH_ACCESS:
            return None
        row = await self._creds.token_by_hash(hash_secret(raw_access))
        if row is None or row.kind != TokenKind.OAUTH_ACCESS or row.client_id is None:
            return None
        return AccessTokenRef(token_id=row.id, client_id=row.client_id)

    async def revoke_by_token_id(self, token_id: UUID) -> None:
        """RFC 7009: revokes the token's whole family. Unknown and non-OAuth tokens
        are ignored (the endpoint answers 200 regardless)."""
        row = await self._creds.token(token_id, fresh=True)
        if row is None or row.family_id is None or row.client_id is None:
            return
        family = _Family(row.family_id, row.user_id, row.client_id)
        await self._revoke_family(family, REVOKED_OAUTH_REVOKE)

    # ---- maintenance ----------------------------------------------------------------

    async def gc(self) -> GcReport:
        """delete_stale, then a credentials.gc event with the counts."""
        counts = await self._creds.delete_stale(self._clock())
        self._creds.add(
            CredentialEvent(event=EVENT_GC, via="system", details=asdict(counts))
        )
        await self._creds.commit()
        logger.info(EVENT_GC, **asdict(counts))
        return counts

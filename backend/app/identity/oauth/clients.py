"""OAuth clients: dynamic registration (RFC 7591) with allowlisted redirects,
lookup, revocation and the admin listing."""

from collections.abc import Callable, Collection
from datetime import datetime
from typing import Final

import structlog

from app.identity.api_tokens import (
    EVENT_CLIENT_REGISTERED,
    EVENT_CLIENT_REVOKED,
    REVOKED_CLIENT,
    UNNAMED_CLIENT,
    CredentialActor,
    hash_secret,
)
from app.identity.clock import as_utc
from app.identity.models import CredentialEvent, OAuthClient
from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.errors import OAuthRegistrationError
from app.identity.oauth.urls import canonical_redirect, redirect_allowed, redirect_host
from app.identity.oauth.values import (
    PUBLIC_METHOD,
    ClientRegistration,
    ClientSummary,
    RegisteredClient,
)
from app.identity.repository import CredentialRepository

logger = structlog.get_logger()

MAX_REDIRECT_URIS: Final = 5
MAX_CLIENT_NAME: Final = 100
MAX_SOFTWARE_ID: Final = 200

_AUTH_METHODS: Final = frozenset(
    {PUBLIC_METHOD, "client_secret_post", "client_secret_basic"}
)
_GRANT_TYPES: Final = frozenset({"authorization_code", "refresh_token"})
_RESPONSE_TYPES: Final = ("code",)


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
            (method == PUBLIC_METHOD) != (registration.client_secret is None),
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


class ClientService:
    """Registers, looks up, revokes and lists OAuth clients."""

    def __init__(
        self,
        creds: CredentialRepository,
        config: OAuthConfig,
        clock: Callable[[], datetime],
    ) -> None:
        self._creds = creds
        self._config = config
        self._clock = clock

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
                    canonical_redirect(uri) for uri in registration.redirect_uris
                ],
                token_endpoint_auth_method=method,
                client_secret_hash=hash_secret(secret) if secret is not None else None,
                grant_types=list(registration.grant_types),
                response_types=list(registration.response_types),
                software_id=registration.software_id,
                registered_at=self._clock(),
            )
        )
        hosts = [redirect_host(uri) for uri in registration.redirect_uris]
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
        row = await self._creds.clients.client(client_id)
        if row is None or row.revoked_at is not None:
            return None
        hosted = self._config.hosted_redirect_uris
        allowed = tuple(
            canonical_redirect(uri)
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
            registered_at=as_utc(row.registered_at),
            secret_hash=row.client_secret_hash,
        )

    async def revoke_client(self, client_id: str, *, actor: CredentialActor) -> bool:
        """Revokes the client, all its tokens and its unused codes; writes
        client.revoked. False when the client is unknown or already revoked."""
        now = self._clock()
        if not await self._creds.clients.revoke_client(client_id, now):
            return False
        tokens = await self._creds.tokens.revoke_client_tokens(
            client_id, REVOKED_CLIENT, now
        )
        codes = await self._creds.codes.spend_client_codes(client_id, now)
        self._creds.add(
            CredentialEvent(
                event=EVENT_CLIENT_REVOKED,
                via=actor.via,
                actor_user_id=actor.user_id,
                client_id=client_id,
                details={"tokens": tokens, "codes": codes},
            )
        )
        await self._creds.commit()
        logger.info("oauth.client_revoked", client_id=client_id, tokens=tokens)
        return True

    async def list_clients(self) -> list[ClientSummary]:
        rows = await self._creds.clients.list_clients()
        families = await self._creds.families.live_family_counts(self._clock())
        return [
            ClientSummary(
                client_id=row.client_id,
                client_name=row.client_name or UNNAMED_CLIENT,
                redirect_uris=tuple(row.redirect_uris),
                token_endpoint_auth_method=row.token_endpoint_auth_method,
                registered_at=as_utc(row.registered_at),
                revoked_at=as_utc(row.revoked_at) if row.revoked_at else None,
                active_families=families.get(row.client_id, 0),
            )
            for row in rows
        ]

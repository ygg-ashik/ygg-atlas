"""The /authorize step: a pending request stored under hash(txn), shown on the
consent page, then approved (a single-use code) or denied, exactly once."""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from app.identity.api_tokens import (
    EVENT_CONSENT_APPROVED,
    EVENT_CONSENT_DENIED,
    UNNAMED_CLIENT,
    hash_secret,
    mint_secret,
)
from app.identity.clock import as_utc
from app.identity.models import CredentialEvent, OAuthAuthorizationRequest, OAuthCode
from app.identity.oauth.clients import ClientService
from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.errors import (
    AuthorizationRequestNotFoundError,
    OAuthRequestError,
)
from app.identity.oauth.urls import (
    canonical_redirect,
    is_loopback_redirect,
    redirect_host,
    same_audience,
    with_query,
)
from app.identity.oauth.values import AuthorizationRequestData, PendingAuthorization
from app.identity.repository import CredentialRepository

MAX_STATE: Final = 500

_CHALLENGE: Final = re.compile(r"[A-Za-z0-9_-]{43}")  # base64url(SHA-256), RFC 7636


class AuthorizationService:
    """Begins, shows, approves and denies pending authorization requests."""

    def __init__(
        self,
        creds: CredentialRepository,
        config: OAuthConfig,
        clock: Callable[[], datetime],
        clients: ClientService,
    ) -> None:
        self._creds = creds
        self._config = config
        self._clock = clock
        self._clients = clients

    async def begin_authorization(
        self, client_id: str, request: AuthorizationRequestData
    ) -> str:
        """Stores the request under hash(txn) and returns the consent URL with txn.
        Raises OAuthRequestError."""
        client = await self._clients.get_client(client_id)
        redirect_uri = canonical_redirect(request.redirect_uri)
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
        if not same_audience(self._config.resource, requested):
            raise OAuthRequestError(
                f"Tokens here are only for {self._config.resource}."
            )
        return self._config.resource

    async def pending_request(self, txn: str) -> PendingAuthorization | None:
        row = await self._creds.codes.pending_request(hash_secret(txn), self._clock())
        if row is None:
            return None
        client = await self._clients.get_client(row.client_id)
        if client is None or row.redirect_uri not in client.redirect_uris:
            return None
        return PendingAuthorization(
            client_id=row.client_id,
            client_name=client.client_name or UNNAMED_CLIENT,
            redirect_uri=row.redirect_uri,
            redirect_host=redirect_host(row.redirect_uri),
            loopback=is_loopback_redirect(row.redirect_uri),
            expires_at=as_utc(row.expires_at),
        )

    async def _consume(self, txn: str, now: datetime) -> OAuthAuthorizationRequest:
        """Single use (D36). A client revoked meanwhile leaves the request as it was
        and issues nothing."""
        request = await self._creds.codes.consume_request(hash_secret(txn), now)
        if request is None:
            raise AuthorizationRequestNotFoundError
        client = await self._clients.get_client(request.client_id)
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

"""OAuthService: the one object app/mcp holds per request. It composes the step
services over one session, so they share the session, the config and the clock."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.api_tokens import CredentialActor
from app.identity.clock import utcnow
from app.identity.oauth.authorization import AuthorizationService
from app.identity.oauth.clients import ClientService
from app.identity.oauth.codes import CodeExchange
from app.identity.oauth.config import OAuthConfig
from app.identity.oauth.families import TokenFamilies
from app.identity.oauth.refresh import RefreshRotation
from app.identity.oauth.revocation import RevocationService
from app.identity.oauth.values import (
    AccessTokenRef,
    AuthorizationRequestData,
    ClientRegistration,
    ClientSummary,
    CodeGrant,
    Eligibility,
    GcReport,
    PendingAuthorization,
    RefreshGrant,
    RegisteredClient,
    TokenPair,
)
from app.identity.repository import CredentialRepository, UserRepository


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
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        creds = CredentialRepository(db)
        clients = ClientService(creds, config, clock)
        families = TokenFamilies(creds, UserRepository(db), config, clock, clients)
        self._clients = clients
        self._authorization = AuthorizationService(creds, config, clock, clients)
        self._codes = CodeExchange(creds, families)
        self._refresh = RefreshRotation(creds, config, families)
        self._revocation = RevocationService(creds, clock, families)

    async def register_client(self, registration: ClientRegistration) -> None:
        await self._clients.register_client(registration)

    async def get_client(self, client_id: str) -> RegisteredClient | None:
        return await self._clients.get_client(client_id)

    async def revoke_client(self, client_id: str, *, actor: CredentialActor) -> bool:
        return await self._clients.revoke_client(client_id, actor=actor)

    async def list_clients(self) -> list[ClientSummary]:
        return await self._clients.list_clients()

    async def begin_authorization(
        self, client_id: str, request: AuthorizationRequestData
    ) -> str:
        return await self._authorization.begin_authorization(client_id, request)

    async def pending_request(self, txn: str) -> PendingAuthorization | None:
        return await self._authorization.pending_request(txn)

    async def approve(self, txn: str, user_id: UUID) -> str:
        return await self._authorization.approve(txn, user_id)

    async def deny(self, txn: str, user_id: UUID) -> str:
        return await self._authorization.deny(txn, user_id)

    async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        return await self._codes.load_code(client_id, raw_code)

    async def exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        return await self._codes.exchange_code(client_id, grant, eligible)

    async def load_refresh(
        self, client_id: str, raw_refresh: str
    ) -> RefreshGrant | None:
        return await self._refresh.load_refresh(client_id, raw_refresh)

    async def rotate_refresh(
        self, client_id: str, grant: RefreshGrant, eligible: Eligibility
    ) -> TokenPair:
        return await self._refresh.rotate_refresh(client_id, grant, eligible)

    async def find_access_token(self, raw_access: str) -> AccessTokenRef | None:
        return await self._revocation.find_access_token(raw_access)

    async def revoke_by_token_id(self, token_id: UUID) -> None:
        await self._revocation.revoke_by_token_id(token_id)

    async def gc(self) -> GcReport:
        return await self._revocation.gc()

"""The authorization-code grant: load a code, then exchange it exactly once. A used
code presented again revokes its whole family."""

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.identity.api_tokens import (
    EVENT_TOKENS_ISSUED,
    REVOKED_CODE_REUSE,
    display_prefix,
    hash_secret,
)
from app.identity.clock import as_utc
from app.identity.models import OAuthCode
from app.identity.oauth.errors import (
    DEAD_CODE,
    INELIGIBLE,
    GrantUnavailableError,
    OAuthGrantError,
)
from app.identity.oauth.families import Family, TokenFamilies, presenter
from app.identity.oauth.values import CodeGrant, Eligibility, TokenPair
from app.identity.repository import CredentialRepository

logger = structlog.get_logger()


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
        expires_at=as_utc(row.expires_at),
        display=display,
    )


class CodeExchange:
    """Loads and exchanges single-use authorization codes."""

    def __init__(self, creds: CredentialRepository, families: TokenFamilies) -> None:
        self._creds = creds
        self._families = families

    async def load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        """None for unknown, foreign or reused codes. A used code revokes its family
        whoever presents it. Expiry is the SDK's check. An unexpected database
        error raises GrantUnavailableError."""
        try:
            return await self._load_code(client_id, raw_code)
        except SQLAlchemyError as exc:
            await self._families.database_error(exc, op="load_code")
            raise GrantUnavailableError from None

    async def _load_code(self, client_id: str, raw_code: str) -> CodeGrant | None:
        row = await self._creds.codes.code_by_hash(hash_secret(raw_code))
        if row is None:
            return None
        if row.used_at is not None:
            family = Family(row.family_id, row.user_id, row.client_id)
            await self._families.revoke(
                family,
                REVOKED_CODE_REUSE,
                kind="code",
                extra_details=presenter(row.client_id, client_id),
            )
            return None
        if row.client_id != client_id:
            return None
        return _code_grant(row, display_prefix(raw_code))

    async def exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        """Exactly one exchange of a code succeeds; a second one (reuse or a lost
        race) revokes the family, the winner's tokens included. Raises
        OAuthGrantError, or GrantUnavailableError for a transient failure."""
        return await self._families.db_errors_as_unavailable(
            self._exchange_code(client_id, grant, eligible), op="exchange_code"
        )

    async def _exchange_code(
        self, client_id: str, grant: CodeGrant, eligible: Eligibility
    ) -> TokenPair:
        if grant.client_id != client_id:
            raise OAuthGrantError(DEAD_CODE)
        family = Family(grant.family_id, grant.user_id, client_id)
        now = await self._families.enter(family)
        if not await self._creds.codes.mark_code_used(grant.code_id, now):
            await self._creds.rollback()
            fresh = await self._creds.codes.code(grant.code_id, fresh=True)
            if fresh is not None and fresh.used_at is not None:
                await self._families.revoke(family, REVOKED_CODE_REUSE, kind="code")
            raise OAuthGrantError(DEAD_CODE)
        denial = await self._families.checked_denial(family, grant.resource, eligible)
        if denial is not None:
            await self._creds.commit()  # the code stays used; nothing is issued
            logger.info(
                "oauth.code_refused", reason=denial, family_id=str(grant.family_id)
            )
            raise OAuthGrantError(INELIGIBLE)
        return await self._families.issue_pair(family, now, EVENT_TOKENS_ISSUED)
